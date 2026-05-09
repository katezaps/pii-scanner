# Roadmap

## v0 — local scanning

- One agent per broker, fanned out concurrently with timeouts
- Headless Playwright with isolated contexts per scan
- Two tools: `discover_forms` and `submit_form` (PII matched in-process, response bodies never leave the tool)
- FastAPI service with SSE streaming, HttpOnly cookie auth, single token per user
- Consent-required persistence (`save: bool`, default-off, server-enforced)
- Only `(broker, field_type, found_boolean)` stored — identity values never persisted
- Per-broker scan state with pre-emption on new submissions
- Configurable retention with manual delete and orphan purge
- React frontend for scans, brokers, results
- Local-first CLI bypassing auth, persistence, and retention
- PR-curated broker registry as JSON
- PII scrubbing on logs as defense in depth

## v1 — opt-out playbooks

- Per-broker opt-out metadata in the registry (URL, method, processing window)
- Scan results include the listing URL where PII was found
- Generated opt-out playbook per broker: deep links, mailto fallback, instructions for ID/notarization/postal cases
- Saved playbooks viewable from prior scans
- Authorized contributors can submit registry updates via API

## v2 — scheduled work

- Postgres-backed job queue (`SELECT ... FOR UPDATE SKIP LOCKED`)
- Background worker process, separate from the API
- Scheduled re-scans with diff-based reporting (new vs. removed)
- Verification loop for v1 opt-outs after broker-stated processing windows
- Multi-step opt-out tracking (email confirmation, postal follow-up)
- Per-user notification preferences

## v3 — automated opt-out submission

- Agent submits opt-out forms for brokers with self-service web flows
- Per-broker explicit consent — no bulk submission
- Pre-submission preview with irreversibility warnings where applicable
- Submission outcomes classified by the agent; verification deferred to v2's re-scan loop
- Per-submission audit record (broker, timestamp, outcome, confidence)
- Allowlisted submit-button selectors to bound agent authority
- Manual fallback to the v1 playbook when the agent can't classify