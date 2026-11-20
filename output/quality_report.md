# Data quality and completeness report

## Data quality

| Metric | Value |
|---|---|
| Scope | TX, practice postal codes starting 770, 771, 772, 773, 774, 775, 776, 777, 778, 779 |
| Records exported (one row per NPI) | 179,759 |
| Individuals | 125,229 (69.7%) |
| Organizations | 54,530 (30.3%) |
| With practice phone | 179,645 (99.9%) |
| With fax | 67,158 (37.4%) |
| With email endpoint | 5,231 (2.9%) |
| With both phone and email | 5,231 (2.9%) |
| With no contact information | 109 (0.1%) |
| With license number | 119,381 (66.4%) |
| Missing name | 0 |
| Failed NPI checksum | 0 |
| Duplicate NPIs in export | 0 (NPI is the primary key) |
| Distinct cities | 347 |

## Extraction run

| Metric | Value |
|---|---|
| Raw unique records in checkpoint database | 185,470 |
| Rows received from the API (before de-duplication) | 252,020 |
| Dropped as outside scope | 5,711 |
| Partitions fully fetched | 23,372 |
| Partitions split into smaller ones | 132 |
| Partitions truncated by the API cap | 0 |
| Partitions still pending | 0 |

## Top 15 cities

| City | Records |
|---|---|
| Houston | 88,460 |
| Katy | 8,003 |
| Sugar Land | 6,214 |
| Spring | 5,664 |
| Pearland | 4,233 |
| Richmond | 3,674 |
| Cypress | 3,669 |
| Beaumont | 3,489 |
| Conroe | 3,417 |
| The Woodlands | 3,334 |
| Humble | 3,212 |
| Galveston | 2,796 |
| Missouri City | 2,701 |
| Kingwood | 2,358 |
| College Station | 2,219 |
