"""Download SPK and BDDK regulations (communiqués and regulations) plus the two framework laws from mevzuat.gov.tr.

Legislation is not protected by copyright in Türkiye (Law No. 5846, Art. 31).
Output: data/raw/mevzuat/<doc_id>.json and the `mevzuat` rows of data/manifest.csv.

Usage: python data/download_mevzuat.py [--limit N]
"""

import argparse
import re

from bs4 import BeautifulSoup

from common import PoliteSession, html_to_text, manifest_row, save_doc, write_manifest

BASE = "https://www.mevzuat.gov.tr"
SOURCE = "mevzuat"
PAGE_SIZE = 50  # the datatable endpoint rejects large pages

# (regulator, KurumId, AltKurumId). Each regulator appears under two parent institutions
# on mevzuat.gov.tr (the former Prime Ministry and the Ministry of Treasury and Finance).
INSTITUTIONS = [
    ("SPK", "3", "44"),
    ("SPK", "578", "1696"),
    ("BDDK", "3", "42"),
    ("BDDK", "578", "1698"),
]
DOC_TYPES = {"Teblig": "teblig", "TumYonetmelik": "yonetmelik"}

# Framework laws: 6362 Capital Markets Law, 5411 Banking Law.
LAWS = [
    {"regulator": "SPK", "mevzuatNo": "6362", "mevzuatTur": 1, "mevzuatTertip": 5,
     "mevAdi": "SERMAYE PİYASASI KANUNU", "resmiGazeteTarihi": "30.12.2012"},
    {"regulator": "BDDK", "mevzuatNo": "5411", "mevzuatTur": 1, "mevzuatTertip": 5,
     "mevAdi": "BANKACILIK KANUNU", "resmiGazeteTarihi": "01.11.2005"},
]


def antiforgery_token(http: PoliteSession) -> str:
    html = http.get(BASE + "/").text
    return re.search(r'name="antiforgerytoken"[^>]*value="([^"]+)"', html).group(1)


def list_documents(http: PoliteSession, token: str, doc_type: str, kurum: str, alt_kurum: str) -> list[dict]:
    rows, start = [], 0
    while True:
        body = {
            "draw": 1, "columns": [], "order": [], "start": start, "length": PAGE_SIZE,
            "search": {"value": "", "regex": False},
            "parameters": {
                "MevzuatTur": doc_type, "YonetmelikMevzuatTur": "OsmanliKanunu",
                "AranacakIfade": "", "AranacakYer": "2", "KurumId": kurum, "AltKurumId": alt_kurum,
                "BaslangicTarihi": "", "BitisTarihi": "", "antiforgerytoken": token,
            },
        }
        data = http.post(BASE + "/Anasayfa/MevzuatDatatable", json=body,
                         headers={"X-Requested-With": "XMLHttpRequest"}).json()
        rows += data["data"]
        start += PAGE_SIZE
        if start >= data["recordsTotal"]:
            return rows


def fetch_text(http: PoliteSession, item: dict) -> str:
    url = (f"{BASE}/anasayfa/MevzuatFihristDetayIframe?MevzuatTur={item['mevzuatTur']}"
           f"&MevzuatNo={item['mevzuatNo']}&MevzuatTertip={item['mevzuatTertip']}")
    return html_to_text(BeautifulSoup(http.get(url).text, "html.parser"))


def to_iso(tr_date: str) -> str:
    """'30.12.2012' -> '2012-12-30'; empty if missing."""
    parts = (tr_date or "").split(".")
    return f"{parts[2]}-{parts[1]}-{parts[0]}" if len(parts) == 3 else ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="download at most N documents (for testing)")
    args = parser.parse_args()

    http = PoliteSession()
    token = antiforgery_token(http)

    items: dict[str, dict] = {}
    for law in LAWS:
        items[f"{law['mevzuatTur']}.{law['mevzuatTertip']}.{law['mevzuatNo']}"] = {**law, "kind": "kanun"}
    for regulator, kurum, alt_kurum in INSTITUTIONS:
        for doc_type, kind in DOC_TYPES.items():
            found = list_documents(http, token, doc_type, kurum, alt_kurum)
            print(f"{regulator} {kurum}/{alt_kurum} {kind}: {len(found)}")
            for item in found:
                key = f"{item['mevzuatTur']}.{item['mevzuatTertip']}.{item['mevzuatNo']}"
                items.setdefault(key, {**item, "regulator": regulator, "kind": kind})
    print(f"unique documents: {len(items)}")

    rows = []
    for i, (key, item) in enumerate(sorted(items.items())):
        if args.limit and i >= args.limit:
            break
        text = fetch_text(http, item)
        if not text:
            print(f"  skip {key}: empty text")
            continue
        doc = {
            "doc_id": f"mevzuat-{key}",
            "source": SOURCE,
            "category": f"{item['regulator']}-{item['kind']}",
            "date": to_iso(item.get("resmiGazeteTarihi")),
            "title": BeautifulSoup(item["mevAdi"], "html.parser").get_text().strip(),
            "url": (f"{BASE}/mevzuat?MevzuatNo={item['mevzuatNo']}"
                    f"&MevzuatTur={item['mevzuatTur']}&MevzuatTertip={item['mevzuatTertip']}"),
            "text": text,
        }
        save_doc(doc)
        rows.append(manifest_row(doc))
        print(f"  [{i + 1}/{len(items)}] {doc['doc_id']} {len(text):,} chars")

    write_manifest(SOURCE, rows)
    print(f"saved {len(rows)} documents")


if __name__ == "__main__":
    main()
