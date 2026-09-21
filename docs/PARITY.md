# Parity with the legacy workbook

Nothing replaces `FTP1.xlsm` until the platform reproduces it exactly. Two
independent workbooks are held as binding targets.

## FTP1.xlsm — 960 account-days, 5 branches, 6 dates

Run in CI on every commit (`backend/tests/parity`), against fixtures extracted
from the workbook's own `Consolidated Data`, `Branch Profit`, `Product Profit`
and `Daily Profit` sheets.

| | Platform | Workbook |
|---|---:|---:|
| Grand total | 53,215.553151 | 53,215.553151 |
| Branch 101 | 9,097.149175 | 9,097.149178 |
| Branch 102 | 11,070.749180 | 11,070.749178 |
| Branch 103 | 12,302.615072 | 12,302.615068 |
| Branch 104 | 9,133.951919 | 9,133.951918 |
| Branch 105 | 11,611.087805 | 11,611.087808 |

All 960 rows match on `ftp_rate`, `ftp_income` and the asset/liability split at
6 decimal places. The per-branch residuals of ≤4×10⁻⁶ are float accumulation in
the workbook's own unrounded sums; the platform quantises every stored value to
its column scale, so a fact row is reproducible from its own displayed figures.

## FTP1.backup-before-dummy.xlsm — 440 account-days, 3 branches

Loaded as six separate daily files, one at a time, to exercise the real
operator path including rejected rows and the merge-back.

| Date | Platform | Workbook |
|---|---:|---:|
| 2026-09-01 | 350.1564 | 350.1564 |
| 2026-09-02 | 345.7061 | 345.7061 |
| 2026-09-03 | 309.8705 | 309.8705 |
| 2026-09-04 | 359.6478 | 359.6478 |
| 2026-09-05 | 581.7104 | 581.7104 |
| 2026-09-06 | 512.2992 | 512.2992 |
| **Total** | **2,459.3904** | **2,459.3904** |

Branch 3 was deliberately left unregistered for the first pass: days 5 and 6
loaded 72 of 79 rows, the 7 branch-3 rows were exported, the branch was
registered, and the export was merged back to complete both days.

## Where the platform deliberately differs

Each is asserted as an intended difference rather than tolerated as drift.

| Behaviour | Workbook | Platform |
|---|---|---|
| Blank ROI | silently 0 | rejected (V008), or derived from interest |
| Blank benchmark | silently 0 | rejected (V006) |
| Invalid `Type` | row dropped silently | rejected (V002), counted and reported |
| Subtotal rows | skipped because column A happens to be blank | never ingested; the mapping declares the rule |
| ROI *and* interest both supplied | interest overwritten from ROI | both kept, variance computed, flagged past tolerance |

The first two matter most. `NzNumber()` coerces an empty cell to zero, so a
missing ROI silently becomes 0% — inflating liability FTP — and a missing
benchmark flips the sign of the spread. Neither raises a warning. The platform
parses a blank to `None` and never to `Decimal("0")`, which is also what keeps
`CANOR`'s legitimate 0% ROI distinguishable from an absent one.
