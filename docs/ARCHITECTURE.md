# GreenTrace: technical deep dive

This document explains how GreenTrace works internally: components, data flow, state machines,
the database, the calculation engine, concurrency, failure handling and deployment. It is the
technical companion to the [README](../README.md). The diagrams are [Mermaid](https://mermaid.js.org)
and render automatically on GitHub; in VS Code use a Mermaid preview extension.

Contents

1. [System context](#1-system-context)
2. [Backend layers](#2-backend-layers)
3. [Request lifecycle](#3-request-lifecycle)
4. [Bill processing pipeline](#4-bill-processing-pipeline)
5. [Bill state machine](#5-bill-state-machine)
6. [The LLM extraction layer](#6-the-llm-extraction-layer)
7. [Validation engine](#7-validation-engine)
8. [Review workflow and concurrency control](#8-review-workflow-and-concurrency-control)
9. [Calculation engine](#9-calculation-engine)
10. [Emission-factor selection](#10-emission-factor-selection)
11. [Recalculation and immutability](#11-recalculation-and-immutability)
12. [Database schema](#12-database-schema)
13. [Report generation and verification](#13-report-generation-and-verification)
14. [Authentication and multi-tenancy](#14-authentication-and-multi-tenancy)
15. [Storage](#15-storage)
16. [Frontend architecture](#16-frontend-architecture)
17. [Concurrency, transactions and failure handling](#17-concurrency-transactions-and-failure-handling)
18. [Deployment topology](#18-deployment-topology)
19. [Design decisions and trade-offs](#19-design-decisions-and-trade-offs)

---

## 1. System context

```mermaid
flowchart LR
    U([User in browser])
    subgraph Vercel
      FE["React SPA<br/>static files"]
    end
    subgraph Render
      API["FastAPI backend<br/>+ worker threads"]
      DB["(PostgreSQL)"]
      FS["(Disk or S3<br/>bill + report PDFs)"]
    end
    subgraph "Your own host"
      OL["Google Gemini API"]
    end

    U -->|HTTPS| FE
    FE -->|"REST/JSON + JWT (VITE_API_URL)"| API
    API --> DB
    API --> FS
    API -->|"LangChain ChatGoogleGenerativeAI<br/>HTTPS, GOOGLE_API_KEY"| OL
```

Everything the browser needs is static (Vercel); all logic and data live in the backend. The LLM
is a separate service so it can be sized (GPU/RAM) independently and swapped by changing
`GOOGLE_API_KEY` / `LLM_MODEL`.

---

## 2. Backend layers

```mermaid
flowchart TB
    subgraph "HTTP layer  (app/api/*, deps.py, schemas.py)"
      R1["auth / users / facilities / factors"]
      R2["bills / review"]
      R3["dashboard / reports / audit"]
    end
    subgraph "Domain services"
      REV["review.py<br/>correct / approve / reject / reopen"]
      DASH[dashboard.py]
      REP["reports/*<br/>snapshot, pdf, charts"]
      FSV[factor_service.py]
    end
    subgraph "Pipeline  (app/pipeline)"
      Q["queue.py<br/>thread pool"]
      RUN[runner.py]
      TXT["text.py<br/>pdfplumber + OCR"]
      LLM["llm.py<br/>LangChain"]
      VAL[validate.py]
      PG["pages.py<br/>page PNG + highlight"]
    end
    subgraph "Calculation  (app/calc) - pure Decimal code"
      UN[units.py]
      QTY[quantity.py]
      PRO[prorate.py]
      FAC[factors.py]
      ENG[engine.py]
      SVC["service.py<br/>DB glue"]
    end
    subgraph "Infrastructure"
      ORM["(SQLAlchemy models<br/>+ Alembic)"]
      STO["storage.py<br/>Local / S3"]
      AUD[audit.py]
      CFG[config.py]
      SEC[security.py]
    end

    R2 --> Q --> RUN --> TXT & LLM & VAL
    RUN --> SVC
    R2 --> REV --> VAL
    REV --> SVC
    SVC --> ENG --> UN & QTY & PRO & FAC
    R3 --> DASH & REP
    REP --> STO
    RUN & REV & SVC & R1 --> AUD
    R1 & R2 & R3 --> ORM
    RUN --> STO
```

Layering rules that keep the code testable:

- **`app/calc/engine.py`, `factors.py`, `prorate.py`, `quantity.py`, `units.py` never touch the
  database.** They take plain dataclasses and return plain dataclasses. Only `calc/service.py`
  loads/stores rows.
- **`pipeline/validate.py` is pure.** Everything it needs from the database (account mapping,
  overlapping bills, usage history) is gathered by `runner.build_context()` into a
  `ValidationContext` and passed in.
- **The LLM is behind a one-method interface** (`Extractor.extract(text, correction) -> str`), so tests
  inject a scripted fake.
- **Storage is behind an interface** (`save`, `save_file`, `read`).

---

## 3. Request lifecycle

```mermaid
sequenceDiagram
    participant B as Browser
    participant F as FastAPI
    participant D as deps.py
    participant S as Session (get_db)
    participant DB as Database

    B->>F: GET /api/bills  (Authorization: Bearer JWT)
    F->>D: get_current_user
    D->>D: decode JWT (HS256, require sub+exp)
    D->>S: open Session
    D->>DB: SELECT app_user WHERE id = sub
    D-->>F: User (401 if missing/inactive)
    F->>DB: query scoped by user.org_id
    F-->>B: JSON (Pydantic response_model)
    Note over S: Session closed in finally
```

- One SQLAlchemy `Session` per request (`db.get_db` generator dependency), closed when the request ends.
- Handlers `commit()` explicitly; if a handler raises, nothing is committed. The audit row is added to
  the same session, so **a change and its audit record commit or roll back together**.
- Admin-only routes depend on `AdminUser` (`require_admin`), returning 403 for members.
- CORS: `CORSMiddleware` allows any origin without credentials. This is safe because auth is a Bearer token
  in the `Authorization` header, never a cookie. It exposes `X-Page-Count`/`X-Highlight` so the browser can read them.

---

## 4. Bill processing pipeline

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant API as POST /bills/upload
    participant ST as Storage
    participant DB as Database
    participant Q as JobQueue (3 threads)
    participant W as process_bill
    participant T as text.py
    participant L as LangChainExtractor
    participant O as Gemini
    participant V as validate.py
    participant C as calc/service.py

    B->>API: multipart: facility_id + PDFs
    loop each file
      API->>API: check .pdf, size, %PDF- magic, SHA-256
      API->>DB: duplicate? (org_id, file_hash)
      API->>ST: save bills/<org>/<hash>.pdf
      API->>DB: INSERT bill(status=uploaded) + audit
    end
    API->>DB: COMMIT
    API->>Q: enqueue(bill_id) for each new bill
    API-->>B: per-file outcomes (queued / duplicate / rejected)

    Q->>W: run in a worker thread
    W->>DB: status = processing (own Session)
    W->>ST: read PDF bytes
    W->>T: extract_text()
    T-->>W: pages[] (OCR for pages with no text layer)
    W->>L: extract_structured(prompt)
    L->>O: ChatGoogleGenerativeAI.invoke(system+human), JSON mode
    O-->>L: JSON text
    L-->>W: LLMExtraction (Pydantic, Decimal)
    W->>V: validate(extraction, pages, context)
    V-->>W: issues[], canonical unit
    W->>DB: INSERT extraction (older ones is_current=false)
    alt no issues
      W->>DB: bill.status = approved (audit actor=system)
      W->>C: calculate_bill()
      C->>DB: INSERT emission_record(s)
    else any issue
      W->>DB: bill.status = needs_review
    end
    loop every 2 s while open
      B->>API: GET /bills/status?ids=...
    end
```

Details worth knowing:

- **The request returns before any AI work.** Upload only stores files and rows. The browser polls a
  lightweight status endpoint.
- **Idempotent claim.** `process_bill` returns immediately unless the bill is `uploaded`/`processing`,
  so a bill is never processed twice by accident.
- **Separate sessions.** The worker opens short sessions: one to mark `processing` (committed before the
  slow LLM call so the UI sees it), another to store the result. No DB transaction is held open during
  the LLM call.
- **Restart recovery.** On startup (`lifespan` in `main.py`) every `uploaded`/`processing` bill is reset to
  `uploaded` and re-enqueued.
- **Failure isolation.** `process_bill` catches `PipelineError` (readable message) and any other exception
  (logged with a reference id, generic message) and marks only that bill `failed`.

---

## 5. Bill state machine

```mermaid
stateDiagram-v2
    [*] --> uploaded: upload accepted
    uploaded --> processing: worker claims it
    processing --> approved: all checks pass (system)
    processing --> needs_review: any validation issue
    processing --> failed: unreadable / LLM down / error
    needs_review --> approved: reviewer approves
    needs_review --> rejected: reviewer rejects (reason)
    needs_review --> uploaded: reprocess
    failed --> uploaded: reprocess
    approved --> needs_review: admin reopens (reason)
    rejected --> needs_review: admin reopens (reason)
    approved --> approved: recalculation (records versioned)
```

Only `approved` bills have current `emission_record`s. Moving a bill out of `approved` (reopen) or into
`rejected` calls `calculate_bill`, which **retires** the bill's records (`is_current=false`), so totals drop
immediately and consistently.

---

## 6. The LLM extraction layer

```mermaid
flowchart TD
    A["document text<br/>=== PAGE n === blocks"] --> B{"length ><br/>60,000 chars?"}
    B -- yes --> X1["ExtractionError:<br/>refuse, never truncate"]
    B -- no --> C["SystemMessage: clerk rules<br/>HumanMessage: bill text<br/>+ correction if retry"]
    C --> D["ChatGoogleGenerativeAI.invoke<br/>temperature 0<br/>JSON mode + schema in prompt"]
    D -->|exception| E{classify}
    E -- "404 model missing" --> X2["ExtractionError:<br/>'model not available'"]
    E -- "other, attempts left" --> F["sleep 2s, 4s, 8s<br/>retry"]
    F --> D
    E -- "attempts exhausted" --> X3["ExtractionError:<br/>cannot reach model"]
    D -->|text| G{empty?}
    G -- yes --> X4[ExtractionError: empty]
    G -- no --> H[json.loads with parse_float=Decimal]
    H --> I["Pydantic LLMExtraction<br/>extra=forbid"]
    I -->|valid| OK([ExtractionResult])
    I -->|invalid, attempt 1| J[describe error] --> C
    I -->|invalid, attempt 2| X5["ExtractionError:<br/>'invalid data twice'"]
```

Why this design:

- **Two independent retry loops.** The inner loop (in `LangChainExtractor.extract`) handles *transport*
  problems. The outer loop (`extract_structured`) handles *content* problems: it re-asks once and passes
  the exact validation errors back to the model.
- **JSON mode + schema in the prompt.** Gemini runs with `response_mime_type=application/json` and the schema
  is included in the prompt, which sharply reduces malformed output (Pydantic still validates and retries once). The schema is hand-maintained (flat,
  no `$ref`) because providers support only a subset of JSON Schema; a unit test asserts it matches the
  Pydantic model field-for-field.
- **Exact decimals.** `json.loads(..., parse_float=Decimal)` means `1234.56` never passes through a binary
  float. Reviewer input is sent as strings for the same reason.
- **Prompt discipline.** The model is told to copy, not compute. If only meter readings are printed it
  must leave `quantity` null; the arithmetic happens in `calc/quantity.py`.

---

## 7. Validation engine

```mermaid
flowchart LR
    X[LLMExtraction] --> L1
    subgraph "validate()  - model-level"
      L1["confidence >= 0.85?"]
      L2["multiple meters / estimated / notes?"]
      L3[snippet exists on cited page?]
      L4[printed quantity appears in snippet?]
      L5[meter readings appear on page?]
    end
    X --> F
    subgraph "validate_fields()  - field-level (re-run after human edits)"
      F1[utility known?]
      F2[unit canonical, allowed, matches utility?]
      F3[period present, ordered, <= 95 d, not future?]
      F4["quantity > 0 / meter math / rollover?"]
      F5[account mapped to this facility?]
      F6[overlaps another bill?]
      F7[daily usage vs facility median 3x?]
    end
    L1 & L2 & L3 & L4 & L5 --> ISS[issues list]
    F1 & F2 & F3 & F4 & F5 & F6 & F7 --> ISS
    ISS -->|empty| AP[auto-approve]
    ISS -->|not empty| NR[needs_review]
```

- Each issue is `{code, message, field}`. Codes are split into **BLOCKING** (cannot calculate: reviewer
  must fix) and warnings (acknowledged on approval), and into **LLM_LEVEL** codes (about how the model
  read the PDF; stored once, kept as history) vs field codes (recomputed after every correction).
- `ValidationContext` carries DB-derived facts: the facility an account is mapped to, IDs of overlapping
  bills (period intersection `a.start <= b.end and b.start <= a.end`), and `HistoryPoint`s (quantity, unit,
  days) of earlier approved bills for the outlier median.
- **Outlier maths:** every historic bill is converted to a base unit (MJ for energy, m³ for volume), divided
  by its days to get a daily rate; the new bill's daily rate divided by the median must lie within
  `[1/3, 3]`. Needs at least 3 comparable bills.
- **Hallucination guard:** `_normalize` collapses whitespace and lowercases; the snippet must be a
  substring of the cited page. `_numbers_in` extracts numbers (commas stripped, as `Decimal`) and the
  extracted quantity must be among them.

---

## 8. Review workflow and concurrency control

```mermaid
sequenceDiagram
    participant R as Reviewer (browser)
    participant API as /extractions/{id}/approve
    participant RV as review.py
    participant V as validate_fields
    participant CS as calc/service
    participant DB as Database

    R->>API: changes{...}, expected_updated_at, remap_account?, note
    API->>RV: load_for_review()
    RV->>DB: SELECT extraction, bill (org check)
    RV-->>API: 409 if extraction not current or bill.updated_at != expected
    API->>RV: apply_corrections()
    RV->>DB: update fields; corrections_json keeps ORIGINAL 'before'
    RV->>V: revalidate (keeps LLM-level issues)
    API->>RV: approve()
    RV->>V: revalidate again
    alt blocking issue
      RV-->>R: 422 with the blocking issues
    else account belongs to another facility and not confirmed
      RV-->>R: 409 account_other_facility
    else ok
      RV->>DB: upsert facility_account mapping
      RV->>DB: bill.status=approved, reviewed_by/at, audit(acknowledged_issues)
      RV->>CS: calculate_bill()
    end
    API->>DB: COMMIT (correction + approval + calculation atomically)
```

**Optimistic concurrency:** the client sends the `updated_at` it loaded. If another reviewer changed the
bill meanwhile, the server returns 409 "reload" rather than overwriting. This avoids row locks and keeps
long reviews safe.

**Provenance of corrections:** `corrections_json[field] = {before: <what the AI read>, after: <latest>}`;
if a field is corrected back to the AI's original value, the entry is removed. Each change is also an
audit row with the reviewer and reason.

---

## 9. Calculation engine

```mermaid
flowchart TD
    IN["CalcInput:<br/>utility, region, period, unit,<br/>quantity or meter readings, org, FY month"]
    IN --> Q["effective_quantity<br/>printed total OR (cur - prev) x multiplier"]
    Q --> Z{"value > 0?"}
    Z -- no --> ERR[CalculationError]
    Z -- yes --> SP["split_period:<br/>cut at each month start<br/>+ factor validity boundaries"]
    SP --> LOOP
    subgraph LOOP[for each segment]
      SEL[select_factor on segment start]
      SEL --> CHK{"factor covers whole segment<br/>and scope matches utility?"}
      CHK -- no --> ERR
      CHK -- yes --> SQ["segment qty = total x seg_days / period_days"]
      SQ --> CV[x unit conversion to factor unit]
      CV --> MUL["x kgCO2e per unit<br/>(34-digit precision)"]
      MUL --> RND[round once: 6 dp, half-even]
      RND --> TR[build JSON trace]
    end
    LOOP --> OUT[CalcResult: list of SegmentResult]
```

Key properties:

- **Types:** all inputs are `Decimal`; `calculate()` raises `TypeError` on floats. Context precision is 34
  significant digits for intermediate values; results are quantized to `0.000001` kg (1 mg) with
  `ROUND_HALF_EVEN`. Day fractions are stored to 12 decimals but the *math uses exact `days/total`*, not the
  rounded fraction.
- **Why split on months:** each emission record then belongs to exactly one month and one reporting year, so
  dashboard sums by month/year are exact and a period boundary never cuts a record. Splitting also at factor
  validity boundaries means a bill straddling two factor editions uses each factor for the right days.
- **Scope:** electricity → 2 (location-based), natural gas → 1; the factor's scope must agree.
- **Trace:** each segment stores quantity (with source `printed`/`meter_readings`), allocation (fraction,
  method, reporting year), normalization (multiplier + the constants' definitions), the complete factor
  record (key, version, source, derivation), a human-readable formula string, and the result. A reviewer or
  auditor can recompute it by hand.

**Worked example** - Pune plant, 16 Mar to 15 Apr 2024, 12,400 kWh printed (illustrative):

| Segment | Days | Quantity | Factor | kg CO2 |
|---|---|---|---|---|
| 16-31 Mar (FY2023-24) | 16 | 12,400 × 16/31 = 6,400 kWh = 6.4 MWh | 727 kg/MWh | 4,652.8 |
| 1-15 Apr (FY2024-25) | 15 | 12,400 × 15/31 = 6,000 kWh = 6.0 MWh | 710 kg/MWh | 4,260.0 |

Two `emission_record`s; the FY2023-24 report contains only the first.

---

## 10. Emission-factor selection

```mermaid
flowchart TD
    S([select_factor]) --> A["Keep factors: same utility,<br/>not superseded,<br/>global OR this org's"]
    A --> B{"any factor for the<br/>EXACT region?"}
    B -- yes --> R1[use exact region]
    B -- no --> C{"parent region exists<br/>(US-CAMX -> US) with factors?"}
    C -- yes --> R2[use parent region]
    C -- no --> E1["Error: no factor for region"]
    R1 & R2 --> D{"any factor valid<br/>on the date?"}
    D -- no --> E2["Error: lists available periods;<br/>never substitutes another year"]
    D -- yes --> O{"org-owned factors<br/>among them?"}
    O -- yes --> P1[pool = org factors]
    O -- no --> P2[pool = global factors]
    P1 & P2 --> U{"unit convertible<br/>(same dimension)?"}
    U -- none --> E3["Error: e.g. m3 bill vs energy factors"]
    U -- some --> X{"exactly one after<br/>preferring exact unit?"}
    X -- no --> E4["Error: ambiguous"]
    X -- yes --> OK([Selection])
```

The principle is **fail loudly rather than guess**. An approved bill that hits one of these errors is stored
with `calculation_error`, contributes nothing, and is counted in the dashboard's completeness banner until a
factor is added and recalculation runs.

---

## 11. Recalculation and immutability

```mermaid
flowchart TD
    T["Trigger:<br/>approve / auto-approve /<br/>factor added or versioned /<br/>seed loaded / admin 'recalculate'"] --> CB[calculate_bill]
    CB --> S{"bill approved<br/>and has extraction?"}
    S -- no --> RT["retire any current records,<br/>clear calculation_error"]
    S -- yes --> CALC[run engine]
    CALC -->|CalculationError| FAIL["retire stale records,<br/>store calculation_error,<br/>audit calculation_failed"]
    CALC -->|result| CMP{"same (factor, dates, kg)<br/>as current records?"}
    CMP -- yes --> NOOP[unchanged: write nothing]
    CMP -- no --> NEW["mark old is_current=false,<br/>insert new records with trace,<br/>audit calculate / recalculate"]
```

Records and factors are **append-only**: nothing is edited or deleted. History stays queryable
(`GET /bills/{id}/trace` returns `superseded_records`). The no-op comparison makes the operation idempotent,
so running "recalculate" repeatedly is safe and doesn't spam the audit log.

---

## 12. Database schema

```mermaid
erDiagram
    ORGANIZATION ||--o{ APP_USER : has
    ORGANIZATION ||--o{ FACILITY : owns
    ORGANIZATION ||--o{ BILL : owns
    ORGANIZATION ||--o{ REPORT : owns
    ORGANIZATION ||--o{ EMISSION_FACTOR : "optional own factors"
    FACILITY ||--o{ BILL : receives
    FACILITY ||--o{ FACILITY_ACCOUNT : "account numbers"
    APP_USER ||--o{ BILL : uploads
    BILL ||--o{ EXTRACTION : "versions of reading"
    EXTRACTION ||--o{ EMISSION_RECORD : yields
    EMISSION_FACTOR ||--o{ EMISSION_RECORD : used_by
    EMISSION_FACTOR ||--o| EMISSION_FACTOR : superseded_by
    AUDIT_LOG }o--|| ORGANIZATION : scoped_to

    ORGANIZATION {
      uuid id PK
      string name
      string reporting_framework
      string default_region
      int fiscal_year_start_month
    }
    BILL {
      uuid id PK
      uuid org_id FK
      uuid facility_id FK
      string file_hash "unique with org_id"
      string status
      string failure_reason
      string calculation_error
    }
    EXTRACTION {
      uuid id PK
      uuid bill_id FK
      bool is_current
      date billing_period_start
      date billing_period_end
      numeric quantity
      string unit
      json validation_issues_json
      json corrections_json
    }
    EMISSION_FACTOR {
      uuid id PK
      string factor_key "unique with version"
      int version
      uuid org_id "null = global"
      string region
      numeric kgco2e_per_unit
      date valid_from
      date valid_to
    }
    EMISSION_RECORD {
      uuid id PK
      uuid extraction_id FK
      uuid emission_factor_id FK
      bool is_current
      date allocation_start
      date allocation_end
      numeric kgco2e
      json calculation_trace_json
    }
```

- **Portable types** (`models/base.py`): `JSON` that becomes `JSONB` on Postgres; `Numeric(20,6)` for
  quantities/kg and `Numeric(24,12)` for factors; UUID primary keys generated in Python.
- **Constraints that encode rules:** `uq_bill_org_hash` (a file can be uploaded once per org),
  `uq_factor_key_version`, `uq_facility_org_name`, `uq_facility_account (org, utility, account)`.
- **Migrations:** Alembic (`0001` schema, `0002` `bill.calculation_error`, `0003` report hashes + draft flag).
  A test fails if models drift from migrations. The service runs `alembic upgrade head` on every start.
- **SQLite vs Postgres:** tests and local dev use SQLite (foreign keys enabled by a connection event);
  production uses Postgres (`pool_pre_ping=True`). `DATABASE_URL` normalisation converts `postgres://` and
  `postgresql://` to `postgresql+psycopg://` (psycopg v3).

---

## 13. Report generation and verification

```mermaid
flowchart LR
    subgraph Generate
      A["approved + current records<br/>in the period"] --> B["build_snapshot<br/>dict of strings, no floats"]
      B --> C["canonical JSON<br/>sorted keys, compact"]
      C --> H1["(snapshot SHA-256)"]
      B --> D["render_pdf<br/>ReportLab + matplotlib<br/>deterministic"]
      D --> H2["(PDF SHA-256)"]
      D --> ST["(storage reports/org/id.pdf)"]
      B & H1 & H2 --> DB["(report row)"]
    end
    subgraph Verify
      V1["read stored PDF -> hash == pdf_sha256?"]
      V2[hash stored snapshot == snapshot_sha256?]
      V3["re-render PDF from stored snapshot<br/>== pdf_sha256?"]
    end
    DB --> V1 & V2 & V3
```

- **Snapshot-first design:** the PDF is a pure function of the snapshot. Live data is read once, at generation.
- **Determinism:** `canonical_json` uses sorted keys and fixed separators; ReportLab runs with
  `invariant=1` (no timestamps/random ids); matplotlib is configured with a fixed hash salt and no date
  metadata. So `render_pdf(snapshot)` produces identical bytes, which is what makes the third check meaningful.
- **Draft logic:** `status_counts` finds bills that may belong to the period but aren't included. If any,
  the report is a `DRAFT` (watermark, cover text, `-DRAFT` filename).
- **Pinned libraries:** byte-identical rendering assumes the same ReportLab/matplotlib versions, which is
  why `requirements.txt` pins exact versions.

---

## 14. Authentication and multi-tenancy

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as /auth
    participant DB as DB
    B->>A: POST /register {org, email, password, ...}
    A->>DB: INSERT organization, app_user(role=admin, bcrypt hash)
    A-->>B: {access_token}
    B->>B: store token in localStorage
    B->>A: POST /login
    A->>DB: find user by lowercase email
    A->>A: bcrypt verify (dummy hash if user unknown)
    A-->>B: JWT {sub=user id, org, iat, exp=+8h}
    Note over B,A: every later call sends Authorization: Bearer
```

- **JWT**: HS256, signed with `JWT_SECRET`. If unset, a 48-byte random secret is generated once and saved to
  `<STORAGE_DIR>/.jwt_secret` (mode 0600 where supported). On a read-only filesystem it falls back to a
  per-process secret (logins end on restart).
- **Passwords**: bcrypt with per-hash salt; ≥10 characters enforced by the request model.
- **Tenant isolation is by query scoping, not by URL secrecy.** Every router filters by `user.org_id`
  (`get_org_bill`, `get_org_facility`, …); a foreign id yields 404 so existence isn't leaked.
- **Roles:** `admin` vs `member` via `require_admin`. The first user of an organization is an admin.

---

## 15. Storage

`storage.py` defines `Storage` with `save(org_id, hash, bytes)`, `save_file(key, bytes)`, `read(key)`.

- **Keys are generated server-side** from a UUID and a hex digest (`bills/<org>/<hash>.pdf`,
  `reports/<org>/<report>.pdf`); `_check_key` rejects absolute paths, backslashes, control characters and
  `..` segments, and `LocalStorage` additionally verifies the resolved path stays under its root.
- **Content-addressed bills:** the key contains the SHA-256, so identical bytes map to the same object.
- **`LocalStorage`** writes under `STORAGE_DIR`; **`S3Storage`** (boto3, path-style addressing, 5 retries)
  works with AWS S3, MinIO and Supabase Storage. Buckets must stay private; files are only served via the API.

---

## 16. Frontend architecture

```mermaid
flowchart TD
    M["main.jsx<br/>BrowserRouter + AuthProvider"] --> RA{RequireAuth}
    RA -- no token/me --> LOGIN["login /register"]
    RA -- ok --> LAY["Layout: nav, review badge,<br/>30 s polling of /review/counts"]
    LAY --> P1[Dashboard - lazy loaded]
    LAY --> P2[Upload]
    LAY --> P3[Review queue] --> P3b[Review bill]
    LAY --> P4[Bills] --> P4b[Bill detail]
    LAY --> P5[Reports]
    LAY --> P6[Facilities]
    LAY --> P7[Emission factors]
    P1 & P2 & P3 & P3b & P4 & P4b & P5 & P6 & P7 --> CL["api/client.js"]
    CL -->|"fetch(VITE_API_URL + /api/..)<br/>+ Bearer token"| BE["(Backend)"]
```

- **State:** local React state + `useEffect` fetches; no global store beyond `AuthProvider` (current user/org).
- **`api/client.js`** centralises base URL, the `Authorization` header, JSON/FormData handling, and an
  `ApiError` that formats FastAPI's string or validation-error list. `fetchBlobUrl`/`fetchPage` fetch PDFs/PNGs
  with the token and turn them into object URLs (an `<iframe>` can't send headers).
- **Dev vs prod:** in dev, Vite proxies `/api` to `localhost:8000` (so `VITE_API_URL` is empty). In production
  the build is static and `VITE_API_URL` is baked in at build time.
- **Performance:** Recharts is code-split (`React.lazy`) so only the dashboard downloads it.
- **Precision:** the UI never does emission maths; it displays strings the server already rounded, and sends
  edited numbers back as strings.

---

## 17. Concurrency, transactions and failure handling

| Concern | Mechanism |
|---|---|
| Slow AI calls blocking requests | Upload returns immediately; `ThreadPoolExecutor(3)` processes bills. |
| Limiting LLM load | Pool size = max concurrent LLM calls (`EXTRACTION_WORKERS`). |
| Double processing | `process_bill` only acts on `uploaded`/`processing` bills. |
| Server restart mid-job | Startup re-queues unfinished bills. |
| One bad bill | Errors caught per bill → `failed` + reason; others continue. |
| LLM down | 4 attempts with backoff, then a readable failure; **Reprocess** later. |
| Atomic changes | Domain change + audit row share one transaction; handlers commit once. |
| Two reviewers, one bill | Optimistic check on `updated_at` → 409. |
| Duplicate uploads | SHA-256 + unique constraint `(org_id, file_hash)`. |
| Stale numbers in totals | Retire-and-replace of records, never edit in place. |
| Float error | `Decimal` end-to-end; strings in JSON and the snapshot. |
| Tampering with reports | Snapshot + PDF hashes and byte-identical re-render. |

Limitation: the queue is in-process memory, which is correct for **one** API instance. With several
instances you would add a shared broker (Redis + RQ/Celery); `JobQueue.enqueue` is the only call site to change.

---

## 18. Deployment topology

```mermaid
flowchart TB
    subgraph Developer
      GH["(GitHub repo)"]
    end
    GH -->|"frontend/ (root dir)"| VC["Vercel build:<br/>npm run build -> dist"]
    GH -->|"render.yaml blueprint"| RD[Render]
    subgraph RD[Render]
      WS["Web service<br/>pip install -r requirements.txt<br/>alembic upgrade head<br/>python -m app.seed<br/>uvicorn app.main:app --port $PORT"]
      PG["(Render Postgres)"]
      DK["(Persistent disk /var/data<br/>or S3 bucket)"]
      WS --> PG
      WS --> DK
    end
    VC -->|static SPA| USER([Browser])
    USER -->|"HTTPS API calls<br/>CORS open to all origins"| WS
    WS -->|"GOOGLE_API_KEY"| OLL["Google Gemini API"]
```

Environment configuration at a glance:

| Where | Variable | Purpose |
|---|---|---|
| Vercel | `VITE_API_URL` | Backend origin baked into the frontend build. |
| Render (auto) | `DATABASE_URL`, `JWT_SECRET`, `PYTHON_VERSION`, `STORAGE_DIR` | From `render.yaml`. |
| Render (you) | `GOOGLE_API_KEY` | Your Gemini key. |
| Optional | `STORAGE_BACKEND=s3` + `S3_*` | Durable storage on the free tier. |

There is no `.env` file anywhere and no LLM API key; configuration is code defaults plus platform variables.

---

## 19. Design decisions and trade-offs

| Decision | Reason | Cost / alternative |
|---|---|---|
| LLM only extracts; code calculates | Reproducible, auditable maths; the model can't silently change a total. | Needs a strict schema and validation layer. |
| Everything uncertain goes to human review | Safer than trusting the model. | More review work with a weaker model. |
| Validation that the quote exists on the page | Cheap, strong defence against hallucinated numbers. | OCR layout differences can trigger review. |
| Append-only records & factors | Full history; old reports stay explainable. | More rows; queries filter `is_current`. |
| Split bills at month and factor boundaries | Exact monthly/yearly totals, correct factor per day. | Assumes uniform daily consumption. |
| Fail instead of guessing a factor/unit | No silent wrong numbers. | Needs factor data kept up to date. |
| `Decimal` and strings everywhere | No float drift between UI, DB, PDF. | Slightly more code. |
| Snapshot-first, deterministic PDF + hashes | Verifiable, tamper-evident reports. | Pinned library versions. |
| In-process thread-pool queue | Simple, no extra infra for one instance. | Not horizontally scalable without a broker. |
| Gemini via LangChain | Nothing to host, strong accuracy, and vision doubles as OCR; swap models by name. | Needs an API key; free tier is rate-limited (the app spaces its calls). |
| SQLite for tests, Postgres for prod | Fast tests, no setup. | Dialect differences must be watched (portable types used). |
| Static SPA on Vercel + API on Render | Cheap, independent scaling and deploys. | Two deployments (CORS is open, since auth is a header token). |
