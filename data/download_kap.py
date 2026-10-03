"""Download a stratified sample of 2025 KAP (Public Disclosure Platform) material event disclosures.

KAP has no documented public API; this uses the endpoints behind kap.org.tr, so it may break
if the site changes. data/manifest.csv records exactly which disclosures were used.
Output: data/raw/kap/<doc_id>.json and the `kap` rows of data/manifest.csv.

Usage: python data/download_kap.py [--limit N] [--refresh-index]
"""

import argparse
import json
import random
import re
from collections import Counter
from datetime import date, timedelta

from bs4 import BeautifulSoup

from common import RAW_DIR, PoliteSession, clean_text, html_to_text, manifest_row, save_doc, write_manifest

BASE = "https://www.kap.org.tr"
SOURCE = "kap"
FROM_DATE, TO_DATE = date(2025, 1, 1), date(2025, 12, 31)
API_MAX_ROWS = 2000  # byCriteria silently truncates at this many rows
SEED = 42
MAX_PER_COMPANY = 2
MIN_CHARS = 200

# subject -> (quota, kind). "text" subjects carry a free-text explanation block with an
# English translation; "form" subjects are structured corporate-action forms (Turkish only).
# Subjects that mainly list individuals (e.g. insider share trades, board committees) are
# left out on purpose to keep personal data out of the corpus.
QUOTAS = {
    "Özel Durum Açıklaması (Genel)": (40, "text"),
    "Yeni İş İlişkisi": (20, "text"),
    "Kredi Derecelendirmesi": (15, "text"),
    "Finansal Duran Varlık Edinimi": (15, "text"),
    "İhale Süreci / Sonucu": (15, "text"),
    "Geleceğe Dönük Değerlendirmeler": (10, "text"),
    "Kar Payı Dağıtım İşlemlerine İlişkin Bildirim": (20, "form"),
    "Sermaye Artırımı - Azaltımı İşlemlerine İlişkin Bildirim": (15, "form"),
}
CATEGORY_SLUGS = {
    "Özel Durum Açıklaması (Genel)": "material-event",
    "Yeni İş İlişkisi": "new-business",
    "Kredi Derecelendirmesi": "credit-rating",
    "Finansal Duran Varlık Edinimi": "financial-asset-acquisition",
    "İhale Süreci / Sonucu": "tender",
    "Geleceğe Dönük Değerlendirmeler": "forward-looking",
    "Kar Payı Dağıtım İşlemlerine İlişkin Bildirim": "dividend",
    "Sermaye Artırımı - Azaltımı İşlemlerine İlişkin Bildirim": "capital-change",
}

INDEX_PATH = RAW_DIR / SOURCE / "_index.json"


def list_window(http: PoliteSession, start: date, end: date) -> list[dict]:
    """List all ODA disclosures in [start, end], splitting the window when the API truncates."""
    body = {
        "fromDate": start.isoformat(), "toDate": end.isoformat(), "disclosureClass": "ODA",
        "subjectList": [], "mkkMemberOidList": [], "inactiveMkkMemberOidList": [],
        "bdkMemberOidList": [], "fromSrc": False, "disclosureIndexList": [],
    }
    rows = http.post(f"{BASE}/tr/api/disclosure/members/byCriteria", json=body).json()
    if len(rows) < API_MAX_ROWS:
        return rows
    if start == end:
        raise RuntimeError(f"more than {API_MAX_ROWS} disclosures on {start}; cannot split further")
    mid = start + (end - start) // 2
    return list_window(http, start, mid) + list_window(http, mid + timedelta(days=1), end)


def build_index(http: PoliteSession) -> list[dict]:
    rows, start = [], FROM_DATE
    while start <= TO_DATE:
        end = min(start + timedelta(days=6), TO_DATE)
        rows += list_window(http, start, end)
        print(f"  listed {start} .. {end}: {len(rows)} total")
        start = end + timedelta(days=1)
    unique = {r["disclosureIndex"]: r for r in rows}
    return sorted(unique.values(), key=lambda r: r["disclosureIndex"])


def rsc_text_records(page: str) -> str:
    """Return the HTML text records embedded in the Next.js (RSC) payload of a disclosure page."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', page)
    payload = "".join(json.loads(f'"{c}"') for c in chunks).encode("utf-8")
    records = []
    # Text records look like `<id>:T<hex byte length>,<content>`.
    for m in re.finditer(rb"(?:^|\n|\])([0-9a-f]+):T([0-9a-f]+),", payload):
        length = int(m.group(2), 16)
        records.append(payload[m.end():m.end() + length].decode("utf-8", "replace"))
    return "".join(records)


def extract(page: str, kind: str) -> tuple[str, str]:
    """Return (turkish_text, english_text) for one disclosure page."""
    soup = BeautifulSoup(rsc_text_records(page), "html.parser")
    if kind == "text":
        def block(lang: str) -> str:
            cells = soup.select(f"td.taxonomy-context-value-summernote.content-{lang}")
            return clean_text("\n\n".join(html_to_text(c) for c in cells))
        return block("tr"), block("en")
    for el in soup.select(".content-en"):
        el.decompose()
    # Form cells are nested tables/divs; one line per cell is enough.
    return re.sub(r"\n+", "\n", html_to_text(soup)), ""


def to_iso(kap_date: str) -> str:
    day, month, rest = kap_date.split(".")
    return f"{rest[:4]}-{month}-{day}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="download at most N documents (for testing)")
    parser.add_argument("--refresh-index", action="store_true", help="re-list disclosures even if cached")
    args = parser.parse_args()

    http = PoliteSession(delay=2.0)  # KAP returns 429 after a few hundred requests at 1 req/s
    if INDEX_PATH.exists() and not args.refresh_index:
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    else:
        index = build_index(http)
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(f"index: {len(index)} disclosures between {FROM_DATE} and {TO_DATE}")

    candidates = [
        r for r in index
        if r["subject"] in QUOTAS
        and (QUOTAS[r["subject"]][1] == "form" or r["hasMultiLanguageSupport"])
    ]
    random.Random(SEED).shuffle(candidates)

    taken: Counter = Counter()
    per_company: Counter = Counter()
    target = sum(q for q, _ in QUOTAS.values())
    rows = []
    for r in candidates:
        if len(rows) >= (args.limit or target):
            break
        subject = r["subject"]
        quota, kind = QUOTAS[subject]
        company = r["kapTitle"]
        if taken[subject] >= quota or per_company[company] >= MAX_PER_COMPANY:
            continue
        url = f"{BASE}/tr/Bildirim/{r['disclosureIndex']}"
        cached = RAW_DIR / SOURCE / f"kap-{r['disclosureIndex']}.json"
        if cached.exists():
            # Resume after an interrupted run without re-fetching.
            text, text_en = (json.loads(cached.read_text(encoding="utf-8"))[k] for k in ("text", "text_en"))
        else:
            text, text_en = extract(http.get(url).text, kind)
        if len(text) < MIN_CHARS:
            continue
        doc = {
            "doc_id": f"kap-{r['disclosureIndex']}",
            "source": SOURCE,
            "category": CATEGORY_SLUGS[subject],
            "date": to_iso(r["publishDate"]),
            "title": f"{company} - {subject}",
            "url": url,
            "company": company,
            "stock_codes": r.get("stockCodes") or "",
            "summary": (r.get("summary") or "").strip(),
            "text": text,
            "text_en": text_en,
        }
        save_doc(doc)
        rows.append(manifest_row(doc))
        taken[subject] += 1
        per_company[company] += 1
        print(f"  [{len(rows)}/{target}] {doc['doc_id']} {doc['category']} {len(text):,} chars"
              f"{' +en' if text_en else ''}")

    write_manifest(SOURCE, rows)
    print(f"saved {len(rows)} documents")
    for subject, (quota, _) in QUOTAS.items():
        if taken[subject] < quota and not args.limit:
            print(f"  warning: {CATEGORY_SLUGS[subject]} has {taken[subject]}/{quota}")


if __name__ == "__main__":
    main()
