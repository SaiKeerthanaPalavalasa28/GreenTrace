# GreenTrace

Automated carbon-emissions reporting from utility bills: upload electricity and gas bill PDFs,
extract usage with an LLM, calculate CO2e in deterministic Python from versioned official emission
factors, review uncertain data, and produce an inspector-ready PDF report.

Design rules: **the LLM extracts, code calculates**; every number traces back to its bill and factor;
low-confidence data is human-approved; emission factors are versioned data, never code.

## Status

All seven milestones are built. 285 backend tests pass (`app/calc` and `app/reports` at 99%
coverage). **Read "Before production" at the end**: some parts have not yet been run
against real infrastructure.

## Layout

```
backend/    FastAPI app (app/), Alembic migrations, seed/emission_factors.yaml, tests/, Dockerfile
frontend/   React (JavaScript) + Vite + Tailwind + Recharts, Dockerfile + nginx.conf
samples/    10 synthetic bills, manifest.json (ground truth + hand-worked emissions), generator
docker-compose.yml   Postgres + API + frontend
```

## Quick start with Docker

```bash
cp backend/.env.example backend/.env   # set JWT_SECRET and GEMINI_API_KEY
docker compose up --build              # http://localhost:8080
```

The API container migrates the database and loads the emission factors on every start
(idempotent). Tesseract is included in the image. Uploaded files and generated reports are kept
in the `storage` volume, and the database in `pgdata`.

## Local setup (Windows, native)

Prerequisites: Python 3.11+, Node 20+, and for scanned bills
[Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) (on PATH, or set `TESSERACT_CMD`).
Poppler is not needed: pages are rendered for OCR with pypdfium2.

```powershell
# Backend
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
copy .env.example .env          # then set JWT_SECRET (and DATABASE_URL for Supabase)
.venv\Scripts\alembic upgrade head
.venv\Scripts\python -m app.seed
.venv\Scripts\python -m uvicorn app.main:app --port 8000   # restart after code changes

# Frontend (second terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173, proxies /api to :8000
```

Without `DATABASE_URL` the backend uses a local SQLite file (`backend/greentrace.db`), which is
fine for trying things out. For Supabase, use the **Session pooler** connection string from
Project Settings → Database; `postgresql://` URLs are converted to the psycopg driver automatically.

API docs: http://localhost:8000/docs

> The repo lives in OneDrive. Exclude `backend/.venv` and `frontend/node_modules` from sync
> (or move the repo outside OneDrive) to avoid slow installs and file-lock errors.

## Extraction pipeline

```
upload ─► SHA-256 duplicate check ─► bill row (uploaded) ─► worker pool
  ─► pdfplumber text per page ─► OCR pages with no text layer
  ─► Gemini, JSON-schema-constrained (retry once if invalid) ─► Pydantic validation
  ─► code validation rules ─► approved (all rules pass) or needs_review
any error ─► failed + readable reason (reprocessable); other bills are unaffected
```

The LLM copies values only. Code then checks every extraction; any failed rule sends the bill
to review:

- **Confidence and model flags:** confidence below 0.85, estimated reads, several meters, or notes from the model.
- **Unit:** must be in the allowed list and match the utility.
- **Billing period:** start and end present, end after start, at most 95 days (inclusive), not in the future.
- **Quantity:** greater than zero. When derived from meter readings, the result must be consistent and a printed multiplier is required.
- **Source snippet:** must appear on the cited page, and the quantity must appear in it. This guards against made-up values.
- **Account number:** if it was never seen before, or belongs to another facility, the bill goes to review.
- **Duplicates:** a billing period that overlaps another bill for the same facility is flagged.
- **Outliers:** daily usage more than 3x, or less than a third of, the facility's median.

So the first bill for each account always goes to review. Once the account has been confirmed,
later clean bills are auto-approved, and the audit log records that as `system`.

Try the pipeline on files without the database:

```powershell
cd backend
.venv\Scripts\python -m app.pipeline.cli --text-only path\to\bill.pdf   # text layer / OCR only
.venv\Scripts\python -m app.pipeline.cli path\to\bill1.pdf path\to\bill2.pdf   # + Gemini + validation
```

Bills interrupted by a server restart are re-queued at startup.

## Review

Bills that fail any rule wait in the review queue (`/review`), oldest first, with a count in the
nav bar. The review screen shows the bill page on the left, with the source snippet boxed when
the PDF has a text layer. On the right is an editable form; each field is outlined in red,
amber or blue, depending on the issue it has.

- **Blocking issues** must be fixed before approving: unknown utility, missing or invalid unit,
  missing or reversed billing period, no usable quantity, or a meter rollover. These make a bill
  impossible to calculate.
- **Warnings** (low confidence, new account, possible duplicate, outlier, and so on) are
  acknowledged by approving. The audit log records which warnings were acknowledged.
- **Corrections** edit the current extraction. `corrections_json` keeps the value the model
  originally read (`before`) and the reviewer's value (`after`). Every change is audited with the
  reviewer, the time and an optional reason. After a correction, the field rules run again.
- **Approve** applies any corrections and approves in one transaction. It also saves the
  account number → facility link. If the account already belongs to another facility, the
  reviewer either moves the bill to that facility or confirms that the account has moved. The
  bill is then calculated.
- **Reject** requires a reason; the bill is excluded from reporting.
- **Reopen** (admin only) sends an approved or rejected bill back to review. Its emissions are
  removed from totals until it is approved again, and earlier records are kept as history.
- **Concurrent edits:** if two reviewers edit the same bill, the second gets a "reload" error
  instead of overwriting the first (each request checks the bill's `updated_at`).

## Dashboard

`/dashboard` (the home page). A single row of filters (reporting period, facility, utility)
applies to every number on the page.

- **What's counted:** totals include only current emission records of approved bills inside
  the period. A banner states how many bills that may belong to the period are left out (in
  review, processing, failed, or approved but not calculated), so a partial total is never
  mistaken for a final one.
- **Reporting periods:** whole months, following the org's fiscal year (FY2023-24 for April
  starts), or a custom range of months. Each emission record covers one month, so a period
  boundary never splits a record. The period can be linked to with `?period=FY2023-24`.
- **Exact sums:** sums are done in exact kg, then converted to tonnes and rounded to 3 decimal
  places on the server. If the rounded Scope 1 + Scope 2 differs from the rounded total, the
  page says so.
- **Layout:**
  - Headline total, then Scope 1 / Scope 2 stat tiles with a thin 100% split bar (a two-slice
    donut is avoided on purpose).
  - Monthly stacked bars by scope, with a table view.
  - Facility donut: top 3 plus a gray "Other", next to a full list of facilities with values.
  - Bills table; clicking a row opens the bill's calculation trace in a side panel.
- **Colors:** the first slots of a validated colorblind-safe palette, in fixed order. Scope 1
  is always blue and Scope 2 always orange.
- **CO2-only factors:** the dashboard notes when part of the total comes from grid factors that
  cover CO2 only (CEA).

## Reports

`/reports` generates an inspector-ready PDF for any whole-month period.

1. **Snapshot** (`app/reports/snapshot.py`): every fact the report shows is frozen as JSON. That
   covers each emission record with its bill, file hash, allocation, factor and formula, plus
   reviewers and corrections, every factor used with its source and derivation, the bills left
   out, the organization and period, and the engine version. Numbers are decimal strings.
2. **PDF** (`app/reports/pdf.py`, ReportLab, plus matplotlib charts) is rendered **from the
   snapshot only**. Its sections:
   - cover (organization, period, framework, generated time, report ID, status)
   - executive summary (Scope 1 / Scope 2 / total; CO2-only factor note; rounding note)
   - breakdown by month and by facility, as charts and tables
   - methodology: GHG Protocol boundary, Scope 1 / location-based Scope 2, the extraction and
     review process, the formula, pro-rating, unit conversions, rounding, a table of every
     emission factor used with its source URL and version, and limitations
   - Appendix A: every bill and its monthly allocations, with quantity, factor and kgCO2e
   - Appendix B: every manual correction (value read → corrected value, reviewer, time)
   - Appendix C: bills left out, with the reason
3. **Draft vs complete:** if any bill that may belong to the period is left out (in review,
   processing, failed, or not calculated), the report is a **DRAFT**. Every page is
   watermarked, the cover says so, and the filename ends in `-DRAFT`.
4. **Integrity:** the SHA-256 of the canonical snapshot and of the PDF are stored. Rendering is
   deterministic (ReportLab invariant mode, fixed chart metadata and fonts). `POST
   /api/reports/{id}/verify` re-checks both hashes and re-renders the PDF from the stored
   snapshot to confirm it is byte-identical. This keeps working after the live data changes
   (bills corrected, factors versioned).
   Byte-identical re-rendering assumes the same ReportLab and matplotlib versions;
   `requirements.txt` pins them.

## Calculation

`app/calc/` is plain, deterministic Python with `Decimal` throughout (floats are rejected):

```
kg CO2e = quantity × (segment days / billing-period days) × unit conversion × factor
```

- **Quantity:** the printed total, or `(current − previous) × multiplier` from the meter readings.
- **Pro-rating:** billing periods include both the start and end date. They are split at every
  calendar-month boundary and wherever an emission factor's validity changes. Each segment gets
  its share of the quantity by day count, assuming steady consumption. So a 16 Mar – 15 Apr bill
  in India uses the FY2023-24 factor for 16/31 of it and the FY2024-25 factor for the remaining
  15/31. Each segment becomes its own `emission_record`, which keeps monthly and yearly totals exact.
- **Unit normalization:** exact constants (e.g. 1 therm = 100,000 Btu(IT)). Units are converted
  only within the same kind of measure. A gas bill in m³ with only energy-based factors fails
  with an explanation; it is never guessed.
- **Factor selection** (`factors.py`):
  - The factor must match the utility and the facility's region, and be valid on the date.
  - The parent region (`US-CAMX` → `US`) is used only when the subregion has no factors for
    that utility at all. In practice that means natural gas, which is published nationally.
  - Organization-specific factors take precedence over global ones.
  - If two factors still apply equally, or none does, the calculation fails. There is no
    default factor.
- **Scopes:** electricity is Scope 2 (location-based); natural gas is Scope 1.
- **Rounding:** each record is rounded once to 6 decimal places of kg (half-even). Tonnes shown
  in the UI are rounded on the server to 3 decimal places.

Every record stores a JSON trace: the bill (file, SHA-256, page, snippet), the extraction and
who approved it, the allocation, the conversion, the factor (key, version, value, source URL,
derivation) and the formula as text. `GET /api/bills/{id}/trace` returns it.

**When results are recalculated:**
- a bill is auto-approved;
- a factor is added or versioned (API or seed loader);
- an admin runs `POST /api/bills/recalculate`.

Recalculation is idempotent: if a bill's result is unchanged, nothing is written. Otherwise the
old records are kept with `is_current = false` and the change is audited. An approved bill that
can't be calculated keeps a `calculation_error` and counts towards nothing until it is fixed.

## Sample bills

`samples/bills/` holds 10 synthetic bills from **fictional** suppliers:

| Bill | Exercises |
|---|---|
| `in-pune-electricity-2024-01` | baseline Indian electricity (CEA) |
| `in-pune-electricity-2024-03-cross-fy` | 16 Mar–15 Apr: split across the 1 April financial-year boundary and two CEA factors |
| `in-chennai-electricity-2024-02-meter-readings` | no total printed: (current − previous) × MF 20 |
| `in-chennai-gas-2024-02-mmbtu` | Indian natural gas in MMBTU → TJ (IPCC factor) |
| `in-pune-electricity-2024-02-scanned` | image-only scan (needs OCR) |
| `in-chennai-electricity-2023-12-two-pages` | consumption on page 2 |
| `uk-london-electricity-2025-12-cross-year` | Dec 2025–Jan 2026: DESNZ 2025 and 2026 factors |
| `uk-london-gas-2025-03` | UK gas in kWh (gross CV) |
| `us-sf-electricity-2024-06` | eGRID subregion (CAMX), lb → kg |
| `us-sf-gas-2024-11-therms` | therms → MMBtu; national factor via parent region |

`samples/manifest.json` gives, for each bill, the values printed on it and the expected kgCO2e,
**worked out by hand** (`expected_working`), independently of the engine. Regenerate the bills
with `backend/.venv/Scripts/python samples/generate_bills.py`.

## Tests

```powershell
cd backend
.venv\Scripts\python -m pytest              # 285 tests, SQLite in memory, no network
.venv\Scripts\python -m pytest -m live -v   # opt-in: real Gemini on the sample bills
```

- **Unit tests:** units, factor selection, pro-rating and the engine (expected values worked by
  hand in the test comments, plus property tests over random billing periods), validation rules,
  text extraction and OCR fallback, and the LLM contract (retries, rate limits, error mapping).
- **API tests:** auth and org isolation, upload, review, dashboard, reports, and storage (local
  and S3 via moto).
- **`test_integration_samples.py`:** uploads every sample bill per organization (IN, UK, US),
  then reviews, approves and calculates them, and checks the dashboard and report. Every bill's
  kgCO2e must equal the manifest exactly. The LLM is replaced by a "perfect reader" that returns
  the printed values; everything else is real.
- **`test_live_extraction.py`** (`-m live`): sends each text sample to the real Gemini model and
  compares every field with the bill, including that it does **not** compute a total when only
  meter readings are printed. Set `GEMINI_REQUESTS_PER_MINUTE` on free-tier keys.
- **`test_migrations.py`:** fails if a model changes without a matching Alembic migration.

## Emission factors

`backend/seed/emission_factors.yaml` holds every factor as printed by its publisher, with source URL,
edition and validity window. The loader derives kg CO2e per unit (mass-unit conversion, and GWP
weighting when gases are listed separately) and stores the derivation with the row.
`python -m app.seed --check` validates the file without a database.

| Region | Utility | Source | Coverage |
|---|---|---|---|
| IN | electricity | CEA CO2 Baseline Database v20 / v21 (weighted average incl. RE; **CO2 only**) | FY2022-23 to FY2024-25 |
| IN | natural gas | IPCC 2006 Guidelines, Vol. 2 Ch. 2, Table 2.3 | open-ended |
| UK | electricity, natural gas (kWh, m3) | DESNZ GHG conversion factors 2025, 2026 | calendar 2025, 2026 |
| US, US-<eGRID subregion> | electricity | EPA eGRID2023 summary tables rev. 2 (CO2e total output rate) | 2023-2024 |
| US | natural gas (MMBtu, scf) | EPA GHG Emission Factors Hub, Jan 2025 | 2024 onward |

**Before reporting, verify each value against the latest edition** (every row carries a TODO).
In particular, the CEA v21 value (FY2024-25, 0.710 tCO2/MWh) could not be read from the source
PDF at seeding time because cea.nic.in required a login; it is flagged UNVERIFIED in the seed file.

A bill whose dates fall outside every factor's validity window fails with a clear error instead of
silently using another year's factor. To cover a new period, add the newly published factor to the
seed file (new `key`), or create an org-specific factor in the admin page. To correct a value,
add the same `key` with `version` incremented; old versions are kept and marked superseded.

## API

| Method | Path | |
|---|---|---|
| POST | `/api/auth/register` | create organization + admin user |
| POST | `/api/auth/login` | JWT |
| GET | `/api/auth/me` | |
| GET/POST | `/api/users` | admin: list / add members |
| GET/POST | `/api/facilities` · PATCH `/api/facilities/{id}` | region must have factors |
| GET | `/api/factors` · `/api/factors/{id}` · `/api/factors/{id}/history` · `/api/factors/regions` · `/api/factors/gwp-sets` | |
| POST | `/api/factors` · `/api/factors/{id}/versions` | admin, org-specific factors |
| POST | `/api/bills/upload` | multipart: `facility_id`, `files` (PDF, ≤20 MB each); per-file outcome |
| GET | `/api/bills` · `/api/bills/{id}` · `/api/bills/{id}/file` | list (filters `status`, `facility_id`), detail with current extraction, PDF |
| GET | `/api/bills/status?ids=…` | lightweight polling |
| GET | `/api/bills/{id}/trace` | bill → extraction → factor → formula → result, plus earlier calculations |
| POST | `/api/bills/recalculate` | admin; recalculate all approved bills |
| GET | `/api/bills/{id}/pages/{n}` | PNG of a page, source snippet highlighted (`X-Highlight`, `X-Page-Count` headers) |
| GET | `/api/review` · `/api/review/counts` | queue (oldest first) · counts for needs_review / failed / calculation errors |
| POST | `/api/extractions/{id}/correct` · `/approve` · `/reject` | `changes` as strings, `expected_updated_at` for concurrency |
| POST | `/api/bills/{id}/reopen` | admin; back to review with a reason |
| POST | `/api/bills/{id}/reprocess` | failed / needs_review bills |
| GET | `/api/dashboard/periods` | reporting years (org fiscal year), newest first, with a default |
| GET | `/api/dashboard?period_start&period_end&facility_id&utility_type` | totals, scope split, monthly, by facility, completeness |
| POST | `/api/reports` | `{period_start, period_end, label?}`: snapshot + PDF |
| GET | `/api/reports` · `/api/reports/{id}` · `/download` · `/snapshot` | list, detail with summary, PDF, canonical JSON |
| POST | `/api/reports/{id}/verify` | hash checks + byte-identical re-render |
| GET | `/api/audit` | admin |

All data is scoped to the caller's organization; another org's ids return 404.

## Production notes

- **Database:** set `DATABASE_URL` to the Supabase **Session pooler** connection string and run
  `alembic upgrade head` and `python -m app.seed`. The Docker image does this on start.
- **File storage:** set `STORAGE_BACKEND=s3` with `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`
  and the S3 access keys (Supabase Storage → S3 connection). Keep the bucket **private**: files
  are only served through the API, which checks the organization on every request.
- **Secrets** come from environment variables only (`JWT_SECRET`, `GEMINI_API_KEY`, S3 keys).
  `.env` is git- and docker-ignored.
- **Gemini quota:** set `GEMINI_REQUESTS_PER_MINUTE` below your plan's limit. On a 429 the
  client waits as long as the API asks (up to 60 s, five attempts). A bill that still fails
  shows the reason and can be reprocessed.
- **Background jobs** run in a thread pool inside the API process, which suits one API
  instance. Bills left unfinished by a restart are re-queued at startup. To run several API
  instances, move processing to a shared queue (RQ/Celery + Redis): `JobQueue.enqueue` is the
  only seam.

## Before production

These have **not** been verified in the environment this was built in:

1. **Live LLM extraction accuracy is only partly verified.** In the first live run with
   `gemini-3.8-flash`, the cross-financial-year bill and the two-page bill matched the printed
   values field for field. On the meter-readings-only bill, the model correctly left the total
   empty rather than calculating it. The other bills could not run: Google returned 503s, and the
   **free tier allows only 20 requests per day** for this model. Re-run `pytest -m live` on a
   paid key (or on another day) and try real bills before relying on the pipeline. A free-tier
   key cannot handle real batch uploads.
2. **Postgres and Docker.** All tests run on SQLite. Models use portable types (JSON→JSONB,
   UUID, Numeric) and the migrations are standard Alembic, but run the stack once with
   `docker compose up` (or against Supabase) and repeat the integration tests before go-live.
3. **OCR.** The scanned-bill path is tested with Tesseract mocked. Tesseract was not
   installed locally; it is in the Docker image.
4. **Emission factors.** Every seeded value carries `TODO: verify against latest published
   edition`. In particular:
   - **CEA v21 is unverified.** The FY2024-25 value (0.710) could not be read from the source
     PDF.
   - **Coverage gaps.** Bills fail with "no factor covers this date" for Indian electricity after
     March 2025, US electricity after 2024, and UK outside 2025–2026, until newer editions are
     added.
   - **India gas basis.** The IPCC default is per TJ on a **net** calorific value basis, while
     Indian gas bills in MMBTU/SCM are usually on a **gross** basis, so results may be roughly
     10% high. Add a gross-basis factor (or a supplier-specific org factor) before reporting
     Indian gas.
5. **Security hardening still to do:** login rate limiting / lockout, password reset, MFA, and
   segregation of duties (today the uploader may also approve).
6. **Out of scope:** market-based Scope 2, Scope 3 (including T&D losses and well-to-tank), and
   fuels other than grid electricity and natural gas.
