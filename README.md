# Large-scale registry extraction: 179,759 provider records to Excel

A resumable Python extractor for the NPPES NPI Registry, the public US government directory of
healthcare providers, using its official API. This is a personal demonstration project.

Scope of the demo run: every provider with a practice address in Texas postal codes starting
770–779 (the Houston area).

## Result

| Metric | Value |
|---|---|
| Records exported (one row per registration number) | 179,759 |
| Individuals / organizations | 125,229 / 54,530 |
| With practice phone | 179,645 (99.9%) |
| With fax | 67,158 (37.4%) |
| With email endpoint | 5,231 (2.9%) |
| With no contact information | 109 (0.1%) |
| Duplicate registration numbers | 0 |
| Failed registration-number checksum | 0 |
| Areas left incomplete | 0 |
| Requests made / errors | 22,495 / 0 |
| Run time | about 73 minutes at 5–6 requests per second |

The full report is in `output/quality_report.md` and on the Summary sheet of the workbook.

## How it works

- **Partitioning.** The API returns at most 1,200 records per query. The scope is split by
  postal-code prefix, then full postal code, then provider type, then name prefix, until every
  slice fits. 132 slices were split this way and none was left truncated.
- **Checkpointing.** Each finished slice is recorded in SQLite. The run was stopped and resumed
  once during this demo and continued from where it left off.
- **Rate limiting and retries.** A global limiter caps requests per second; failed requests
  retry with exponential backoff.
- **De-duplication.** The registration number is the primary key. 252,020 rows were received
  and 185,470 were unique.
- **Scope check.** 5,711 records the API returned for these postal codes had their main
  practice address elsewhere and were excluded.
- **Cleaning and validation.** Phones normalised to one format, postal codes split into ZIP
  and ZIP+4, whitespace collapsed, and every registration number checked against its check digit.
  Missing fields are left blank; nothing is guessed.

## Run it

```bash
python scraper.py --zip-prefixes 770 771 772 773 774 775 776 777 778 779
```

```bash
python export.py --zip-prefixes 770 771 772 773 774 775 776 777 778 779
```

```bash
python export.py --zip-prefixes 770 771 772 773 774 775 776 777 778 779 --sample 1000 --xlsx output/pilot_1000_records.xlsx --report ""
```

Requires Python 3.10+, `requests` and `openpyxl`.

## Output

- `output/npi_registry_houston_area.xlsx`: the full database, 39 columns, plus a Summary sheet
- `output/pilot_1000_records.xlsx`: a 1,000-record sample in the same format
- `output/quality_report.md`: data quality and completeness report
