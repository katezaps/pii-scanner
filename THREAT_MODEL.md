# Threat model — v0

This document describes what `pii-scanner` v0 protects against and, more
importantly, what it does not. Update this document with each version.

## What v0 is

A locally-deployed FastAPI service that scans a curated list of US data
brokers for the user's identity fields and returns where matches were
found. Raw identity values are never stored — only field type labels
and boolean detection results are persisted. Identity fields leave the
process only during broker scan calls.

Tools use a headless Chromium browser (Playwright) to render
JavaScript-heavy broker pages. A concurrency semaphore (5 contexts)
limits memory usage.

## What v0 protects against

- **Database leak.** A copy of the Postgres database does not contain
  plaintext identity values (email addresses, phone numbers, etc.).
  Only field type labels (e.g. "email", "phone") and boolean detection
  results are stored.
- **Casual log inspection.** A filter scrubs PII-shaped strings from
  log output. This is defense in depth; primary control is not logging
  PII in the first place.
- **Cross-user data access on a multi-user deployment.** Each scan
  execution is owned by a user; retrieval requires a valid session
  (httponly cookie) whose owner matches the execution's owner.
- **Replay of stale scans.** Stored scan results expire after the
  configured retention window (default 30 days) and are purged.
- **Response body exposure.** The `submit_form` tool checks broker
  response bodies for PII matches in-process and returns only boolean
  results. The response body is never returned to the agent, logged,
  or stored. The `discover_forms` tool returns structured form metadata
  (field names, action URLs) — never raw HTML.
- **PII in streamed URLs.** URLs sent to the frontend in SSE events
  are scrubbed of query parameters to prevent PII leakage in the UI.

## What v0 does NOT protect against

- **A compromised host.** If an attacker has root on the machine running
  this service, they can read the environment, the database, the running
  process memory, and any in-flight identity fields. This is by design —
  a privacy tool is not a substitute for endpoint security.
- **A compromised broker.** When the service queries a broker's search
  endpoint, the user's identity fields are sent to that broker.
  Broker-side logging, breach, or surveillance is not in scope.
- **Network observers between this service and brokers.** TLS to the
  broker is required, but a sufficiently-positioned adversary may still
  observe metadata.
- **A compromised OpenAI API call.** The agent prompt includes raw
  identity values (via the `{input}` template variable) so that the
  agent can match form fields to user PII. These values are sent to
  OpenAI in plaintext as part of the agent's instructions. A
  compromised or subpoenaed OpenAI API would expose the identity
  fields submitted during scans.
- **Session cookie theft.** Whoever holds a valid session cookie can
  use the API. Cookies are httponly but not auto-rotating.
- **Login enumeration.** Login failures return an opaque "Denied."
  message with no distinction between wrong password and nonexistent
  user. This is intentional — but timing side channels may still leak
  whether an account exists.
- **Browser fingerprinting.** The headless Chromium instance uses a
  fixed User-Agent string. Broker sites may fingerprint the browser
  and block or track scans.

## CLI (`pii-scanner`)

The CLI is a separate entry point that intentionally bypasses most of
the security controls described above. This is safe because the CLI
runs as a local single-user process — there is no network service, no
shared state, and no persistence. The controls that the web application
needs (authentication, cross-user isolation, retention limits) exist to
protect a multi-user service with a database. The CLI has none of these:
it runs, prints results to the operator's terminal, and exits.

**What the CLI bypasses (and why it's safe to):**

- **Authentication.** No login, no session, no cookie. The operator
  already has shell access and the API key — there is no untrusted
  party to authenticate against.
- **Database persistence.** No results are written to Postgres. There
  is no stored data to protect — output lives only in the terminal
  and process memory for the duration of the run.
- **Log scrubbing.** The `PIIScrubFilter` is not active in the CLI
  code path. The operator is the only consumer of CLI output, and
  they already provided the PII.
- **Retention and expiry.** Nothing is stored, so there is nothing to
  expire or purge.
- **Cross-user isolation.** There is no concept of users — the CLI is
  a single-operator tool with no shared state.

**What the CLI preserves:**

- **Consent prompt.** Every scan requires interactive confirmation
  (`y`/`yes`) before identity fields are submitted to brokers. This
  cannot be bypassed or suppressed programmatically.
- **Broker-side exposure model.** The same `submit_form` tool is used,
  which checks response bodies for PII matches internally and never
  returns the response body. The broker still sees the search query.
- **OpenAI API exposure model.** The agent prompt includes identity
  values via `{input}`, identical to the web application. The same
  caveats about OpenAI API trust apply.
- **TLS to brokers.** All broker requests use HTTPS via Playwright's
  Chromium browser.
- **Timeouts.** The same per-broker and overall scan timeouts apply
  (configurable via `.env.cli`).

**Additional CLI risks:**

- **Shell history.** Identity values passed as command-line flags
  (`--email`, `--phone`, etc.) are recorded in shell history. Users
  should clear history or use environment variables if this is a
  concern.
- **Unattended use.** The consent prompt is the only gate. If an
  operator pipes `y` into stdin, the scan proceeds without meaningful
  human review. This is a deliberate trade-off — the tool submits
  real PII to third-party sites and should not be run without the
  operator's awareness.

## Reporting a vulnerability

Open a private security advisory on the GitHub repository. Do not file
public issues for security reports.
