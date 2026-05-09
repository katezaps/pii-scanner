import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import BrokerRow from "../components/BrokerRow";
import type { BrokerRowData } from "../components/BrokerRow";
import { compareBrokerResults } from "../sort";
import "./Audit.css";

interface Broker {
  key: string;
  name: string;
  search_url: string;
}

interface FormFieldMatch {
  identity_field: string;
  form_input: string;
  found: boolean | null;
}

interface AgentResult {
  name: string;
  search_url: string;
  status_code: number | null;
  content_length: number | null;
  message: string | null;
  input_fields_found: string[];
  matched_inputs: FormFieldMatch[];
}

interface PendingBroker {
  name: string;
  search_url: string;
}

interface AcceptedField {
  field_type: string;
  status: string;
}

interface IdentityFields {
  email: string;
  phone: string;
  name: string;
  address: string;
}

const CACHE_KEY = "pii-scanner-scan-cache";

interface ScanRun {
  id: number;
  name: string | null;
  pending: PendingBroker[];
  results: Record<string, AgentResult>;
  accepted: AcceptedField[];
}

interface ScanHistory {
  runs: ScanRun[];
  nextId: number;
}

function loadHistory(): ScanHistory {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return { runs: [], nextId: 1 };
    return JSON.parse(raw);
  } catch {
    return { runs: [], nextId: 1 };
  }
}

function stripPii(result: AgentResult): AgentResult {
  return {
    ...result,
    matched_inputs: result.matched_inputs.map((m) => ({
      ...m,
      form_input: m.form_input,
    })),
  };
}

function saveHistory(history: ScanHistory) {
  localStorage.setItem(CACHE_KEY, JSON.stringify(history));
}

function clearHistory() {
  localStorage.removeItem(CACHE_KEY);
}

function agentResultToRow(name: string, r: AgentResult): BrokerRowData {
  const wasCancelled = r.message === "Cancelled.";
  const isTimedOut = r.message === "Completed at timeout.";
  const hasError = !!r.message && !wasCancelled && !isTimedOut;
  const detected = r.matched_inputs.filter((m) => m.found === true);

  let state = "SUCCESS";
  if (wasCancelled) state = "CANCELLED";
  else if (hasError) state = "FAILED";

  return {
    name,
    state,
    message: r.message,
    fields: detected.map((m) => ({ field_type: m.identity_field, found: true })),
    foundCount: detected.length,
  };
}

export default function Audit() {
  const navigate = useNavigate();
  const { auth } = useAuth();
  const [brokers, setBrokers] = useState<Broker[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [identity, setIdentity] = useState<IdentityFields>({
    email: "",
    phone: "",
    name: "",
    address: "",
  });
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [pending, setPending] = useState<PendingBroker[]>([]);
  const [results, setResults] = useState<Map<string, AgentResult>>(new Map());
  const [accepted, setAccepted] = useState<AcceptedField[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [showConsent, setShowConsent] = useState(false);
  const [saveResults, setSaveResults] = useState(false);
  const [scanName, setScanName] = useState("");
  const [nameConflict, setNameConflict] = useState(false);
  const [resolvedScanName, setResolvedScanName] = useState<string | null>(null);
  const [pastRuns, setPastRuns] = useState<ScanRun[]>([]);
  const [expandedRun, setExpandedRun] = useState<number | null>(null);
  const [scanStartTime, setScanStartTime] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [scanComplete, setScanComplete] = useState(false);
  const [agentTimeoutSeconds, setAgentTimeoutSeconds] = useState<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const historyRef = useRef<ScanHistory>({ runs: [], nextId: 1 });
  const mountedRef = useRef(true);

  // Restore history on mount
  useEffect(() => {
    const history = loadHistory();
    historyRef.current = history;
    if (history.runs.length > 0) {
      const latest = history.runs[history.runs.length - 1];
      setPending(latest.pending);
      setResults(new Map(Object.entries(latest.results)));
      setAccepted(latest.accepted);
      setResolvedScanName(latest.name);
      if (history.runs.length > 1) {
        setPastRuns(history.runs.slice(0, -1));
      }
    }
  }, []);

  // Persist current run to history as results stream in
  useEffect(() => {
    if (pending.length === 0 || !mountedRef.current) return;
    const safeResults: Record<string, AgentResult> = {};
    for (const [k, v] of results) {
      safeResults[k] = stripPii(v);
    }
    const currentRun: ScanRun = {
      id: historyRef.current.nextId,
      name: resolvedScanName,
      pending,
      results: safeResults,
      accepted: accepted.map((a) => ({
        field_type: a.field_type,
        status: a.status,
      })),
    };
    const history: ScanHistory = {
      runs: [...pastRuns, currentRun],
      nextId: historyRef.current.nextId + 1,
    };
    historyRef.current = history;
    saveHistory(history);
  }, [pending, results, accepted, pastRuns, resolvedScanName]);

  // Timer for progress bar
  useEffect(() => {
    if (scanStartTime && !scanComplete) {
      timerRef.current = setInterval(() => {
        setElapsed(Math.floor((Date.now() - scanStartTime) / 1000));
      }, 1000);
      return () => {
        if (timerRef.current) clearInterval(timerRef.current);
      };
    }
    if (timerRef.current) clearInterval(timerRef.current);
  }, [scanStartTime, scanComplete]);

  // On unmount: abort any running scan
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      if (timerRef.current) clearInterval(timerRef.current);
      clearHistory();
    };
  }, []);

  useEffect(() => {
    if (!auth) return;
    fetch("/brokers", {
      credentials: "include",
    })
      .then(async (res) => {
        if (!res.ok) throw new Error("Failed to load brokers");
        const data = await res.json();
        setBrokers(data.brokers);
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load brokers"),
      )
      .finally(() => setLoading(false));
  }, [auth]);

  useEffect(() => {
    fetch("/health")
      .then(async (res) => {
        if (res.ok) {
          const data = await res.json();
          setAgentTimeoutSeconds(data.agent_timeout_seconds);
        }
      })
      .catch(() => {});
  }, []);

  function toggleBroker(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleAll() {
    if (selected.size === brokers.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(brokers.map((b) => b.key)));
    }
  }

  function updateField(field: keyof IdentityFields, value: string) {
    setIdentity((prev) => ({ ...prev, [field]: value }));
  }

  function toggleRow(name: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function hasIdentityInput(): boolean {
    return !!(
      identity.email.trim() ||
      identity.phone.trim() ||
      identity.name.trim() ||
      identity.address.trim()
    );
  }

  async function handleSubmitClick() {
    if (!auth || selected.size === 0) return;

    // Check for duplicate scan name before proceeding
    if (saveResults && scanName.trim()) {
      try {
        const res = await fetch("/fetch/scans", {
          credentials: "include",
        });
        if (res.ok) {
          const data = await res.json();
          const conflict = data.scans.some(
            (s: { name: string | null }) =>
              s.name && s.name.toLowerCase() === scanName.trim().toLowerCase(),
          );
          if (conflict) {
            setNameConflict(true);
            return;
          }
        }
      } catch {
        // If the check fails, let the backend catch it
      }
    }

    if (hasIdentityInput()) {
      setShowConsent(true);
    } else {
      runScan();
    }
  }

  async function runScan() {
    if (!auth || selected.size === 0) return;
    setShowConsent(false);

    // Abort any in-flight scan before starting a new one
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }

    // Move current run to history if it had any brokers
    if (pending.length > 0) {
      const safeResults: Record<string, AgentResult> = {};
      for (const [k, v] of results) {
        safeResults[k] = stripPii(v);
      }
      // Mark pending brokers with no result as cancelled
      for (const broker of pending) {
        if (!safeResults[broker.name]) {
          safeResults[broker.name] = {
            name: broker.name,
            search_url: broker.search_url,
            status_code: null,
            content_length: null,
            message: "Cancelled.",

            input_fields_found: [],
            matched_inputs: [],
          };
        }
      }
      const finishedRun: ScanRun = {
        id: historyRef.current.nextId,
        name: resolvedScanName,
        pending,
        results: safeResults,
        accepted: accepted.map((a) => ({
          field_type: a.field_type,
          status: a.status,
        })),
      };
      historyRef.current.nextId += 1;
      setPastRuns((prev) => [...prev, finishedRun]);
    }

    setError(null);
    setSubmitting(true);
    setScanComplete(false);
    setScanStartTime(Date.now());
    setElapsed(0);
    setResolvedScanName(null);
    setPending([]);
    setResults(new Map());
    setAccepted([]);
    const payload: Record<string, unknown> = {
      broker_keys: Array.from(selected),
      save: saveResults,
    };
    if (scanName.trim()) payload.scan_name = scanName.trim();
    if (identity.email.trim()) payload.email = identity.email.trim();
    if (identity.phone.trim()) payload.phone = identity.phone.trim();
    if (identity.name.trim()) payload.name = identity.name.trim();
    if (identity.address.trim()) payload.address = identity.address.trim();

    const abort = new AbortController();
    abortRef.current = abort;

    try {
      const res = await fetch("/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(payload),
        signal: abort.signal,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        if (res.status === 409) {
          setNameConflict(true);
          setSubmitting(false);
          return;
        }
        throw new Error(body?.detail ?? `Audit failed (${res.status})`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:") && currentEvent) {
            const data = line.slice(5).trim();
            try {
              const parsed = JSON.parse(data);
              if (currentEvent === "started") {
                setPending(parsed.brokers ?? []);
                setAccepted(parsed.accepted ?? []);
                setResolvedScanName(parsed.scan_name ?? null);
              } else if (currentEvent === "result") {
                setResults((prev) => {
                  const next = new Map(prev);
                  next.set(parsed.name, parsed);
                  return next;
                });
              } else if (currentEvent === "done") {
                setSubmitting(false);
                setScanComplete(true);
              }
            } catch {
              // skip malformed JSON
            }
            currentEvent = "";
          }
        }
      }
    } catch (err) {
      if (!mountedRef.current) return;
      if (abort.signal.aborted) {
        // Aborted scans are already handled by the history snapshot in runScan
      } else {
        setError(err instanceof Error ? err.message : "Something went wrong");
      }
    } finally {
      if (mountedRef.current) {
        setSubmitting(false);
        setScanComplete(true);
      }
      abortRef.current = null;
    }
  }

  const showResults = pending.length > 0;

  return (
    <div className="audit">
      <header className="audit__header">
        <div>
          <h1 className="audit__title">Run Audit</h1>
          <p className="audit__subtitle">
            Enter your information and select brokers to audit
          </p>
        </div>
      </header>

      {loading && <p className="audit__status">Loading brokers...</p>}
      {error && <p className="audit__error">{error}</p>}

      {!loading && brokers.length > 0 && (
        <>
          <section className="audit__pii-wrap">
            <h2 className="audit__section-title">Your Information</h2>
            <p className="audit__pii-hint">
              All fields are optional. Only provided fields will be checked.
            </p>
            <div className="audit__pii-grid" onKeyDown={(e) => { if (e.key === "Enter") handleSubmitClick(); }}>
              <div className="audit__pii-field">
                <label className="audit__pii-label" htmlFor="pii-email">
                  Email
                </label>
                <input
                  id="pii-email"
                  className="audit__pii-input"
                  type="email"
                  placeholder="you@example.com"
                  value={identity.email}
                  onChange={(e) => updateField("email", e.target.value)}
                />
              </div>
              <div className="audit__pii-field">
                <label className="audit__pii-label" htmlFor="pii-phone">
                  Phone
                </label>
                <input
                  id="pii-phone"
                  className="audit__pii-input"
                  type="tel"
                  placeholder="+1 (555) 123-4567"
                  value={identity.phone}
                  onChange={(e) => updateField("phone", e.target.value)}
                />
              </div>
              <div className="audit__pii-field">
                <label className="audit__pii-label" htmlFor="pii-name">
                  Full Name
                </label>
                <input
                  id="pii-name"
                  className="audit__pii-input"
                  type="text"
                  placeholder="Jane Doe"
                  value={identity.name}
                  onChange={(e) => updateField("name", e.target.value)}
                />
              </div>
              <div className="audit__pii-field">
                <label className="audit__pii-label" htmlFor="pii-address">
                  Address
                </label>
                <input
                  id="pii-address"
                  className="audit__pii-input"
                  type="text"
                  placeholder="123 Main St, City, ST 12345"
                  value={identity.address}
                  onChange={(e) => updateField("address", e.target.value)}
                />
              </div>
            </div>
          </section>

          <section className="audit__checklist-wrap">
            <div className="audit__checklist-header">
              <h2 className="audit__section-title">
                Brokers ({selected.size} of {brokers.length} selected)
              </h2>
              <button
                className="audit__toggle-all"
                onClick={toggleAll}
                type="button"
              >
                {selected.size === brokers.length
                  ? "Deselect all"
                  : "Select all"}
              </button>
            </div>

            <ul className="audit__checklist">
              {brokers.map((broker) => (
                <li key={broker.key} className="audit__item">
                  <label className="audit__label">
                    <input
                      type="checkbox"
                      className="audit__checkbox"
                      checked={selected.has(broker.key)}
                      onChange={() => toggleBroker(broker.key)}
                    />
                    <span className="audit__broker-name">{broker.name}</span>
                    <span className="audit__broker-url">
                      {broker.search_url}
                    </span>
                  </label>
                </li>
              ))}
            </ul>

            <div className="audit__submit-bar">
              <div className="audit__submit-options">
                <label className="audit__save-toggle">
                  <input
                    type="checkbox"
                    checked={saveResults}
                    onChange={(e) => setSaveResults(e.target.checked)}
                  />
                  <span>Save results</span>
                </label>
                <div className="audit__scan-name-wrap">
                  <input
                    className={`audit__scan-name ${nameConflict ? "audit__scan-name--conflict" : ""}`}
                    type="text"
                    placeholder="Scan name (optional)"
                    value={scanName}
                    onChange={(e) => {
                      setScanName(e.target.value);
                      if (nameConflict) setNameConflict(false);
                    }}
                    disabled={!saveResults}
                  />
                  {nameConflict && (
                    <span className="audit__scan-name-error">
                      A scan with this name already exists
                    </span>
                  )}
                </div>
              </div>
              <button
                className="audit__submit"
                onClick={handleSubmitClick}
                disabled={selected.size === 0}
              >
                {submitting
                  ? `Restart (${selected.size})`
                  : `Submit (${selected.size})`}
              </button>
            </div>
          </section>
        </>
      )}

      {accepted.length > 0 && (
        <section className="audit__accepted-wrap">
          <h2 className="audit__section-title">Searching for matches in...</h2>
          <ul className="audit__accepted-list">
            {accepted.map((a) => (
              <li key={a.field_type} className="audit__accepted-item">
                <span className="audit__accepted-check">&#10003;</span>
                {a.status}
              </li>
            ))}
          </ul>
        </section>
      )}

      {showResults && scanStartTime && (() => {
        const maxSeconds = pending.length * 120;
        const progress = scanComplete ? 100 : Math.min((elapsed / maxSeconds) * 100, 100);
        const elapsedMin = Math.floor(elapsed / 60);
        const elapsedSec = elapsed % 60;
        const maxMin = Math.floor(maxSeconds / 60);
        return (
          <div className="audit__timer-bar">
            <div className="audit__timer-track">
              <div
                className={`audit__timer-fill ${scanComplete ? "audit__timer-fill--done" : ""}`}
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="audit__timer-labels">
              <span className="audit__timer-elapsed">
                {elapsedMin}:{elapsedSec.toString().padStart(2, "0")}
              </span>
              <span className="audit__timer-status">
                {scanComplete ? "Complete" : "Scanning..."}
              </span>
              <span className="audit__timer-max">
                {maxMin}:{(maxSeconds % 60).toString().padStart(2, "0")} max
              </span>
            </div>
          </div>
        );
      })()}

      {showResults && (
        <section className="audit__results-wrap">
          <div className="audit__results-header">
            <h2 className="audit__section-title">
              {resolvedScanName ?? "Scan Results"}
            </h2>
            <span className="audit__results-progress">
              ({results.size}/{pending.length} Scans Complete)
            </span>
          </div>
          <div className="audit__results-list">
            {/* Completed brokers — rendered as BrokerRow */}
            {[...pending]
              .filter((b) => results.has(b.name))
              .map((b) => agentResultToRow(b.name, results.get(b.name)!))
              .sort((a, b) =>
                compareBrokerResults(
                  {
                    name: a.name,
                    violationCount: a.foundCount,
                    isCancelled: a.state === "CANCELLED",
                    isFailed: a.state === "FAILED",
                  },
                  {
                    name: b.name,
                    violationCount: b.foundCount,
                    isCancelled: b.state === "CANCELLED",
                    isFailed: b.state === "FAILED",
                  },
                ),
              )
              .map((row) => (
                <BrokerRow key={row.name} row={row} />
              ))}
            {/* Still scanning */}
            {[...pending]
              .filter((b) => !results.has(b.name))
              .map((broker) => (
                <div key={broker.name} className="audit__result-item">
                  <div className="audit__result-row audit__result-row--scanning">
                    <div className="audit__result-left">
                      <span className="audit__result-name">{broker.name}</span>
                    </div>
                    <div className="audit__result-output">
                      <span className="audit__scanning-text">Scanning...</span>
                    </div>
                  </div>
                </div>
              ))}
          </div>
        </section>
      )}

      {pastRuns.length > 0 && (
        <section className="audit__history-wrap">
          <h2 className="audit__section-title">
            Previous Runs ({pastRuns.length})
          </h2>
          <div className="audit__history-list">
            {[...pastRuns].reverse().map((run) => {
              const isOpen = expandedRun === run.id;
              const totalBrokers = run.pending.length;
              const completedResults = Object.values(run.results);
              const violationCount = completedResults.filter(
                (r) => r.matched_inputs.some((m) => m.found === true),
              ).length;
              const clearCount = completedResults.filter(
                (r) => (!r.message || r.message === "Completed at timeout.") && !r.matched_inputs.some((m) => m.found === true),
              ).length;
              const cancelledCount = completedResults.filter(
                (r) => r.message === "Cancelled.",
              ).length;
              const errorCount = completedResults.filter(
                (r) => !!r.message && r.message !== "Cancelled." && r.message !== "Completed at timeout.",
              ).length;

              return (
                <div key={run.id} className="audit__history-item">
                  <div
                    className="audit__history-row"
                    onClick={() => setExpandedRun(isOpen ? null : run.id)}
                  >
                    <span className="audit__history-label">
                      {run.name ?? `Run #${run.id}`} &mdash; {totalBrokers} broker
                      {totalBrokers > 1 ? "s" : ""}
                    </span>
                    <div className="audit__history-summary">
                      {violationCount > 0 && (
                        <span className="audit__violation-count">
                          {violationCount} violation
                          {violationCount > 1 ? "s" : ""}
                        </span>
                      )}
                      {clearCount > 0 && (
                        <span className="audit__clear-count">
                          {clearCount} clear
                        </span>
                      )}
                      {cancelledCount > 0 && (
                        <span className="audit__cancelled-count">
                          {cancelledCount} cancelled
                        </span>
                      )}
                      {errorCount > 0 && (
                        <span className="audit__error-text">
                          {errorCount} error
                          {errorCount > 1 ? "s" : ""}
                        </span>
                      )}
                      <span
                        className={`audit__row-chevron ${isOpen ? "audit__row-chevron--open" : ""}`}
                      >
                        &#x276F;
                      </span>
                    </div>
                  </div>

                  {isOpen && (
                    <div className="audit__history-expanded">
                      <div className="audit__history-broker-list">
                        {[...run.pending]
                          .filter((b) => run.results[b.name])
                          .map((b) => agentResultToRow(b.name, run.results[b.name]))
                          .sort((a, b) =>
                            compareBrokerResults(
                              {
                                name: a.name,
                                violationCount: a.foundCount,
                                isCancelled: a.state === "CANCELLED",
                                isFailed: a.state === "FAILED",
                              },
                              {
                                name: b.name,
                                violationCount: b.foundCount,
                                isCancelled: b.state === "CANCELLED",
                                isFailed: b.state === "FAILED",
                              },
                            ),
                          )
                          .map((row) => (
                            <BrokerRow key={row.name} row={row} />
                          ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {showConsent && (
        <div className="audit__consent-overlay" onClick={() => setShowConsent(false)}>
          <div className="audit__consent-modal" onClick={(e) => e.stopPropagation()}>
            <h2 className="audit__consent-title">Before we scan</h2>
            <p className="audit__consent-text">
              To check if your data appears on these broker sites, we need to
              submit your information to each selected broker's search page.
              This means:
            </p>
            <ul className="audit__consent-list">
              <li>Your identity fields will be sent to each broker's website</li>
              <li>The broker will see the search query and may log it</li>
              <li>We check the results for your data and discard the response</li>
            </ul>
            <p className="audit__consent-text">
              No data is stored on our end. The broker receives only what you
              would enter if you searched their site manually.
            </p>
            <p className="audit__consent-text">
              Scans can take up to {agentTimeoutSeconds ? `${Math.ceil(agentTimeoutSeconds / 60)} minute${Math.ceil(agentTimeoutSeconds / 60) === 1 ? "" : "s"}` : "a few minutes"} per broker.
            </p>
            <div className="audit__consent-actions">
              <button
                className="audit__consent-cancel"
                onClick={() => setShowConsent(false)}
              >
                Nevermind
              </button>
              <button
                className="audit__consent-confirm"
                onClick={runScan}
              >
                I understand, scan
              </button>
            </div>
          </div>
        </div>
      )}

      <footer className="audit__footer">
        <button className="audit__back" onClick={() => navigate("/")}>
          &larr; Back to Dashboard
        </button>
      </footer>
    </div>
  );
}
