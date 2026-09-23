# FTP Platform

Funds Transfer Pricing for a bank. Replaces the `FTP1.xlsm` workbook with a
governed, auditable, multi-user system.

The engine reproduces the workbook exactly — 960 account-day rows matching at
6 decimal places, grand total **53,215.553151**. See
[`docs/PARITY.md`](docs/PARITY.md) and [Tests](#tests).

| | |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL 16 |
| Frontend | React 18, Vite, TypeScript, ECharts |
| API | 65 operations under `/api/v1` |
| Tests | 18, `pytest`, no database required |
| Deployment | Docker; reference target is Render |

---

## Contents

- [Quick start](#quick-start) · [Signing in](#signing-in) · [What it does](#what-it-does)
- [Daily workflow](#the-daily-workflow) · [Rate configuration](#rate-configuration) · [Audit trail](#audit-trail)
- [Shape of the code](#shape-of-the-code) · [Configuration](#configuration) · [Deployment](#deployment)
- [Restore points](#restore-points) · [Tests](#tests) · [Status and limitations](#status-and-limitations)

---

## Quick start

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

`requirements-dev.txt` adds pytest, ruff, mypy and import-linter.

---

## Signing in

### Administrator

The bootstrap account is `admin`. Its password comes from `FTP_ADMIN_PASSWORD`;
when that is unset the seed falls back to `ChangeMe!2026`, which is published in
this repository and is therefore suitable for local development only. Seeding
**refuses** the fallback when `ENVIRONMENT=production`.

The account is flagged `must_change_password`. Set
`ENFORCE_PASSWORD_CHANGE=true` and it is gated in the API, not only in the UI —
gating client-side alone would leave the endpoints open to anyone holding a
token. `/auth/*` stays reachable so the change itself can be made. Minimum 12
characters.

`admin` holds `ADMIN`, `FTP_MANAGER`, `DATA_OPERATOR` and `ANALYST`: it can
upload data, maintain branches and products, maintain rate configuration,
manage users and read everything.

### Demo accounts

Created **only when `ENVIRONMENT` is not `production`**. All four share the
password `Passw0rd!2026x`. They exist to make scope enforcement visible — sign
in as each and the *same* dashboard returns a different slice, because scope is
applied server-side on every query:

| Username | Scope | Role | Sees |
|---|---|---|---|
| `operator` | Head office | `DATA_OPERATOR` | Everything; can upload but not maintain masters |
| `division_user` | One division | `ANALYST` | Districts and branches within that division |
| `district_user` | One district | `ANALYST` | Branches in that district only |
| `branch_user` | One branch | `VIEWER` | That branch only |

A branch user asking for another branch gets **403**, not an empty result — an
empty result would confirm the filter was valid and let them map the hierarchy
by watching totals move.

---

## What it does

### Ingest

Excel today; CSV, Parquet, SFTP and a push API drop in behind the same
`SourceAdapter` boundary without touching validation, calculation or audit. A
worksheet holds at most 1,048,576 rows, so past roughly 1M accounts a day Excel
is not slow — it is impossible, which is why that boundary exists.

The **business date is entered by the operator and required**. It is never taken
from the sheet name: a tab called "5 Sep 26" is a label somebody typed, and
trusting it silently books a day's figures against the wrong date. The preview
shows what the name suggests and offers it as one click; confirming it is the
point.

Eighteen validation rules run over every row. A `REJECT` blocks the row but
still stores it, so it can be downloaded, corrected and re-sent; a `WARN` loads
the row and raises an exception for review.

### Price

Rates resolve from governed configuration, not from columns typed into a
spreadsheet: a global default that each product may override per component. The
workbook's own data validates the model — liquidity (0.30) and other cost (0.05)
were identical across all five products, only the benchmark varied. 2,880
hand-typed cells collapse to one global row and five product rows.

```
LIABILITY   ftp_rate = benchmark - roi - liquidity - other
ASSET       ftp_rate = roi - benchmark - liquidity - other
both        ftp_income = balance * ftp_rate / 36500
```

`ftp_rate` is quantised to 6 dp *before* income is derived from it, so a stored
row is reproducible from its own displayed figures.

### Analyse

Twenty analytical endpoints. The two that carry the most weight:

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

### Summarise

The bottom of the Basic overview rebuilds the workbook's three summary sheets —
Branch, Product and Daily profit — from the calculated results, scoped by the
same filters as everything else.

Branch profit rolls up through **division → district → branch** and opens at
division, because eight rows fit on screen and a few hundred do not. At every
level the chart draws the top twelve and the table carries the whole list,
searchable and paginated. The tail is stated in words beneath the chart rather
than drawn as an "Other" bar: that bar is typically larger than every individual
one combined and flattens the twelve the chart exists to compare.

### Govern

Every change is audited in three independent layers: semantic records written in
the same transaction as the change, database triggers that fire however the
change arrived, and a hash chain that makes tampering detectable. `audit_log`
rejects UPDATE and DELETE outright.

---

## The daily workflow

Upload one sheet. The system parses, validates, loads what is valid, and
calculates — the dashboard is current before the operator leaves the page.

Rows referencing master data that does not exist yet do not fail the file. They
are dropped, counted, explained, and handed back as a workbook:

```
91 read → 79 accepted → 12 rejected
    Branch 10 is not registered          8 rows
    Product GOLDLOAN is not registered   6 rows
    [Download rejected rows (.xlsx)]
```

That workbook keeps the bank's original column layout, adds the reason, and
carries a "What to fix" sheet. Register the missing branch or product, upload
the same file, and it **merges** into the day rather than replacing it — the 79
rows that loaded stay put.

Re-uploading identical content is rejected on a content hash. Re-uploading a
date that already has data supersedes it, and nothing is ever deleted: the prior
version stays queryable and the dashboards read only the current one.

### Deleting a batch

An HO administrator can remove a batch entirely — for a file loaded against the
wrong date, say. It needs `UPLOAD_DELETE`, which `DATA_OPERATOR` deliberately
does **not** carry: uploading data is routine, removing published figures is not.

The confirmation is built from a dry run, so the decision is made with the row
counts and the FTP profit at stake on screen. Deleting then puts back exactly
the rows that batch displaced (tracked per row, because a merge retires only the
account-days it carries), recalculates every affected date from what remains,
and clears the aggregates for any date left empty.

A reason is required. The batch row is genuinely removed; the audit record is
not — it holds the full before-image, so what was deleted, by whom and when
outlives the deletion. A batch that has itself been superseded cannot be deleted
until the newer one is: removing a link from the middle of the chain would leave
the rows it retired with nothing to fall back to.

---

## Rate configuration

**Rate configuration** (`CONFIG_RATE_VIEW`) shows the global defaults in force,
every product's effective rates tagged with the layer that supplied each
component, and the full version history.

Two layers, resolved independently per component. `NULL` on a product component
means *inherit*; `0.00` means a deliberate zero. Conflating the two is what let
the workbook price at a zero spread when a rate was merely absent.

| Global | Product override | Result |
|---|---|---|
| `7.00` | `5.50` | 5.50, `PRODUCT_OVERRIDE` |
| `7.00` | `NULL` | 7.00, `GLOBAL_DEFAULT` |
| `NULL` | `5.50` | 5.50, `PRODUCT_OVERRIDE` |
| `NULL` | `NULL` | `ConfigMissingError` — never a zero spread |
| `7.00` | `0.00` | 0.00, `PRODUCT_OVERRIDE` — an explicit zero |

A product benchmark always wins over the global benchmark, so where the global
benchmark is `NULL` — the seeded posture — a product benchmark is mandatory.
That is enforced at configuration time, not just at calculation time: creating a
product without one is refused when the global layer supplies none, and clearing
the global benchmark is refused while any active product depends on it, naming
the products concerned.

### Changing a rate

| Action | Route | Effect |
|---|---|---|
| Change from a date | `PUT /config/global` | Closes the current version, opens the next. Published figures keep the version that priced them. |
| Correct in place | `PATCH /config/global` | Rewrites the current version. **409** once any completed calculation used it, naming the runs and rows at stake. |

Edits are applied directly by a head-office administrator; `CONFIG_RATE_EDIT`
plus HO scope, because the global layer prices every branch and a divisional
administrator must not be able to reprice branches they cannot see. There is no
separate approval step — see [Status and limitations](#status-and-limitations).

---

## Audit trail

**Activity log** (`AUDIT_VIEW`) searches every recorded change by actor
(case-insensitive substring), entity type, and date range. Opening an entry
shows the full before and after.

Every service writes its record inside the same transaction as the change, so a
committed change without its audit row is impossible rather than unlikely. The
table is append-only and hash-chained (`row_hash = SHA-256(row ‖ prev_hash)`,
computed by a trigger so a client cannot forge one). There is deliberately no
write route: an audit entry is a side effect of a change, never something a
caller can post.

---

## Shape of the code

```
backend/app/
  domain/          PURE — engine, rate resolver, 18 validation rules, scope.
                   Decimal only, no I/O. import-linter forbids it from
                   importing anything else, which is what lets the parity
                   suite run with no database.
  ingestion/       SourceAdapter protocol + Excel adapter, mapping profiles
  models/          SQLAlchemy models; 58 tables
  repositories/    dashboard and analytics queries; effective-dated rate lookup
  services/        pipeline, branches, products, config, rejects, audit
  api/v1/          auth, dashboard, analytics, org, products, config, audit,
                   uploads, system
  cli/             seed, ingest
frontend/src/
  components/      FilterBar, Chart (ECharts + tokens), waterfall, UI primitives
  views/           BasicOverview, Daily, Overview, Analytics, Leaders, Accounts,
                   Consolidated, Upload, Admin, Rates, Activity
```

Dashboards read pre-aggregated tables and never touch the fact table, so query
time stays flat as history grows. `ftp_calculation_results` is range-partitioned
by business date and append-only. Aggregates store only additive components —
weighted averages are kept as `SUM(rate × balance)` beside `SUM(balance)` and
divided at read time, because an average of averages is not the average.

---

## Configuration

Everything is an environment variable; see `backend/app/core/config.py`.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | local dev DSN | `postgres://` and `postgresql://` are rewritten to `postgresql+psycopg://`; the installed driver is psycopg 3 |
| `ENVIRONMENT` | `development` | `production` enables the guards below |
| `SECRET_KEY` | dev value | Signs session tokens; refuses to start on the dev value when `ENVIRONMENT=production` |
| `FTP_ADMIN_PASSWORD` | — | Bootstrap admin password. Required in production; removable once the account exists |
| `ENFORCE_PASSWORD_CHANGE` | `false` | Turn on for any real deployment |
| `CORS_ORIGINS` | localhost dev origins | JSON array, comma-separated list, or a single origin |
| `UPLOAD_STORAGE_DIR` | `./var/uploads` | See [limitations](#status-and-limitations) — ephemeral on a managed host |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `20` | Lower to `5` / `5` on a small managed database |

`DEBUG` is declared but never read anywhere in the codebase.

The branch hierarchy is editable data, not code:

```
backend/data/divisions.csv  districts.csv  branch_mapping.csv
```

Re-run `python -m app.cli.seed` after editing; the seed is idempotent.

---

## Deployment

The container is self-sufficient: `backend/docker-entrypoint.sh` applies
migrations, seeds reference data and starts Uvicorn on `$PORT`. Both steps are
idempotent and run on every start; set `RUN_MIGRATIONS=0` or `RUN_SEED=0` to
suppress either. A hosting platform's start-command field should be left
**empty**.

Three units are needed: one web service (Docker, root `backend`), one static
site (root `frontend`, build `npm ci && npm run build`, publish `dist`), and
PostgreSQL 16. The SPA uses hash routing, so no single-page fallback rewrite is
required.

The frontend reaches the API either way:

| Arrangement | Configuration |
|---|---|
| Same-origin | A proxy rule for `/api/*`; leave `VITE_API_BASE` unset |
| Cross-origin | `VITE_API_BASE=https://<api-host>/api/v1` plus `CORS_ORIGINS` on the API |

`VITE_API_BASE` is compiled into the bundle, so changing it needs a rebuild with
the build cache cleared, not a restart.

> **`render.yaml` is not deployable.** It declares seven services on paid plans,
> four of which cannot start: three Celery workers with no Celery application
> present, and a cron job whose entry point `app/cli/maintenance.py` does not
> exist. It records the target architecture. Create the three services above by
> hand instead.

Full procedure, including every environment variable and the first-load steps:
`../FTP Platform - Technical Document.docx`, section 10.

---

## Restore points

The database can be snapshotted and rolled back, which is what makes it safe to
load demo data over real data.

```bash
./rollback.sh --save     # snapshot the database now
./rollback.sh --list     # what is available
./rollback.sh <name>     # roll back to a specific one
```

Rolling back replaces the whole database, so it takes a safety copy of the
current state first — a rollback is itself destructive, and the state being
replaced may be the one someone wanted. It asks for the name typed back before
it proceeds.

Snapshots are `pg_dump` custom-format archives in `var/backups`, named
`restore-point-<name>.dump`. Any token works as a name, so descriptive names are
fine.

> Because a rollback writes its own safety copy to `.latest-stamp`, a subsequent
> bare `./rollback.sh` targets **that copy**, not the snapshot you last
> restored. Always name the target.

`pg_restore --clean` reports errors dropping inherited constraints on partitions;
these are benign, as the parent drop handles them. Verify a restore by row
counts, 25 partitions, all three triggers, and the audit hash-chain linkage.

On a free managed plan there is no point-in-time recovery. This mechanism is a
development convenience, not a backup strategy.

---

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q      # 18 tests, under a second
.venv/bin/ruff check app
.venv/bin/mypy app
.venv/bin/lint-imports                            # the layering contract
```

| Suite | What it holds |
|---|---|
| `tests/parity` | Reproduces `FTP1.xlsm` exactly, through the production adapter and engine. Must stay exact. |
| `tests/unit` | ROI ↔ interest inverse properties, sign convention per side, cost monotonicity, income linearity |

The two are complementary and neither subsumes the other. Measured over the
workbook's 960 rows, the external oracle contains **no** row that supplies ROI
alone, **no** row that supplies interest alone, and **no** negative spread — so
the derived-ROI path and every negative spread have no external oracle, which is
what `tests/unit` covers. Mutation testing confirms it: a wrong `interest → ROI`
divisor is caught only by the property tests, and a halved income only by parity.

The parity suite skips automatically when `FTP1.xlsm` is absent; its path is in
`tests/parity/conftest.py`.

> There is **no CI pipeline** in this repository — `.github/workflows` is empty.
> Run the suite before pushing.

---

## Status and limitations

Working and verified end to end: ingestion, validation, calculation,
aggregation, dashboards and analytics, RBAC and scope, rate configuration, the
audit trail, and deployment to a managed host. A simulated month — 96 branches,
20 products, 30 daily uploads, 1,440,433 fact rows — ingested at roughly 16s per
day, and every row was independently recomputed and matched to 6 dp.

Known gaps, all of which affect what can be promised to users:

| Gap | Position |
|---|---|
| **Asynchronous processing** | `app/tasks` is empty; Celery and Redis are not dependencies. Ingestion and calculation run synchronously in the request, so a large upload is exposed to request timeouts and a deploy kills an in-flight batch. |
| **Uploaded file retention** | `storage_uri` records an absolute path on an ephemeral filesystem. After a restart the rejects download and batch re-parse fail on a missing file. Committed data is unaffected. Object storage is designed but not built. |
| **Recalculation** | No calculation routes exist. A rate change applies only to later calculations; dates already calculated cannot be restated from the application. `CALC_RECALC_HISTORY` is unused. |
| **V015 / V016 / V017** | Prior-day checks — vanished accounts, >50% balance moves, branch row-count drift — read context that `pipeline._validation_context` never populates, so they cannot fire. |
| **Maker-checker** | `approval_requests`, `CONFIG_APPROVE` and the status/maker/checker columns exist but no route uses them. Rate changes apply directly, with version history and audit as the compensating controls. A deliberate decision. |
| **Audit scope** | `GET /audit` is gated on permission alone and applies no scope filter, so any holder sees the whole trail. |
| **Reference data** | `FTP1.xlsm` carries branch **codes** only. Division and district names in `branch_mapping.csv` are representative, and branch categories are spread across all four values to exercise category analysis. Note that the workbook's codes are `101`–`105` while the seed creates `1`–`3`, so the workbook rejects on V003 until the masters match. Replace both with the bank's real data before UAT. |

---

## Documentation

| Document | Audience |
|---|---|
| `docs/PARITY.md` | How parity with the workbook is established |
| `../FTP Platform - Technical Document.docx` | Developers, deployment and operations |
| `../FTP Platform - Functional Document.docx` | Business users, management, audit |
| `../FTP_DASHBOARD_SYSTEM_PLAN.md` | Full design, scale tiers, delivery phases |
| `../FTP_CALCULATION_LOGIC.md` | The workbook's own formulas, as found |
