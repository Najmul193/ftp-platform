# FTP Platform

Funds Transfer Pricing for a bank. Replaces the `FTP1.xlsm` workbook with a
governed, auditable, multi-user system.

The engine reproduces the workbook exactly — 960 account-day rows matching at
6 decimal places, grand total **53,215.553151** — and that parity runs in CI on
every commit. See [`docs/PARITY.md`](docs/PARITY.md).

---

## Running it

```bash
./start.sh --seed      # database, API and web UI from local source
./start.sh --docker    # the whole stack in containers instead
./stop.sh              # stop; --all also stops PostgreSQL, --purge deletes its data
```

| | |
|---|---|
| Dashboard | http://127.0.0.1:5173 |
| API docs | http://127.0.0.1:8099/docs |

First run needs the toolchain in place:

```bash
cd backend  && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd frontend && npm install
```

---

## Sign in

### Administrator

```
username:  admin
password:  ChangeMe!2026
```

Change it. A seeded password is a shared secret until it is replaced.

Enforcement is available but **off by default**, so it stays out of the way
during development. Set `ENFORCE_PASSWORD_CHANGE=true` and an account still on
its initial password is gated — in the API, not only in the UI, since gating
client-side alone would leave the endpoints open to anyone holding a token.
`/auth/*` stays reachable so the change itself can be made. Minimum 12
characters.

`admin` holds `ADMIN`, `FTP_MANAGER`, `DATA_OPERATOR` and `ANALYST`: it can
upload data, maintain branches and products, manage users and read everything.

### Demo accounts

All four share the password `Passw0rd!2026x`. They exist to make scope
enforcement visible — sign in as each and the *same* dashboard returns a
different slice, because scope is applied server-side on every query:

| Username | Scope | Role | Sees (with the sample data loaded) |
|---|---|---|---|
| `operator` | Head Office | `DATA_OPERATOR` | Everything; can upload but not maintain masters |
| `division_user` | Northern Division | `ANALYST` | 3 branches, 440 account-days |
| `district_user` | Jaipur district | `ANALYST` | 2 branches, 426 account-days |
| `branch_user` | Branch 1 | `VIEWER` | 1 branch, 188 account-days |

A branch user asking for another branch gets **403**, not an empty result — an
empty result would confirm the filter was valid and let them map the hierarchy
by watching totals move.

These four are created by the seed **only when `ENVIRONMENT` is not
`production`**. Change every password before any real deployment; none of these
belong in a live system.

---

## What it does

**Ingest.** Excel today; CSV, Parquet, SFTP and a push API drop in behind the
same `SourceAdapter` boundary without touching validation, calculation or
audit. A worksheet holds at most 1,048,576 rows, so past roughly 1M accounts a
day Excel is not slow — it is impossible, which is why that boundary exists.

The **business date is entered by the operator and required**. It is never
taken from the sheet name: a tab called "5 Sep 26" is a label somebody typed,
and trusting it silently books a day's figures against the wrong date with
nothing to catch the mistake. The preview shows what the name suggests and
offers it as one click; confirming it is the point.

**Price.** Rates resolve from governed configuration, not from columns typed
into the spreadsheet: a global default that each product may override per
component. The workbook's own data validates the model — liquidity (0.30) and
other cost (0.05) were identical across all five products, only the benchmark
varied. 2,880 hand-typed cells collapse to one global row and five product rows.

**Analyse.** Twenty analytical endpoints. The two that carry the most weight:

- **NII reconciliation** — of the margin earned from customers, how much belongs
  to the units that wrote the business and how much to the book that funded it.
  This is what FTP is *for*.
- **Variance bridge** — profit moved; was it balances or was it pricing? Volume,
  rate and interaction effects that sum to the change with a zero residual.

Plus spread waterfall, concentration (HHI and Pareto), rankings on yield rather
than size, balance-weighted rate distribution, within-product outliers, profit
leakage, quadranted scatter, leaderboards per division/district/category, which
product leads in which area, and the banker's daily set — yield on advances,
cost of deposits, NIM, CASA, credit-deposit ratio, MTD/QTD/YTD, a watchlist
ordered by money at stake, and a quantified repricing opportunity.

**Govern.** Every change is audited in three independent layers: semantic
records written in the same transaction as the change, database triggers that
fire however the change arrived, and a hash chain that makes tampering
detectable. `audit_log` rejects UPDATE and DELETE outright.

---

## The daily workflow

Upload one sheet. The system parses, validates, loads what is valid, and
calculates — the dashboard is current before the operator leaves the page.

Rows referencing master data that does not exist yet do not fail the file. They
are dropped, counted, explained, and handed back as a workbook:

```
91 read → 79 accepted → 12 rejected
    Branch 10 is not registered      8 rows
    Product GOLDLOAN is not registered   6 rows
    [Download rejected rows (.xlsx)]
```

That workbook keeps the bank's original column layout, adds the reason, and
carries a "What to fix" sheet. Register the missing branch or product, upload
the same file, and it **merges** into the day rather than replacing it — the 79
rows that loaded stay put.

Re-uploading identical content is rejected on a content hash. Re-uploading a
date that already has data supersedes it, and nothing is ever deleted: the
prior version stays queryable and the dashboards read only the current one.

### Deleting a batch

An HO administrator can remove a batch entirely — for a file loaded against
the wrong date, say. It needs `UPLOAD_DELETE`, which `DATA_OPERATOR`
deliberately does **not** carry: uploading data is routine, removing published
figures is not.

The confirmation is built from a dry run, so the decision is made with the
row counts and the FTP profit at stake on screen. Deleting then puts back
exactly the rows that batch displaced (tracked per row, because a merge
retires only the account-days it carries), recalculates every affected date
from what remains, and clears the aggregates for any date left empty.

A reason is required. The batch row is genuinely removed; the audit record is
not — it holds the full before-image, so what was deleted, by whom and when
outlives the deletion. A batch that has itself been superseded cannot be
deleted until the newer one is: removing a link from the middle of the chain
would leave the rows it retired with nothing to fall back to.

---

## Shape of the code

```
backend/app/
  domain/          PURE — engine, rate resolver, 19 validation rules, scope.
                   Decimal only, no I/O. import-linter forbids it from
                   importing anything else, which is what lets the parity
                   suite run with no database.
  ingestion/       SourceAdapter protocol + Excel adapter, mapping profiles
  repositories/    dashboard and analytics queries; effective-dated rate lookup
  services/        pipeline, branches, products, rejects, audit
  api/v1/          auth, dashboard, analytics, org, products, uploads, system
frontend/src/
  components/      Chart (ECharts + tokens), waterfall builder, UI primitives
  views/           Daily, Overview, Analytics, Leaders, Accounts, Upload, Admin
```

Dashboards read pre-aggregated tables and never touch the fact table, so query
time stays flat as history grows. The fact table is partitioned by business
date and append-only. Aggregates store only additive components — weighted
averages are kept as `SUM(rate × balance)` beside `SUM(balance)` and divided at
read time, because an average of averages is not the average.

---

## Configuration

Credentials live in `backend/app/cli/seed.py` (`ADMIN_PASSWORD`,
`DEMO_PASSWORD`). Turn on `ENFORCE_PASSWORD_CHANGE` before any real
deployment. Branch hierarchy is an editable CSV, not code:

```
backend/data/branch_mapping.csv
```

Everything else is environment variables; see `backend/app/core/config.py`.
`SECRET_KEY` refuses to start with its development value when
`ENVIRONMENT=production`.

---

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q
```

| Suite | What it holds |
|---|---|
| `parity` | Reproduces `FTP1.xlsm` exactly. Must stay exact. |
| `unit` | Engine, resolver, validators, scope |

---

## Known placeholders

`FTP1.xlsm` carries branch **codes** and nothing else — no names, no hierarchy,
no categories. Division and district names in `branch_mapping.csv` are invented,
and branch categories are spread across all four values so the category analysis
is exercised. Replace both with the bank's real data before UAT; this is open
item Q1/Q2 in the plan.

Full design, scale tiers and delivery phases: `../FTP_DASHBOARD_SYSTEM_PLAN.md`.
