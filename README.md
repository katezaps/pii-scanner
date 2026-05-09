# pii-scanner

An open-source data broker auditor. Uses AI agents to scan US data broker
sites, discover what personal information they accept, and detect whether
your data appears in their results.

**Status:** v0 — local scanning tool with agent-based PII detection. No
opt-out automation yet.

## Privacy posture

- No PII is stored in the database. Only detection results (`found: true/false`)
  are persisted — never the identity values themselves.
- The `submit_form` agent tool checks broker response bodies for PII matches
  internally and returns only boolean results. Response bodies are never
  returned, logged, or stored.
- Scan history retention is bounded (default 30 days) and configurable.
- A consent modal explains data submission before any PII leaves the server.
- Log scrubbing (`PIIScrubFilter`) redacts email, phone, and SSN patterns
  as defense-in-depth.

See `THREAT_MODEL.md` for what this protects against and what it does not.

---

## Booting up the service

### Prerequisites

Docker, Python 3.11+, Node.js 18+, and `make`. Playwright Chromium is
installed automatically (`playwright install chromium` after `pip install`).

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

- `POSTGRES_PASSWORD` — any non-empty string for local dev
- `OPENAI_API_KEY` — required for agent-based scanning

### 2. Start Postgres

```bash
docker compose up -d postgres
```

Postgres binds to `127.0.0.1:5432` only.

### 3. Install dependencies

```bash
make install
```

This creates a `.venv` Python virtual environment, installs backend
dependencies (including dev extras), and runs `npm install` for the
frontend.

All `make` targets use the venv automatically — no activation needed.
If you need to run Python commands directly (outside of `make`), activate
it first:

```bash
source .venv/bin/activate
```

### 4. Apply migrations and seed the broker list

```bash
make migrate
make seed
```

### 5. Start the application

**Backend** (terminal 1):

```bash
make dev
```

The API server runs at `http://127.0.0.1:8000`. Swagger UI is at `/docs`
in development mode.

**Frontend** (terminal 2):

```bash
cd frontend
npm run dev
```

The frontend runs at `http://localhost:5173`. Open it and sign up for an
account.

### 6. Smoke test (API only)

```bash
curl http://127.0.0.1:8000/health

# Log in (sets an httponly cookie)
curl -c cookies.txt -X POST http://127.0.0.1:8000/login \
  -H "Content-Type: application/json" \
  -d '{"name": "youruser", "password": "yourpass"}'

curl -b cookies.txt http://127.0.0.1:8000/me

curl -b cookies.txt http://127.0.0.1:8000/brokers
```

To run a scan:

```bash
curl -N -b cookies.txt -X POST http://127.0.0.1:8000/audit \
  -H "Content-Type: application/json" \
  -d '{
    "broker_keys": ["spokeo"],
    "save": true,
    "email": "you@example.com",
    "name": "Your Name"
  }'
```

Results stream as Server-Sent Events. To retrieve saved results:

```bash
curl -b cookies.txt http://127.0.0.1:8000/fetch
```

---

## Docker full-stack

```bash
make up
```

Builds the app image, starts Postgres and the application server, applies
migrations, and seeds brokers. Available at `http://127.0.0.1:8000`.

To stop: `make down`.

---

## Running the test suite

Tests require a running Postgres with migrations applied and brokers seeded.

```bash
make test
```

The suite covers agent parsing, PII matching, scan persistence, endpoint
auth, broker listing, scan streaming, naming collision, and a core privacy
test that asserts no plaintext PII appears anywhere in the database after
a scan.

---

## Endpoints

All endpoints (except `/health`, `/login`, `/signup`) require an
authenticated session (httponly cookie set by `/login`).

| Method | Path       | Purpose                                     |
|--------|------------|---------------------------------------------|
| POST   | `/signup`  | Create account with password                 |
| POST   | `/login`   | Authenticate and set httponly session cookie  |
| GET    | `/me`      | Verify session and return user info          |
| POST   | `/logout`  | Clear auth cookie                            |
| GET    | `/brokers` | Active brokers (highest version)             |
| POST   | `/audit`   | Stream agent scan results (SSE)              |
| GET    | `/fetch`   | Retrieve most recent saved scan              |
| GET    | `/fetch/scans` | List all unexpired scans for the user    |
| GET    | `/health`  | Liveness check (no auth)                     |

---

## User flow

```
Login ──> Audit Page ──> Results Page
  │           │
  │     ┌─────┴──────────────────────┐
  │     │                            │
  │     ▼                            ▼
  │  Select Brokers           View Saved Scans
  │     │                        │
  │  Enter PII (optional)     Expand Scan
  │     │                        │
  │  Set Save / Name          Expand Broker
  │     │                        │
  │     ▼                     See field results
  │  ┌─ Has PII? ─┐
  │  │ yes         │ no
  │  ▼             │
  │  Consent       │
  │  Modal ────────┤
  │  │ confirm     │
  │  ▼             ▼
  │  Name conflict? ──yes──> Show error, stop
  │  │ no
  │  ▼
  │  POST /audit (SSE stream)
  │     │
  │     ├── "started" → show broker list
  │     ├── "result"  → update broker row
  │     ├── "done"    → scan complete
  │     └── "error"   → show error
  │
  └──> Logout ──> Clear cookie
```

## Scan state management

```
scan_executions                  broker_field_scans
────────────────                 ──────────────────

  ┌─────────┐                     ┌─────────┐
  │ RUNNING │ (created on POST)   │ RUNNING │ (pre-created markers)
  └────┬────┘                     └────┬────┘
       │                               │
       ├── new scan by same user ──────┤──> CANCELLED
       │   (audit_cancel_running)      │
       │                               │
       │                               ├── agent succeeds ──> SUCCESS
       │                               │     found=true/false
       │                               │     message=null
       │                               │
       │                               ├── agent times out ──> SUCCESS
       │                               │     found=true/false (partial)
       │                               │     message="Completed at timeout."
       │                               │
       │                               ├── client disconnects ──> CANCELLED
       │                               │     message="Cancelled."
       │                               │
       │                               └── agent error ──> FAILED
       │                                     message=<error string>
       │
       ├── all brokers done ──> SUCCESS
       │
       └── any broker missing ──> CANCELLED
```

## CLI — `pii-scanner`

A standalone command-line scanner that bypasses the web application
entirely. No database, authentication, persistence, or retention — just
a direct scan against broker sites using the OpenAI agents layer.
Reads the broker list from the installed `share/pii-scanner/brokers.json`
(packaged via `data-files` in `pyproject.toml`). Loads `.env.cli` from
the current working directory.

### Prerequisites

Python 3.11+ and an OpenAI API key. No Docker or Postgres required.

### Installation

```bash
# From the project root
make install-cli

# Create and configure .env.cli
cp .env.cli.example .env.cli
# Edit .env.cli and set OPENAI_API_KEY
```

This creates a `.venv` virtual environment and installs the `pii-scanner`
command into it. Activate the venv to use the CLI:

```bash
source .venv/bin/activate
```

### Usage

```bash
# List supported brokers
pii-scanner brokers list

# Scan all brokers for an email and name
pii-scanner scan --email you@example.com --name "Your Name"

# Scan specific brokers only
pii-scanner scan --email you@example.com --broker spokeo --broker radaris

# All identity options
pii-scanner scan --email EMAIL --phone PHONE --name NAME --address ADDRESS
```

At least one identity field (`--email`, `--phone`, `--name`, `--address`)
is required. If no `--broker` flags are given, all brokers are scanned.

A progress bar tracks broker completion during the scan. Once all brokers
finish, results are displayed sorted by category (violations first, then
clear, then incomplete), followed by a summary table.

### Consent prompt

Before every scan, the CLI displays a warning explaining that identity
fields will be submitted to third-party broker websites and requires
explicit confirmation (`y`/`yes`). This consent check cannot be bypassed
or suppressed — the tool submits real PII to external sites on the
user's behalf, and an unattended or scripted scan without informed
consent would be a misuse of the tool.

### Security note

The CLI intentionally bypasses the security controls present in the web
application (authentication, session management, PII scrubbing, scan
persistence, retention limits). It is designed for direct local use by
the operator, not as a service endpoint. PII values are passed to the
OpenAI agent prompt in plaintext and are not hashed, stored, or retained
after the process exits.

---

## Database management

```bash
make db-init    # start Postgres, create DB/user if missing, migrate + seed
make db-reset   # drop + recreate + migrate + seed (destroys all data)
```

---

## Contributing

Brokers are added via PR to `brokers/brokers.json`. Any change bumps the
broker version. See `CONTRIBUTING.md`.

---

## License

AGPL-3.0
