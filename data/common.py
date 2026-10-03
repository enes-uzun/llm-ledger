"""Shared helpers for the download scripts: polite HTTP session, text cleanup, manifest I/O."""

import csv
import hashlib
import json
import re
import time
from pathlib import Path

import requests
from bs4 import Comment, Tag

DATA_DIR = Path(__file__).resolve().parent
RAW_DIR = DATA_DIR / "raw"
MANIFEST_PATH = DATA_DIR / "manifest.csv"

MANIFEST_FIELDS = ["doc_id", "source", "category", "date", "title", "url", "has_en", "chars", "sha256"]

USER_AGENT = "llm-ledger-research/0.1 (+https://github.com/enes-uzun/llm-ledger)"


class PoliteSession:
    """requests.Session wrapper that waits `delay` seconds between requests and retries on failure."""

    def __init__(self, delay: float = 1.0, retries: int = 5):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.delay = delay
        self.retries = retries
        self._last = 0.0

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 60)
        for attempt in range(1, self.retries + 1):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                resp = self.session.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                if attempt == self.retries:
                    raise
                status = getattr(e.response, "status_code", None)
                if status == 429:
                    # Rate limited: honour Retry-After, otherwise back off for minutes, not seconds.
                    retry_after = e.response.headers.get("Retry-After", "")
                    pause = int(retry_after) if retry_after.isdigit() else 60 * attempt
                    print(f"  rate limited, waiting {pause}s")
                    time.sleep(pause)
                else:
                    time.sleep(2**attempt)
        raise AssertionError("unreachable")

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self.request("POST", url, **kwargs)


BLOCK_TAGS = ["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "td", "th"]


def clean_text(text: str) -> str:
    """Normalize whitespace but keep paragraph breaks."""
    text = text.replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def html_to_text(node: Tag) -> str:
    """Flatten HTML to text: one line per block element, source line wraps and inline tags joined with spaces."""
    for tag in node.find_all(["script", "style", "head"]):
        tag.decompose()
    for comment in node.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for text_node in node.find_all(string=True):
        text_node.replace_with(re.sub(r"\s+", " ", text_node))
    for br in node.find_all("br"):
        br.replace_with("\n")
    for block in node.find_all(BLOCK_TAGS):
        block.append("\n")
    return clean_text(node.get_text(""))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def save_doc(doc: dict) -> Path:
    """Write one document to data/raw/<source>/<doc_id>.json."""
    path = RAW_DIR / doc["source"] / f"{doc['doc_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def manifest_row(doc: dict) -> dict:
    return {
        "doc_id": doc["doc_id"],
        "source": doc["source"],
        "category": doc["category"],
        "date": doc["date"],
        "title": doc["title"],
        "url": doc["url"],
        "has_en": bool(doc.get("text_en")),
        "chars": len(doc["text"]),
        "sha256": sha256(doc["text"]),
    }


def write_manifest(source: str, rows: list[dict]) -> None:
    """Replace this source's rows in the shared manifest, keeping other sources untouched."""
    existing = []
    if MANIFEST_PATH.exists():
        with MANIFEST_PATH.open(encoding="utf-8", newline="") as f:
            existing = [r for r in csv.DictReader(f) if r["source"] != source]
    all_rows = sorted(existing + rows, key=lambda r: (r["source"], str(r["doc_id"])))
    with MANIFEST_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
