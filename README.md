# GreenTrace

GreenTrace turns **utility bills (PDFs)** into an **auditable carbon-emissions report**.

You upload electricity and natural-gas bills. The app reads each bill, pulls out how much energy
was used and for which dates, checks the result, lets a person confirm anything doubtful,
multiplies the usage by an official emission factor, and finally produces a PDF report that an
inspector or auditor can verify number by number.

The one rule that shapes everything: **the AI reads, the code calculates.**

- The language model only *copies* values off the bill (usage, unit, dates, account number). It is
  forbidden to add, convert, round or guess.
- Every number you see in a total is calculated by plain, deterministic Python from those copied
  values and a **versioned, sourced emission factor**.
- Anything the AI is unsure about, or that fails a check, goes to a **human review queue** instead
  of silently entering the totals.
- Every figure can be traced back to: the bill file → the page and exact text it was read from →
  who approved it → the emission factor and its source → the formula.

> **Technical deep dive with architecture diagrams** (components, sequence diagrams, state machine,
> database ER diagram, calculation flow, deployment): see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Contents

1. [What the project does, in plain words](#1-what-the-project-does-in-plain-words)
2. [Key words you will see](#2-key-words-you-will-see)
3. [The big picture (architecture)](#3-the-big-picture-architecture)
4. [The life of one bill, step by step](#4-the-life-of-one-bill-step-by-step)
5. [The AI / LangChain part](#5-the-ai--langchain-part)
6. [Validation: the checks that decide "auto-approve or review"](#6-validation-the-checks-that-decide-auto-approve-or-review)
7. [Human review](#7-human-review)
8. [The calculation, explained with a worked example](#8-the-calculation-explained-with-a-worked-example)
9. [Emission factors](#9-emission-factors)
10. [Dashboard](#10-dashboard)
11. [Reports (the PDF)](#11-reports-the-pdf)
12. [Users, organizations, security](#12-users-organizations-security)
13. [Data model (database tables)](#13-data-model-database-tables)
14. [The website, page by page](#14-the-website-page-by-page)
15. [Folder-by-folder, file-by-file guide](#15-folder-by-folder-file-by-file-guide)
16. [Configuration (no `.env`, no API keys)](#16-configuration-no-env-one-api-key)
17. [Run it on your computer](#17-run-it-on-your-computer)
18. [The `samples/` folder: what it is and what to do with it](#18-the-samples-folder-what-it-is-and-what-to-do-with-it)
19. [Tests](#19-tests)
20. [Deploy: Vercel (frontend) + Render (backend)](#20-deploy-vercel-frontend--render-backend)
21. [API reference](#21-api-reference)
22. [Troubleshooting](#22-troubleshooting)
23. [Known limits and what to verify before real reporting](#23-known-limits-and-what-to-verify-before-real-reporting)

---

## 1. What the project does, in plain words

Companies must report their greenhouse-gas emissions. For energy use, the raw evidence is the
monthly electricity and gas bills. Doing this by hand means typing numbers from dozens of PDFs
into a spreadsheet and looking up conversion factors, which is slow and error-prone.

GreenTrace automates it while keeping a paper trail:

1. **Upload** bill PDFs for a facility (a plant, an office...).
2. **Extract** the usage with an AI model (and OCR for scanned bills).
3. **Check** the extraction with code (dates sane? unit allowed? number really on the page?...).
4. **Review**: clean bills are approved automatically; doubtful ones wait for a person.
5. **Calculate** CO2-equivalent (CO2e) emissions with the right official factor for the bill's
   country/region and dates.
6. **Dashboard**: totals by scope, month and facility.
7. **Report**: a PDF with methodology, appendices and tamper-evidence hashes.

Supported: **grid electricity** (reported as Scope 2) and **natural gas** (Scope 1), with factors
seeded for **India (CEA, IPCC), UK (DESNZ), US (EPA eGRID and GHG Hub)**.

---

## 2. Key words you will see

| Term | Meaning |
|---|---|
| **Bill** | One uploaded PDF. It has a status (see below). |
| **Extraction** | What was read from a bill: provider, account number, billing period, quantity, unit, meter readings, confidence, the source snippet... A bill can have several extractions over time (e.g. after "reprocess"); only one is *current*. |
| **Facility** | A place that consumes energy (e.g. "Pune Plant"). Has a **region** code (`IN`, `UK`, `US`, `US-CAMX`) that decides which emission factors apply. |
| **Organization** | A company account. All data is private to its organization. |
| **Scope 1 / Scope 2** | GHG Protocol categories. Gas burned on site = Scope 1. Purchased electricity = Scope 2 (location-based in this app). |
| **kgCO2e / tCO2e** | Kilograms / tonnes of CO2-equivalent. The app stores kg exactly and shows tonnes (kg / 1000). |
| **Emission factor** | "kg of CO2e released per unit of energy", e.g. 0.727 tCO2 per MWh of Indian grid electricity. Published by governments, stored as versioned data. |
| **Billing period** | The dates the consumption covers (not the bill date). Both the first and last day count (1-30 April = 30 days). |
| **Pro-rating** | Splitting a bill that spans months/years/factor-changes into pieces by day count. |
| **Fiscal year** | Reporting year. India uses April to March ("FY2024-25"); others use the calendar year. Set per organization. |
| **Confidence** | The AI's own 0-1 estimate that quantity, unit and period are right. |
| **Source snippet** | The exact line of text from the bill that the AI says it copied the quantity from. Used to prove the number is really on the page. |
| **Audit log** | An append-only history of who/what did what (upload, approve, correct, calculate...). |

**Bill statuses**

| Status | Meaning |
|---|---|
| `uploaded` | Saved, waiting for a worker. |
| `processing` | A worker is reading it right now. |
| `needs_review` | Extracted, but a check failed. Waiting for a person. |
| `approved` | Counted in totals (by a person, or automatically with the audit log saying `system`). |
| `rejected` | A reviewer excluded it (not a bill, duplicate, wrong company...). Not counted. |
| `failed` | Something broke (unreadable PDF, LLM unreachable, OCR missing...). A readable reason is stored; you can **reprocess**. |

---

## 3. The big picture (architecture)

```
 Browser (React app, hosted on Vercel)
        │   HTTPS, JSON, Authorization: Bearer <JWT>
        ▼
 FastAPI backend (hosted on Render)  ───────────►  Postgres (bills, extractions, factors, records, audit...)
        │                         └──────────────►  File storage (bill PDFs, report PDFs): local disk or S3
        │ background worker threads
        ▼
 PDF text (pdfplumber) ─ no text? ─► OCR (Tesseract, or Gemini vision if not installed)
        ▼
 LangChain ChatGoogleGenerativeAI ──► Google Gemini (needs GOOGLE_API_KEY)
        ▼
 Code validation  ─►  approved  or  needs_review (human)  ─►  calculation engine (Decimal math)  ─►  emission records
                                                                     ▲
                                              emission factors (seed YAML → DB, versioned)
```

**Technology**

| Part | Tech | Why |
|---|---|---|
| Frontend | React 19, Vite, Tailwind CSS 4, Recharts, react-router, react-dropzone | Fast SPA, charts. |
| Backend | Python, FastAPI, SQLAlchemy 2, Alembic, Pydantic | Typed API, migrations. |
| DB | PostgreSQL in production, SQLite for local/tests | SQLite needs no setup. |
| PDF reading | pdfplumber (text), pypdfium2 (render pages), Tesseract via pytesseract (OCR), with Gemini vision as the fallback | |
| AI | LangChain (`langchain-google-genai`, `ChatGoogleGenerativeAI`) + Google Gemini | Needs a free `GOOGLE_API_KEY`. |
| Math | Python `Decimal` everywhere (never floats) | Exact, reproducible results. |
| Reports | ReportLab (PDF) + matplotlib (charts) | Deterministic output. |
| Auth | bcrypt password hashes, JWT bearer tokens | |
| Files | Local folder or any S3-compatible bucket (boto3) | |

---

## 4. The life of one bill, step by step

1. **Upload** (`POST /api/bills/upload`, `app/api/bills.py`). For each file the server checks:
   name ends in `.pdf`; size ≤ 20 MB; the first bytes are `%PDF-`; at most 50 files per request.
   It computes the file's **SHA-256 hash**. If the same file (same hash) was already uploaded by
   this organization, or twice in the same batch, it is reported as a **duplicate** and not stored
   again. Otherwise the file is saved to storage under `bills/<org-id>/<hash>.pdf`, a `bill` row is
   created with status `uploaded`, an audit entry is written, and the bill ID is put on the job
   queue. Each file gets its own result (`queued`, `duplicate`, `rejected` + reason), so one bad
   file never fails the batch.
2. **Queue** (`app/pipeline/queue.py`). A small thread pool (3 workers by default) processes bills
   in the background so the upload request returns immediately. The pool also limits how many
   LLM calls run at once. When the server restarts, every bill still `uploaded`/`processing` is
   put back on the queue.
3. **Worker** (`app/pipeline/runner.py`, `process_bill`) sets status `processing`, then:
   1. **Read text** (`app/pipeline/text.py`). pdfplumber extracts text page by page. A page with
      fewer than 40 non-blank characters is treated as scanned: it is rendered to an image at
      300 DPI and read by **Tesseract OCR**; if Tesseract isn't installed (e.g. on Render) the page image is read by **Gemini vision** instead. Limits: max 30 pages; encrypted/corrupt PDFs give
      a clear error. The pages are joined as `=== PAGE 1 ===`, `=== PAGE 2 ===`... so the AI (and
      the checks) know which page is which.
   2. **Extract with the AI** (`app/pipeline/llm.py`). See [section 5](#5-the-ai--langchain-part).
      If the reply is invalid, it is retried **once** with the error message; after that the bill
      fails with a readable reason.
   3. **Validate with code** (`app/pipeline/validate.py`). See [section 6](#6-validation-the-checks-that-decide-auto-approve-or-review).
   4. **Store** an `extraction` row (older extractions of the same bill are kept but marked not
      current), including the full list of issues.
   5. **Decide.** No issues → status `approved` automatically and the bill is **calculated
      immediately** (audit actor: `system`). Any issue → status `needs_review`.
   Anything unexpected is caught: the bill becomes `failed` with a short reference code (the full
   error is in the server log). `process_bill` never crashes the worker or other bills.
4. **Review** (if needed). A person fixes or confirms; see [section 7](#7-human-review).
5. **Calculate** (`app/calc/`). See [section 8](#8-the-calculation-explained-with-a-worked-example).
   One or more `emission_record` rows are written with a complete JSON trace.
6. **Report on it**: the dashboard and PDF reports include approved, calculated bills only.

The upload page polls `GET /api/bills/status?ids=...` every 2 seconds to show live progress.

---

## 5. The AI / LangChain part

File: `backend/app/pipeline/llm.py` (the AI call) and `app/pipeline/schema.py` (the contract).

**One API key.** The AI is a **LangChain `ChatGoogleGenerativeAI`** model (Google **Gemini**). Create a
free key at https://aistudio.google.com/apikey and set it as `GOOGLE_API_KEY` (never commit it). The
model is chosen with `LLM_MODEL` (default `gemini-2.5-flash`).

**The prompt.** `SYSTEM_PROMPT` tells the model it is a careful data-entry clerk: copy values
exactly as printed; do **not** calculate, convert, add up, round or infer; give `null` for
anything not on the bill; quote the exact line the quantity came from; if no total consumption is
printed, return the meter readings instead (and never compute the difference itself); report a
confidence.

**The contract.** The model must reply with JSON of exactly this shape (`LLMExtraction`):

| Field | Meaning |
|---|---|
| `utility_type` | `electricity`, `natural_gas` or `unknown` |
| `provider_name`, `account_number` | as printed |
| `billing_period_start/_end` | `YYYY-MM-DD`, the consumption period |
| `quantity`, `unit` | total consumption and its unit exactly as printed (`kWh`, `SCM`, `therms`, `MMBtu`...) |
| `meter_readings` | `previous`, `current`, `multiplier` (used only if no total is printed) |
| `read_type` | `actual`, `estimated`, `unknown` |
| `multiple_meters_or_line_items` | true if the bill has several meters or consumption lines |
| `page_number`, `source_snippet` | where the quantity was found and the exact text |
| `confidence` | 0 to 1 |
| `notes` | anything a reviewer should know (solar export, corrected bill...) |

Enforcement is layered: (1) the JSON schema is put in the prompt and Gemini runs in JSON mode
(`response_mime_type=application/json`); (2) Pydantic re-validates it and **rejects extra fields**; (3) numbers
are parsed as `Decimal` straight from the JSON text so `1234.56` stays exact (a float would not);
(4) on a bad reply the model is asked once more with the exact error.

**Robustness.** Temperature is 0 (deterministic). A bill whose text is longer than 60,000
characters is *refused* rather than cut off (the consumption figure could be in the missing part).
Connection errors are retried 4 times with growing waits (2s, 4s, 8s). If the server is
unreachable or rate-limited, the bill fails with: *"Could not reach the Gemini API (rate limit or
network). Reprocess the bill in a minute."* A missing key gives *"GOOGLE_API_KEY is not set..."* and a
rejected key *"Gemini rejected the API key..."*. Calls are spaced to `LLM_REQUESTS_PER_MINUTE`
(default 10, the free-tier quota).

**Testing hook.** The rest of the app only knows the tiny `Extractor` interface (`extract(text,
correction) -> JSON string`). Tests plug in a fake extractor; production uses
`LangChainExtractor`.

**Choosing a model.** Bigger models read messy bills better. Whatever the model gets wrong is
caught by the validation rules or the review queue, but a weak model means more bills go to
review. The default is `gemini-2.5-flash`; test on the sample bills (`pytest -m live`) and set
`LLM_MODEL=gemini-2.5-pro` if accuracy is poor.

---

## 6. Validation: the checks that decide "auto-approve or review"

All in `app/pipeline/validate.py`. They are plain code, not AI. **Any issue sends the bill to
review.** Nothing is rejected outright, because a human may be able to fix it.

*Rules about the model's reading of the PDF*
- `low_confidence`: confidence below 0.85.
- `multiple_meters`: the bill has several meters/lines; confirm the total.
- `estimated_read`: the meter reading is estimated.
- `model_notes`: the model wrote a note.
- `snippet_missing` / `snippet_page_invalid` / `snippet_not_found`: the quoted snippet must exist
  **on the cited page** of the extracted text (whitespace and case ignored). This is the guard
  against invented values.
- `quantity_not_in_snippet`: the printed quantity must actually appear as a number in the snippet.
- `readings_not_on_page`: when using meter readings, both readings must appear on the page.

*Rules about the values themselves*
- `utility_unknown`: not electricity or gas.
- `unit_missing` / `unit_not_allowed` / `unit_utility_mismatch`: unit must be one of
  `kWh, MWh, therm, m3, scf, ccf, Mcf, MMBtu, GJ`, and must suit the utility (electricity is
  energy only; gas may be energy or volume). Aliases are understood (`SCM`→m3, `therms`→therm,
  `m³`, `cubic feet`...). The bare word "units" is deliberately *not* accepted (ambiguous).
- `period_missing` / `period_order` / `period_too_long` / `period_in_future`: both dates present,
  end after start, at most 95 days, end not in the future.
- `quantity_missing` / `quantity_not_positive`: need a usable number > 0.
- `meter_rollover`: current reading below previous.
- `meter_mismatch`: printed total ≠ (current − previous) × multiplier.
- `multiplier_not_printed`: readings used but no multiplier printed (assumed 1; check it).
- `account_missing`: no account number.
- `account_unmapped`: first time this account number is seen. **So the first bill of every
  account always goes to review**; approving it teaches the system "account X belongs to facility
  Y". Later clean bills for that account auto-approve.
- `account_other_facility`: the account is known but belongs to a different facility.
- `overlapping_period`: another non-rejected bill for the same facility and utility covers
  overlapping dates (possible duplicate).
- `outlier`: daily usage is more than 3× or less than 1/3 of the facility's median daily usage
  (needs at least 3 earlier approved bills).

Some issues are **blocking** (the bill cannot be calculated at all: unknown utility, bad/missing
unit, bad period, no quantity, meter rollover); the others are **warnings** that a reviewer
acknowledges by approving.

---

## 7. Human review

Pages: **Review** (queue) and **Review → a bill**. Code: `app/review.py`, `app/api/review.py`.

The review screen shows the **bill page image on the left** (rendered by `app/pipeline/pages.py`,
with the source snippet boxed in yellow when the PDF has a text layer) and an **editable form on
the right**. Each field is outlined red/amber/blue depending on its issue.

Actions:
- **Correct**: change fields (provider, account, dates, quantity, unit, meter readings, read type,
  utility type, facility). The original AI value is kept in `corrections_json` as `before`; your
  value as `after`; each change is audited with who/when/why. After a correction the field rules
  run again. Numbers must be sent as strings so they stay exact (max 6 decimals).
- **Approve**: applies corrections and approves in one transaction. Blocking issues must be fixed
  first; warnings are recorded as "acknowledged". Approval also saves the account → facility
  mapping (if the account already points at another facility you must either change this bill's
  facility or confirm the account moved). Then the bill is calculated.
- **Reject**: needs a reason. The bill is excluded from reporting.
- **Reopen** (admin only): send an approved/rejected bill back to review with a reason; its
  emissions leave the totals until it is approved again (old records are kept as history).
- **Reprocess**: re-run extraction for `failed`/`needs_review` bills (e.g. after a rate-limit error).
- **Concurrent edits**: each request sends the bill's `updated_at`; if someone else changed the
  bill meanwhile you get a "reload" error instead of overwriting their work.

---

## 8. The calculation, explained with a worked example

Code: `app/calc/` (pure, `Decimal` only; floats are rejected). Formula for each piece of a bill:

```
kg CO2e  =  quantity  ×  (days in piece ÷ days in billing period)  ×  unit conversion  ×  emission factor
```

**Step 1 - effective quantity** (`quantity.py`): the printed total, or, if only meter readings
are printed, `(current − previous) × multiplier`. The AI never does this subtraction.

**Step 2 - split the period** (`prorate.py`): the billing period (inclusive of both dates) is cut
at the start of every calendar month, and also at any date where an emission factor's validity
changes. Consumption is assumed uniform, so each piece receives its share by day count. Each piece
lies in exactly one month, which keeps monthly and yearly totals exact.

**Step 3 - pick the factor** (`factors.py`), in order:
1. same utility, not superseded, valid on the piece's start date;
2. region: the facility's exact region. Only if **no** factor of that utility exists for the exact
   region at all may the parent be used (`US-CAMX` → `US`, e.g. gas, which is published nationally).
   A factor that merely doesn't cover the date is an **error**, never a silent fallback;
3. an organization's own factor beats a global one;
4. the factor's unit must be convertible from the bill's unit (same kind of quantity);
5. still ambiguous, or none → the calculation fails with an explanation. **There is no default factor.**

**Step 4 - convert units** (`units.py`): exact constants (1 kWh = 3.6 MJ, 1 therm = 100,000 Btu(IT),
1 ft³ = 0.028316846592 m³ ...). Only within the same dimension (energy↔energy, volume↔volume).
**A gas bill in m³ with only energy-based factors fails** with an explanation; the app never guesses
a calorific value.

**Step 5 - multiply and round** (`engine.py`): 34 significant digits internally; the result is
rounded **once** to 6 decimal places (half-even). Each piece becomes one `emission_record` with a
JSON trace (bill, page, snippet, who approved, allocation, conversion, factor key/version/source,
formula text, scope).

**Worked example** (sample bill `in-pune-electricity-2024-01.pdf`): 14,250 kWh, 1-31 Jan 2024,
region `IN`. One piece (31/31 days). 14,250 kWh = 14.25 MWh. The CEA FY2023-24 factor is
0.727 tCO2/MWh = 727 kg/MWh. So 14.25 × 727 = **10,359.75 kg CO2** (Scope 2).

**Cross-year example** (`in-pune-electricity-2024-03-cross-fy.pdf`): 16 Mar - 15 Apr 2024 is 31
days. It is split into 16 Mar-31 Mar (16 days, FY2023-24 factor 727) and 1 Apr-15 Apr (15 days,
FY2024-25 factor 710). Two records, one per piece.

**When bills are recalculated automatically**: when a bill is auto-approved or approved; when a
factor is added/versioned or the seed is loaded; or when an admin calls `POST /api/bills/recalculate`.
It is idempotent: if nothing changed, nothing is written. If the result changed, old records are
kept with `is_current = false` (never deleted) and the change is audited. An approved bill that
cannot be calculated stores a `calculation_error`, counts for nothing, and is flagged on the
dashboard.

---

## 9. Emission factors

Stored in the database table `emission_factor`, loaded from `backend/seed/emission_factors.yaml`
by `python -m app.seed` (idempotent; the Render start command runs it every deploy).

Each factor stores: a stable **key** (e.g. `IN-CEA-GRID-FY2023-24`), a **version**, utility,
region, the unit it is "per", the derived `kgco2e_per_unit`, GHG basis (`CO2` or `CO2e`), scope,
source name + URL + year, the values **exactly as published**, a human-readable **derivation**,
and validity dates (`valid_from`, `valid_to`).

- **Never edited in place.** To correct a value, add the same key with `version + 1`; the old one
  is marked superseded and kept for history. Changing a value under an existing version makes the
  seed loader refuse with an error.
- **Derivation** (`calc/factor_derivation.py`): the loader converts published numbers (e.g.
  CO2/CH4/N2O in lb per MWh) into kg CO2e per unit, applying the stored GWP set (AR5) when gases
  are listed separately. Check the YAML without a DB: `python -m app.seed --check`.
- **Global vs organization factors**: seeded ones are global; admins can add their own
  organization-specific factors on the *Emission factors* page (they take precedence).

| Region | Utility | Source | Coverage |
|---|---|---|---|
| IN | electricity | CEA CO2 Baseline Database (weighted average incl. RE; **CO2 only**) | FY2022-23 to FY2024-25 |
| IN | natural gas | IPCC 2006 Guidelines Vol. 2 Ch. 2 Table 2.3 | open-ended |
| UK | electricity, gas (kWh, m³) | DESNZ GHG conversion factors 2025, 2026 | calendar 2025, 2026 |
| US, `US-<eGRID subregion>` | electricity | EPA eGRID2023 (CO2e output rate) | 2023-2024 |
| US | natural gas (MMBtu, scf) | EPA GHG Emission Factors Hub (Jan 2025) | 2024 onward |

A bill dated outside every factor's validity fails with a clear message instead of using another
year's number. To cover a new period add the newly published factor (new key) in the YAML or on
the Emission factors page, then recalculate. **Every seeded value is marked "TODO: verify against
latest published edition"; verify before real reporting** (see section 23).

---

## 10. Dashboard

Code: `app/dashboard.py`, `app/api/dashboard.py`, `frontend/src/pages/DashboardPage.jsx`.

One row of filters (reporting period, facility, utility) controls every number.

- **What is counted:** only *current* emission records of **approved** bills inside the period.
- **Honesty banner:** counts the bills that may belong to the period but are *not* included
  (in review, processing, failed, approved-but-not-calculated). A partial total is never presented
  as final.
- **Periods** are whole months, following the organization's fiscal year (e.g. FY2023-24), or a
  custom month range. `period_start` must be a 1st and `period_end` a month's last day.
- **Exact sums:** added up as exact kg, converted to tonnes once, rounded to 3 decimals. If the
  rounded Scope 1 + Scope 2 differs from the rounded total, the page says so.
- **Layout:** headline total; Scope 1 / Scope 2 tiles with a split bar; monthly stacked bars
  (with a table view); facility donut (top 3 + "Other") with a full list; a bills table whose
  rows open the bill's **calculation trace** in a side drawer.
- **CO2-only note:** shown when part of the total comes from grid factors that cover CO2 only (CEA).

---

## 11. Reports (the PDF)

Code: `app/reports/` (`snapshot.py`, `pdf.py`, `charts.py`, `service.py`), `app/api/reports.py`.

1. **Snapshot** - every fact the report shows is frozen as JSON: each emission record with its
   bill, file hash, allocation, factor, formula; reviewers and corrections; every factor used with
   source and derivation; bills left out; the organization and period; the engine version. Numbers
   are decimal strings.
2. **PDF** - rendered **only from the snapshot**: cover; executive summary; breakdown by month and
   facility; methodology (GHG Protocol boundary, formula, pro-rating, units, rounding, table of
   every factor with source URL/version, limitations); **Appendix A** every bill and its monthly
   allocations; **Appendix B** every manual correction; **Appendix C** bills left out and why.
3. **Draft vs complete** - if any bill that may belong to the period is left out, the report is a
   **DRAFT**: watermarked on every page, cover says so, filename ends `-DRAFT`.
4. **Integrity** - SHA-256 of the snapshot and of the PDF are stored. Rendering is deterministic.
   `POST /api/reports/{id}/verify` re-checks both hashes and re-renders the PDF from the stored
   snapshot to confirm it is byte-identical, even after live data changed. (This assumes the same
   ReportLab/matplotlib versions, which `requirements.txt` pins.)

Reports can be generated for any whole-month period on the **Reports** page, then downloaded
(PDF or the snapshot JSON) and verified.

---

## 12. Users, organizations, security

- **Register** (`/register`) creates an **organization** and its first user, who is an **admin**.
  You choose the organization's name, reporting framework label (BRSR/SECR/CSRD/EPA/OTHER), default
  region, and fiscal-year start month (default April = 4). Password ≥ 10 characters, stored as a
  bcrypt hash.
- **Roles:** `admin` (manage users, facilities, org emission factors, recalculate, reopen bills)
  and `member` (upload, review, view, create reports).
- **Login** returns a JWT (8-hour expiry) that the frontend keeps in `localStorage` and sends as
  `Authorization: Bearer ...`. Login timing is equalized so response time doesn't reveal which
  emails exist.
- **Tenant isolation:** every query is scoped to the caller's organization; another
  organization's IDs return 404, never 403.
- **Files:** never public. They are only served through API endpoints that check the
  organization. Storage keys are built from a UUID and a hash only, so user input never reaches a
  file path.
- **JWT secret:** generated automatically on first start and saved to `<storage dir>/.jwt_secret`
  (or set `JWT_SECRET` yourself; on Render the blueprint generates one).
- **Audit log** (`audit_log` table, `GET /api/audit`, admin only): every important action with
  actor, before/after JSON and timestamp. Actor `system` = automatic steps.
- **Still to do for production hardening:** login rate limiting/lockout, password reset, MFA,
  segregation of duties (today the uploader may also approve).

---

## 13. Data model (database tables)

Defined in `backend/app/models/`, created by Alembic migrations in `backend/alembic/versions/`.

| Table | Purpose |
|---|---|
| `organization` | Company: name, framework, default region, fiscal-year start month. |
| `app_user` | Users: org, email (unique), bcrypt hash, role, active flag. |
| `facility` | Site: org, name (unique per org), address, **region**. |
| `facility_account` | Learned mapping *(org, utility, account number) → facility*. |
| `bill` | Uploaded PDF: org, facility, filename, storage key, SHA-256 (unique per org), size, utility, status, failure reason, calculation error, uploader, timestamps. |
| `extraction` | What was read from a bill (all the fields above), `is_current`, issues JSON, reviewer, `corrections_json`, model name, text method (`pdfplumber`/`ocr`). |
| `emission_factor` | Versioned factors (see section 9). `org_id` NULL = global. |
| `emission_record` | One calculated piece: extraction, factor, allocation dates + fraction, normalized quantity/unit, **kgco2e**, scope, trace JSON, `is_current`. |
| `report` | Generated report: period, status, snapshot JSON, snapshot/PDF hashes, draft flag, file key. |
| `audit_log` | Append-only history. |

Numbers use `Numeric(20,6)` (quantities, kg) and `Numeric(24,12)` (factors). JSON columns are
`JSONB` on Postgres and plain JSON on SQLite. Keys are UUIDs.

---

## 14. The website, page by page

Code: `frontend/src/`. Routes are in `main.jsx`; all calls go through `api/client.js`, which adds the
token and prefixes `VITE_API_URL` if set.

| Route | Page | What it does |
|---|---|---|
| `/login`, `/register` | AuthPage | Sign in; or create an organization + admin. |
| `/dashboard` | DashboardPage | Totals and charts (section 10). Lazy-loaded so charts don't slow the first page. |
| `/upload` | UploadPage | Pick a facility, drag-and-drop PDFs (≤ 20 MB), see each file's live status. |
| `/review` | ReviewQueuePage | Bills waiting for a person, oldest first; counts also shown as a badge in the top nav. |
| `/review/:billId` | ReviewPage | Side-by-side page image and editable form (section 7). |
| `/bills` | BillsPage | Masonry grid of bill cards with filters, status, quantity, emissions. |
| `/bills/:id` | BillDetailPage | One bill: status, extraction, issues, PDF, calculation trace, reprocess/reopen. |
| `/reports` | ReportsPage | Create, download, verify reports. |
| `/facilities` | FacilitiesPage | Add/edit facilities. The region must have emission factors, otherwise it is rejected (a typo would make every bill fail). |
| `/factors` | FactorsPage | Browse factors with history; admins add organization factors or new versions. |

Shared pieces: `Layout.jsx` (floating glass nav bar + review badge refreshed every 30 s), `ui.jsx`
(buttons, glass cards, page headers), `status.jsx` (status badges), `issues.js` (human wording for
issue codes), `viz.js` (chart colors: Scope 1 ember, Scope 2 forest green, colorblind-safe),
`EmissionsTrace.jsx` (renders the calculation trace), `Drawer.jsx` (side panel), `auth.jsx` (login
state).

**Design system** (all tokens live in `frontend/src/index.css`). The look is a Pinterest-style,
card-first layout with glassmorphism: frosted-glass surfaces (`.glass`, `.glass-strong`) over a soft
aurora background, pill-shaped navigation and buttons, and masonry card grids (`.masonry`, `.pin`) for
bills, the review queue and facilities. The palette is chosen for the product: **forest green**
(brand, "verified and clean") on **warm paper neutrals** (the "auditable document" feel), with
**ember** reserved for natural gas / Scope 1 and **amber** for "needs attention". Tailwind's
`emerald` and `slate` scales are overridden in `@theme`, so changing the brand colour is a one-place
edit. Motion respects `prefers-reduced-motion`.

---

## 15. Folder-by-folder, file-by-file guide

```
GreenTrace/
├── README.md                  this guide
├── render.yaml                Render blueprint (backend + Postgres)
├── .gitignore
├── samples/                   demo bills + ground truth (section 18)
├── backend/
│   ├── requirements.txt       runtime dependencies (pinned)
│   ├── requirements-dev.txt   + pytest, coverage, moto (fake S3)
│   ├── pyproject.toml         pytest settings
│   ├── alembic.ini, alembic/  database migrations (0001 schema, 0002 calc error, 0003 report hashes)
│   ├── seed/emission_factors.yaml   all emission factors with sources
│   ├── app/                   the application (below)
│   └── tests/                 279 automated tests
└── frontend/
    ├── package.json, vite.config.js, index.html
    ├── vercel.json            SPA routing for Vercel
    └── src/                   React app (section 14)
```

**`backend/app/`**

| File / folder | Role |
|---|---|
| `main.py` | Creates the FastAPI app, CORS (open to all origins; auth is a header token, not cookies), mounts all routers under `/api`, re-queues unfinished bills at startup, `/api/health`. |
| `config.py` | All settings with defaults (section 16); auto-generates the JWT secret. |
| `db.py` | SQLAlchemy engine/session (SQLite foreign keys switched on). |
| `deps.py` | FastAPI dependencies: DB session, current user from JWT, `AdminUser`. |
| `security.py` | Password hashing (bcrypt) and JWT create/decode. |
| `audit.py` | `record()` writes audit rows inside the current transaction. |
| `enums.py` | Utility types, scopes, bill statuses, roles, frameworks, GHG basis. |
| `schemas.py` | Pydantic request/response models for the API. |
| `storage.py` | `LocalStorage` and `S3Storage` behind one interface. |
| `seed.py` | Loads the factor YAML into the DB (`python -m app.seed`). |
| `factor_service.py` | Builds/validates/versions factors; used by the seed and the API. |
| `dashboard.py` | Dashboard aggregation (exact Decimal sums). |
| `review.py` | Correct/approve/reject/reopen business logic. |
| `models/` | `base.py` (types), `org.py`, `bill.py`, `emissions.py`. |
| `api/` | One router per area: `auth, users, facilities, factors, bills, review, dashboard, reports, audit`. |
| `pipeline/text.py` | PDF → text per page, OCR fallback. |
| `pipeline/llm.py` | LangChain/Gemini extractor, Gemini-vision OCR, prompt, retry logic. |
| `pipeline/schema.py` | The AI contract (Pydantic + JSON Schema). |
| `pipeline/validate.py` | All validation rules (section 6). |
| `pipeline/runner.py` | Orchestrates one bill end to end. |
| `pipeline/queue.py` | Background thread pool + restart recovery. |
| `pipeline/pages.py` | Renders a page as PNG with the snippet highlighted. |
| `pipeline/errors.py` | Error types with user-readable messages. |
| `pipeline/cli.py` | Try the pipeline on PDFs from the command line, no DB. |
| `calc/units.py` | Unit registry and exact conversions. |
| `calc/quantity.py` | Printed total vs meter-reading arithmetic. |
| `calc/prorate.py` | Period splitting and fiscal-year labels. |
| `calc/factors.py` | Factor selection rules. |
| `calc/factor_derivation.py` | Published values → kg CO2e per unit. |
| `calc/engine.py` | The calculation and its trace. |
| `calc/service.py` | DB side: load factors, store records, recalculate. |
| `reports/` | `snapshot.py`, `pdf.py`, `charts.py`, `service.py`. |

---

## 16. Configuration (no `.env`; one API key)

Nothing reads a `.env` file, and there is no API key in the project. Every setting has a working
default in `app/config.py`. In deployment you can override a setting with a normal **process
environment variable** of the same name in upper case (set in the Render dashboard); you never need
to create a file.

| Setting | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | local SQLite file `backend/greentrace.db` | Postgres URL in production. `postgres://` and `postgresql://` are auto-converted to the psycopg driver. |
| `JWT_SECRET` | auto-generated and saved in storage dir | Token signing key (≥ 32 chars). Set explicitly if you run several API instances. |
| `JWT_EXPIRE_MINUTES` | 480 | Login lifetime. |
| **`GOOGLE_API_KEY`** (or `GEMINI_API_KEY`) | unset | **Required.** Free key from https://aistudio.google.com/apikey |
| `LLM_MODEL` | `gemini-2.5-flash` | Which Gemini model to ask. |
| `LLM_TIMEOUT_SECONDS` | 120 | Per-request timeout. |
| `LLM_REQUESTS_PER_MINUTE` | 10 | Client-side rate limit (0 = off). |
| `EXTRACTION_WORKERS` | 3 | Parallel bill workers. |
| `MAX_PROMPT_CHARS` | 60000 | Bills with longer text are refused, not truncated. |
| `STORAGE_BACKEND` | `local` | `local` or `s3`. |
| `STORAGE_DIR` | `backend/storage` | Folder for local storage (on Render: the disk mount `/var/data`). |
| `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_PREFIX` | unset | For `s3` storage (these are storage credentials, only needed if you choose S3). |
| `MAX_UPLOAD_MB` / `MAX_FILES_PER_UPLOAD` / `MAX_PDF_PAGES` | 20 / 50 / 30 | Upload limits. |
| `MIN_TEXT_CHARS_PER_PAGE` / `OCR_DPI` / `TESSERACT_CMD` | 40 / 300 / unset | OCR behavior; Tesseract is optional; without it scanned pages go to Gemini vision. |
| `REVIEW_CONFIDENCE_THRESHOLD` | 0.85 | Below this → review. |
| `MAX_BILLING_PERIOD_DAYS` | 95 | Longer periods → review. |
| `OUTLIER_RATIO` / `OUTLIER_MIN_HISTORY` | 3.0 / 3 | Outlier rule. |
| `REQUEUE_ON_STARTUP` | true | Resume interrupted bills on start. |

Frontend (set in the Vercel project settings, not in a file): `VITE_API_URL` = the backend's URL.

---

## 17. Run it on your computer

Prerequisites: **Python 3.11+**, **Node 20+**, a free **Gemini API key** (https://aistudio.google.com/apikey), and
optionally **Tesseract** for scanned bills (without it, Gemini vision reads them). Poppler is
not needed.

```powershell
# 0. Give the backend your Gemini key (PowerShell; set it in the same terminal that runs the API)
$env:GOOGLE_API_KEY = "your-key-here"

# 1. Backend
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\alembic upgrade head                          # create the tables (SQLite file)
.venv\Scripts\python -m app.seed                            # load the emission factors
.venv\Scripts\python -m uvicorn app.main:app --port 8000    # restart after code changes
#   API docs: http://localhost:8000/docs

# 2. Frontend (a second terminal)
cd frontend
npm install
npm run dev                                                 # http://localhost:5173 (proxies /api to :8000)
```

Then open http://localhost:5173, **Register** an organization, add a **Facility**, and **Upload**
bills (use the `samples/` PDFs, section 18).

Try the pipeline without the website or database:

```powershell
cd backend
.venv\Scripts\python -m app.pipeline.cli --text-only ..\samples\bills\in-pune-electricity-2024-01.pdf   # only the text
.venv\Scripts\python -m app.pipeline.cli ..\samples\bills\in-pune-electricity-2024-01.pdf               # + AI + validation
```

The repo may live in OneDrive; exclude `backend/.venv` and `frontend/node_modules` from sync (or move
the repo) to avoid slow installs and file-lock errors.

---

## 18. The `samples/` folder: what it is and what to do with it

`samples/` contains **10 synthetic utility bills** (PDFs) from **fictional** suppliers, plus the
answer key. It exists so you can try and test the whole system without real bills.

```
samples/
├── bills/               the 10 PDFs
├── manifest.json        the answer key: what is printed on each bill + the hand-worked expected emissions
└── generate_bills.py    the script that created the PDFs and the manifest
```

**What to do with it:**

1. **Demo the app (most useful).** After registering, create the facilities below (names are just
   labels; the **region** matters) and upload each bill to its facility:

   | Organization to register | Fiscal year start | Facility → region | Bills |
   |---|---|---|---|
   | India (framework BRSR) | April (4) | Pune Plant → `IN`, Chennai Plant → `IN` | the 6 `in-*` bills |
   | UK (SECR) | January (1) | London Office → `UK` | the 2 `uk-*` bills |
   | US (EPA) | January (1) | San Francisco Lab → `US-CAMX` | the 2 `us-*` bills |

   Upload `pune` bills to Pune Plant, `chennai` to Chennai Plant, etc. Because every account number
   is new, **every bill will land in the Review queue the first time**; that is correct behavior. Open
   each, compare with the page image, and Approve. Then look at the Dashboard (choose a period that
   covers 2023-2026) and generate a Report.
2. **Check the AI.** Run `pytest -m live` (section 19): it sends the 8 text-layer samples to your
   real Gemini model and compares every extracted field with the manifest. This is the quickest way to
   decide if your chosen model is good enough.
3. **Check the maths.** `manifest.json` has `expected_kgco2e` for each bill, worked out by hand
   independently of the code (`expected_working` explains each). After approving, the bill's total
   on screen must match exactly (e.g. Pune Jan 2024 = 10,359.75 kg).
4. **Automated tests use it.** `backend/tests/test_integration_samples.py` uploads every sample,
   with a "perfect reader" standing in for the AI, and asserts every figure equals the manifest.
   You do not need to do anything for that; it runs with `pytest`.
5. **Regenerate** (only if you change the bills): `backend\.venv\Scripts\python samples\generate_bills.py`.
   This rewrites the PDFs *and* the manifest.

What each bill is designed to test:

| Bill | Tests |
|---|---|
| `in-pune-electricity-2024-01` | Baseline Indian electricity (CEA factor). |
| `in-pune-electricity-2024-03-cross-fy` | 16 Mar-15 Apr: split across the April 1 fiscal-year boundary and two different CEA factors. |
| `in-chennai-electricity-2024-02-meter-readings` | No total printed: (current − previous) × multiplier 20. The AI must not calculate it. |
| `in-chennai-gas-2024-02-mmbtu` | Indian gas in MMBtu converted to TJ for the IPCC factor. |
| `in-pune-electricity-2024-02-scanned` | Image-only scan: needs OCR (Tesseract or Gemini vision). |
| `in-chennai-electricity-2023-12-two-pages` | Consumption appears on page 2. |
| `uk-london-electricity-2025-12-cross-year` | Dec 2025-Jan 2026: DESNZ 2025 and 2026 factors. |
| `uk-london-gas-2025-03` | UK gas in kWh (gross CV). |
| `us-sf-electricity-2024-06` | eGRID subregion CAMX, lb → kg conversion. |
| `us-sf-gas-2024-11-therms` | therms → MMBtu; national factor via parent region. |

The samples are **not** used by the deployed app at runtime; they are demo/test data only. You can
leave the folder in the repo (it's useful documentation) or delete it from a production copy.
Never treat the fictional emissions numbers as real.

---

## 19. Tests

```powershell
cd backend
.venv\Scripts\python -m pytest              # all offline tests: SQLite in memory, no network, no API key
.venv\Scripts\python -m pytest -m live -v   # opt-in: real Gemini model on the sample bills (needs GOOGLE_API_KEY)
```

- **Unit tests:** units and derivation, factor selection, pro-rating and the engine (expected
  values worked by hand in the comments, plus random-period property tests), validation rules,
  text extraction + OCR fallback, and the LangChain extractor (request shape, retries, error
  messages) using a fake chat model.
- **API tests:** auth and tenant isolation, upload, review, dashboard, reports, storage (local and
  S3 via `moto`).
- **`test_integration_samples.py`:** every sample bill end to end (see section 18).
- **`test_live_extraction.py`** (`-m live`): the real model vs the manifest. Skipped automatically if
  `GOOGLE_API_KEY` is not set.
- **`test_migrations.py`:** fails if a model changes without a matching Alembic migration.

Frontend: `cd frontend && npm run build` must succeed.

---

## 20. Deploy: Vercel (frontend) + Render (backend)

No Docker is used.

**Backend on Render**
1. Push the repo to GitHub. In Render choose **New → Blueprint** and select the repo; it reads
   `render.yaml` and creates a Postgres database and a Python web service (root dir `backend`).
2. Build: `pip install -r requirements.txt`. Start: `alembic upgrade head && python -m app.seed &&
   uvicorn app.main:app --host 0.0.0.0 --port $PORT` (migrates and loads factors on every deploy).
   Health check: `/api/health`.
3. Set in the Render dashboard: `GOOGLE_API_KEY` = your Gemini key. No CORS setting is needed (the API
   accepts requests from any origin). `JWT_SECRET` and `DATABASE_URL` are filled
   automatically.
4. **Storage:** the blueprint attaches a persistent disk at `/var/data` (paid plan). On the free plan
   disks are ephemeral: set `STORAGE_BACKEND=s3` and the `S3_*` variables instead (e.g. Supabase
   Storage's S3 endpoint; keep the bucket private).

**Frontend on Vercel**
1. Import the same repo, set **Root Directory** to `frontend` (framework Vite is detected).
2. Add the environment variable `VITE_API_URL` = `https://<your-api>.onrender.com`, then deploy.
   `vercel.json` makes page refreshes on `/dashboard` etc. work.

**The AI.** Gemini is a hosted API, so there is nothing to run yourself: just set `GOOGLE_API_KEY` in
the Render dashboard. On the free Gemini tier requests are limited (about 10 per minute for Flash);
GreenTrace spaces its calls to stay under that and retries with backoff. If a bill still fails with a
rate-limit message, click **Reprocess** a minute later, or enable billing on the key.

**OCR on Render.** The native Python runtime has no Tesseract, so scanned (image-only) pages are
read by **Gemini vision** with the same `GOOGLE_API_KEY`. No extra setup or Docker is needed.

**Background jobs** run in a thread pool inside the API process, which is right for one API
instance. For several instances move processing to a shared queue (RQ/Celery + Redis);
`JobQueue.enqueue` is the only seam to change.

---

## 21. API reference

All paths are under `/api`. Interactive docs at `/docs` on the backend. All except register/login/health
need a Bearer token and are limited to your organization.

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | liveness |
| POST | `/auth/register` | create organization + admin → token |
| POST | `/auth/login` | → token |
| GET | `/auth/me` | current user + organization |
| GET/POST | `/users` | admin: list / add members |
| GET/POST | `/facilities` · PATCH `/facilities/{id}` | create/edit are admin; region must have factors |
| GET | `/factors` · `/factors/{id}` · `/factors/{id}/history` · `/factors/regions` · `/factors/gwp-sets` | browse |
| POST | `/factors` · `/factors/{id}/versions` | admin: organization factors |
| POST | `/bills/upload` | multipart `facility_id` + `files`; per-file outcome |
| GET | `/bills` | filters: `status`, `facility_id`, `utility_type`, `period_start/end` |
| GET | `/bills/{id}` · `/bills/{id}/file` · `/bills/{id}/trace` | detail, original PDF, calculation trace |
| GET | `/bills/{id}/pages/{n}` | PNG of a page, snippet highlighted (`X-Highlight`, `X-Page-Count` headers) |
| GET | `/bills/status?ids=...` | light polling |
| POST | `/bills/{id}/reprocess` | failed / needs_review bills |
| POST | `/bills/recalculate` | admin |
| POST | `/bills/{id}/reopen` | admin |
| GET | `/review` · `/review/counts` | queue (oldest first) · badge counts |
| POST | `/extractions/{id}/correct` · `/approve` · `/reject` | `changes` as strings; `expected_updated_at` for concurrency |
| GET | `/dashboard/periods` · `/dashboard?period_start&period_end&facility_id&utility_type` | |
| POST | `/reports` | `{period_start, period_end, label?}` |
| GET | `/reports` · `/reports/{id}` · `/reports/{id}/download` · `/reports/{id}/snapshot` | |
| POST | `/reports/{id}/verify` | hash checks + byte-identical re-render |
| GET | `/audit` | admin |

---

## 22. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Bill `failed`: "GOOGLE_API_KEY is not set..." | Set `GOOGLE_API_KEY` on the server and restart it, then click **Reprocess**. |
| Bill `failed`: "Gemini rejected the API key" | The key is wrong or revoked. Create a new one at aistudio.google.com/apikey. |
| Bill `failed`: "Could not reach the Gemini API" | Rate limit (free tier) or network. Wait a minute, then click **Reprocess**. |
| Bill `failed`: "looks scanned... neither Tesseract nor a GOOGLE_API_KEY" | Set `GOOGLE_API_KEY` (Gemini reads the scan) or install Tesseract. |
| Bill `failed`: "invalid data twice" | The model can't follow the format. Use a larger model. |
| Bill `failed`: "text is too long" | Upload only the bill pages (limit 60,000 characters). |
| Approved bill shows a calculation error | No factor covers its dates/region/unit. Add the factor on the *Emission factors* page, then an admin runs *Recalculate*. |
| Facility creation says "No emission factors exist for region..." | Use a known region (`IN`, `UK`, `US`, `US-CAMX` ...). |
| Browser: network error / `Failed to fetch` after deploying | `VITE_API_URL` on Vercel is missing or wrong (it must be the Render URL, https, no trailing path). Fix it and **redeploy** the frontend, since it is baked in at build time. |
| Everyone is logged out after a restart | The JWT secret wasn't persisted (read-only/ephemeral storage). Set `JWT_SECRET`. |
| Uploaded files vanish after a deploy on Render free | Ephemeral disk; use `STORAGE_BACKEND=s3`. |
| Everything goes to review | Expected for new accounts. Also check model confidence and the issue list on each bill. |

---

## 23. Known limits and what to verify before real reporting

1. **AI accuracy is not guaranteed.** Test your chosen model on the samples and real bills. The
   checks and review queue catch most mistakes, but a person is the final control.
2. **Emission factors need verification.** Every seeded value carries "TODO: verify against latest
   published edition". In particular the CEA v21 value (FY2024-25, 0.710 tCO2/MWh) could not be read
   from the source at seeding time and is flagged UNVERIFIED in the YAML.
3. **Coverage gaps.** Bills fail with "no factor covers this date" for Indian electricity after
   March 2025, US electricity after 2024, and UK outside 2025-2026, until newer factors are added.
4. **India gas basis.** The IPCC default is per TJ on a *net* calorific basis, while Indian gas bills
   in MMBtu/SCM are usually *gross*, so results may be roughly 10% high. Add a gross-basis or
   supplier-specific organization factor before reporting Indian gas.
5. **Tested on SQLite.** The tests run on SQLite; the models and migrations use portable types, but
   run the full flow once against your Render Postgres before go-live.
6. **OCR path** is tested with Tesseract mocked plus the real-Tesseract sample on machines that have
   it; it isn't available on Render's native runtime.
7. **Out of scope:** market-based Scope 2, Scope 3 (including transmission & distribution losses and
   well-to-tank), and fuels other than grid electricity and natural gas. Consumption is assumed
   uniform across a billing period when splitting it.
8. **Single API instance** for background jobs (see section 20).
9. **Security hardening** still to do: rate limiting, password reset, MFA, separation of duties.
