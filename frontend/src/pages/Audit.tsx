import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import type { AgentResult, PendingBroker, AcceptedField, BrokerOut } from "../api";
import PiiForm from "../components/PiiForm";
import type { IdentityFields } from "../components/PiiForm";
import BrokerChecklist from "../components/BrokerChecklist";
import ConsentModal from "../components/ConsentModal";
import ScanProgress from "../components/ScanProgress";
import ScanHistory from "../components/ScanHistory";
import type { ScanRun } from "../components/ScanHistory";
import "./Audit.css";

const CACHE_KEY = "pii-scanner-scan-cache";

interface ScanHistory_ {
  runs: ScanRun[];
  nextId: number;
}

function loadHistory(): ScanHistory_ {
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

function saveHistoryCache(history: ScanHistory_) {
  localStorage.setItem(CACHE_KEY, JSON.stringify(history));
}

export default function Audit() {
  const navigate = useNavigate();
  const { auth } = useAuth();
  const [brokers, setBrokers] = useState<BrokerOut[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [identity, setIdentity] = useState<IdentityFields>({
    email: "", phone: "", name: "", address: "",
  });
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [pending, setPending] = useState<PendingBroker[]>([]);
  const [results, setResults] = useState<Map<string, AgentResult>>(new Map());
  const [accepted, setAccepted] = useState<AcceptedField[]>([]);
  const [error, setError] = useState<string | null>(null);
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
  const historyRef = useRef<ScanHistory_>({ runs: [], nextId: 1 });
  const mountedRef = useRef(true);

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

  useEffect(() => {
    if (pending.length === 0 || !mountedRef.current) return;
    const safeResults: Record<string, AgentResult> = {};
    for (const [k, v] of results) safeResults[k] = stripPii(v);
    const currentRun: ScanRun = {
      id: historyRef.current.nextId,
      name: resolvedScanName,
      pending,
      results: safeResults,
      accepted: accepted.map((a) => ({ field_type: a.field_type, status: a.status })),
    };
    const history: ScanHistory_ = {
      runs: [...pastRuns, currentRun],
      nextId: historyRef.current.nextId + 1,
    };
    historyRef.current = history;
    saveHistoryCache(history);
  }, [pending, results, accepted, pastRuns, resolvedScanName]);

  useEffect(() => {
    if (scanStartTime && !scanComplete) {
      timerRef.current = setInterval(() => {
        setElapsed(Math.floor((Date.now() - scanStartTime) / 1000));
      }, 1000);
      return () => { if (timerRef.current) clearInterval(timerRef.current); };
    }
    if (timerRef.current) clearInterval(timerRef.current);
  }, [scanStartTime, scanComplete]);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }
      if (timerRef.current) clearInterval(timerRef.current);
      localStorage.removeItem(CACHE_KEY);
    };
  }, []);

  useEffect(() => {
    if (!auth) return;
    fetch("/brokers", { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) throw new Error("Failed to load brokers");
        setBrokers((await res.json()).brokers);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load brokers"))
      .finally(() => setLoading(false));
  }, [auth]);

  useEffect(() => {
    fetch("/health")
      .then(async (res) => { if (res.ok) setAgentTimeoutSeconds((await res.json()).agent_timeout_seconds); })
      .catch(() => {});
  }, []);

  function toggleBroker(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  function toggleAll() {
    setSelected(selected.size === brokers.length ? new Set() : new Set(brokers.map((b) => b.key)));
  }

  function hasIdentityInput(): boolean {
    return !!(identity.email.trim() || identity.phone.trim() || identity.name.trim() || identity.address.trim());
  }

  async function handleSubmitClick() {
    if (!auth || selected.size === 0) return;
    if (saveResults && scanName.trim()) {
      try {
        const res = await fetch("/fetch/scans", { credentials: "include" });
        if (res.ok) {
          const data = await res.json();
          if (data.scans.some((s: { name: string | null }) => s.name && s.name.toLowerCase() === scanName.trim().toLowerCase())) {
            setNameConflict(true);
            return;
          }
        }
      } catch {}
    }
    if (hasIdentityInput()) setShowConsent(true); else runScan();
  }

  async function runScan() {
    if (!auth || selected.size === 0) return;
    setShowConsent(false);
    if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }

    if (pending.length > 0) {
      const safeResults: Record<string, AgentResult> = {};
      for (const [k, v] of results) safeResults[k] = stripPii(v);
      for (const broker of pending) {
        if (!safeResults[broker.name]) {
          safeResults[broker.name] = {
            name: broker.name, search_url: broker.search_url,
            status_code: null, content_length: null, message: "Cancelled.",
            input_fields_found: [], matched_inputs: [], opt_out_url: null,
          };
        }
      }
      const finishedRun: ScanRun = {
        id: historyRef.current.nextId, name: resolvedScanName,
        pending, results: safeResults,
        accepted: accepted.map((a) => ({ field_type: a.field_type, status: a.status })),
      };
      historyRef.current.nextId += 1;
      setPastRuns((prev) => [...prev, finishedRun]);
    }

    setError(null); setSubmitting(true); setScanComplete(false);
    setScanStartTime(Date.now()); setElapsed(0); setResolvedScanName(null);
    setPending([]); setResults(new Map()); setAccepted([]);

    const payload: Record<string, unknown> = { broker_keys: Array.from(selected), save: saveResults };
    if (scanName.trim()) payload.scan_name = scanName.trim();
    if (identity.email.trim()) payload.email = identity.email.trim();
    if (identity.phone.trim()) payload.phone = identity.phone.trim();
    if (identity.name.trim()) payload.name = identity.name.trim();
    if (identity.address.trim()) payload.address = identity.address.trim();

    const abort = new AbortController();
    abortRef.current = abort;

    try {
      const res = await fetch("/audit", {
        method: "POST", headers: { "Content-Type": "application/json" },
        credentials: "include", body: JSON.stringify(payload), signal: abort.signal,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        if (res.status === 409) { setNameConflict(true); setSubmitting(false); return; }
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
            try {
              const parsed = JSON.parse(line.slice(5).trim());
              if (currentEvent === "started") {
                setPending(parsed.brokers ?? []);
                setAccepted(parsed.accepted ?? []);
                setResolvedScanName(parsed.scan_name ?? null);
              } else if (currentEvent === "result") {
                setResults((prev) => { const next = new Map(prev); next.set(parsed.name, parsed); return next; });
              } else if (currentEvent === "done") {
                setSubmitting(false); setScanComplete(true);
              }
            } catch {}
            currentEvent = "";
          }
        }
      }
    } catch (err) {
      if (!mountedRef.current) return;
      if (!abort.signal.aborted) setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      if (mountedRef.current) { setSubmitting(false); setScanComplete(true); }
      abortRef.current = null;
    }
  }

  const showResults = pending.length > 0;

  return (
    <div className="audit">
      <header className="audit__header">
        <div>
          <h1 className="audit__title">Run Audit</h1>
          <p className="audit__subtitle">Enter your information and select brokers to audit</p>
        </div>
      </header>

      {loading && <p className="audit__status">Loading brokers...</p>}
      {error && <p className="audit__error msg-box msg-box--red">{error}</p>}

      {!loading && brokers.length > 0 && (
        <>
          <PiiForm
            identity={identity}
            onChange={(field, value) => setIdentity((prev) => ({ ...prev, [field]: value }))}
            onSubmit={handleSubmitClick}
          />
          <BrokerChecklist
            brokers={brokers}
            selected={selected}
            onToggle={toggleBroker}
            onToggleAll={toggleAll}
            saveResults={saveResults}
            setSaveResults={setSaveResults}
            scanName={scanName}
            setScanName={setScanName}
            nameConflict={nameConflict}
            setNameConflict={setNameConflict}
            onSubmit={handleSubmitClick}
            submitting={submitting}
          />
        </>
      )}

      {accepted.length > 0 && (
        <section className="audit__accepted panel">
          <h2 className="section-label" style={{ color: "var(--accent)" }}>Searching for matches in...</h2>
          <ul className="audit__accepted-list">
            {accepted.map((a) => (
              <li key={a.field_type} className="audit__accepted-item tag tag--accent">
                <span>&#10003;</span> {a.status}
              </li>
            ))}
          </ul>
        </section>
      )}

      {showResults && (
        <ScanProgress
          pending={pending}
          results={results}
          scanName={resolvedScanName}
          elapsed={elapsed}
          scanComplete={scanComplete}
          scanStartTime={scanStartTime}
        />
      )}

      {pastRuns.length > 0 && (
        <ScanHistory
          runs={pastRuns}
          expandedRun={expandedRun}
          onToggleRun={(id) => setExpandedRun(expandedRun === id ? null : id)}
        />
      )}

      {showConsent && (
        <ConsentModal
          onClose={() => setShowConsent(false)}
          onConfirm={runScan}
          timeoutSeconds={agentTimeoutSeconds}
        />
      )}

      <footer className="audit__footer">
        <button className="btn btn--secondary" style={{ padding: "10px 20px", fontSize: "0.85rem" }} onClick={() => navigate("/")}>
          &larr; Back to Dashboard
        </button>
      </footer>
    </div>
  );
}
