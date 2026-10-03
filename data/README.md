# data

Download scripts for the corpus. Raw documents land in `data/raw/` (gitignored, never committed).
[`manifest.csv`](manifest.csv) is committed: it lists every document with its source URL and a SHA-256 of the extracted text, so the corpus can be rebuilt and checked even if a source changes.

## Corpus

| Source | What | Docs | Terms of use | Script |
| --- | --- | --- | --- | --- |
| [mevzuat.gov.tr](https://www.mevzuat.gov.tr) | All SPK and BDDK communiqués and regulations listed on the site, plus the Capital Markets Law (6362) and Banking Law (5411) | ~172 | Legislation is not protected by copyright (Law No. 5846, Art. 31) | [download_mevzuat.py](download_mevzuat.py) |
| [kap.org.tr](https://www.kap.org.tr) | Stratified sample of 2025 material event disclosures (see below) | 150 | No published terms of use found; robots.txt not reachable. Content belongs to the disclosing companies; used for non-commercial research only and not redistributed | [download_kap.py](download_kap.py) |

### KAP sample

Disclosures from 2025-01-01 to 2025-12-31, sampled with a fixed seed, at most 2 per company:

| Category | Subject on KAP | Docs | English text |
| --- | --- | --- | --- |
| material-event | Özel Durum Açıklaması (Genel) | 40 | yes |
| new-business | Yeni İş İlişkisi | 20 | yes |
| credit-rating | Kredi Derecelendirmesi | 15 | yes |
| financial-asset-acquisition | Finansal Duran Varlık Edinimi | 15 | yes |
| tender | İhale Süreci / Sonucu | 15 | yes |
| forward-looking | Geleceğe Dönük Değerlendirmeler | 10 | yes |
| dividend | Kar Payı Dağıtım İşlemlerine İlişkin Bildirim | 20 | no (structured form) |
| capital-change | Sermaye Artırımı - Azaltımı İşlemlerine İlişkin Bildirim | 15 | no (structured form) |

Free-text categories only include disclosures published in both Turkish and English, which gives a parallel TR/EN set for the tokenizer lab.

**Personal data.** Subjects that mainly list individuals (insider share trades, board committees) are excluded. Some material event disclosures still name board members. Golden set questions never ask about individuals.

**Fragility.** KAP has no documented public API. The script uses the endpoints behind the website and may break if the site changes.

## Usage

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python data/download_mevzuat.py
.venv/bin/python data/download_kap.py
```

The mevzuat script waits 1 second between requests, the KAP script 2 seconds (KAP rate-limits with HTTP 429; the script backs off and retries). Already downloaded KAP documents are reused, so an interrupted run can simply be restarted. Pass `--limit N` for a quick test run.

## Document format

`data/raw/<source>/<doc_id>.json`:

```json
{
  "doc_id": "kap-1466689",
  "source": "kap",
  "category": "material-event",
  "date": "2025-07-25",
  "title": "<company> - <subject>",
  "url": "https://www.kap.org.tr/tr/Bildirim/1466689",
  "text": "Turkish text",
  "text_en": "English text (KAP free-text categories only)"
}
```

KAP documents also carry `company`, `stock_codes` and `summary`.
