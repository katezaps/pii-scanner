import { useEffect, useReducer, useRef, useState } from "react";
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

// ── Scan state machine ──────────────────────────────────────────

type ScanPhase = "idle" | "confirming" | "scanning" | "complete" | "error";

interface ScanState {
  phase: ScanPhase;
  pending: PendingBroker[];
  results: Map<string, AgentResult>;
  accepted: AcceptedField[];
  scanName: string | null;
  startTime: number | null;
  elapsed: number;
  error: string | null;
  pastRuns: ScanRun[];
}

type ScanAction =
  | { type: "CONFIRM" }
  | { type: "CANCEL_CONFIRM" }
  | { type: "START"; startTime: number }
  | { type: "STARTED"; pending: PendingBroker[]; accepted: AcceptedField[]; scanName: string | null }
  | { type: "RESULT"; name: string; result: AgentResult }
  | { type: "TICK"; elapsed: number }
  | { type: "DONE" }
  | { type: "ERROR"; error: string }
  | { type: "NAME_CONFLICT" }
  | { type: "ARCHIVE_RUN"; run: ScanRun }
  | { type: "RESTORE"; pending: PendingBroker[]; results: Map<string, AgentResult>; accepted: AcceptedField[]; scanName: string | null; pastRuns: ScanRun[] };

const initialScanState: ScanState = {
  phase: "idle",
  pending: [],
  results: new Map(),
  accepted: [],
  scanName: null,
  startTime: null,
  elapsed: 0,
  error: null,
  pastRuns: [],
};

function scanReducer(state: ScanState, action: ScanAction): ScanState {
  switch (action.type) {
    case "CONFIRM":
      return { ...state, phase: "confirming" };
    case "CANCEL_CONFIRM":
      return { ...state, phase: "idle" };
    case "START":
      return {
        ...state,
        phase: "scanning",
        pending: [],
        results: new Map(),
        accepted: [],
        scanName: null,
        startTime: action.startTime,
        elapsed: 0,
        error: null,
      };
    case "STARTED":
      return {
        ...state,
        pending: action.pending,
        accepted: action.accepted,
        scanName: action.scanName,
      };
    case "RESULT": {
      const next = new Map(state.results);
      next.set(action.name, action.result);
      return { ...state, results: next };
    }
    case "TICK":
      return { ...state, elapsed: action.elapsed };
    case "DONE":
      return { ...state, phase: "complete" };
    case "ERROR":
      return { ...state, phase: "error", error: action.error };
    case "NAME_CONFLICT":
      return { ...state, phase: "idle" };
    case "ARCHIVE_RUN":
      return { ...state, pastRuns: [...state.pastRuns, action.run] };
    case "RESTORE":
      return {
        ...state,
        phase: "complete",
        pending: action.pending,
        results: action.results,
        accepted: action.accepted,
        scanName: action.scanName,
        pastRuns: action.pastRuns,
      };
    default:
      return state;
  }
}

// ── History persistence ─────────────────────────────────────────

const CACHE_KEY = "pii-scanner-scan-cache";

interface HistoryCache {
  runs: ScanRun[];
  nextId: number;
}

function loadHistory(): HistoryCache {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return { runs: [], nextId: 1 };
    return JSON.parse(raw);
  } catch {
    return { runs: [], nextId: 1 };
  }
}

function stripPii(result: AgentResult): AgentResult {
  return { ...result, matched_inputs: result.matched_inputs.map((m) => ({ ...m })) };
}

function saveHistoryCache(history: HistoryCache) {
  localStorage.setItem(CACHE_KEY, JSON.stringify(history));
}

// ── Component ───────────────────────────────────────────────────

export default function Audit() {
  const navigate = useNavigate();
  const { auth } = useAuth();

  // Page-level state (not scan lifecycle)
  const [brokers, setBrokers] = useState<BrokerOut[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [identity, setIdentity] = useState<IdentityFields>({ email: "", phone: "", name: "", address: "" });
  const [loading, setLoading] = useState(true);
  const [saveResults, setSaveResults] = useState(false);
  const [scanNameInput, setScanNameInput] = useState("");
  const [nameConflict, setNameConflict] = useState(false);
  const [expandedRun, setExpandedRun] = useState<number | null>(null);
  const [agentTimeoutSeconds, setAgentTimeoutSeconds] = useState<number | null>(null);

  // Scan lifecycle
  const [scan, dispatch] = useReducer(scanReducer, initialScanState);

  // Refs
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const historyRef = useRef<HistoryCache>({ runs: [], nextId: 1 });
  const mountedRef = useRef(true);

  // Restore history on mount
  useEffect(() => {
    const history = loadHistory();
    historyRef.current = history;
    if (history.runs.length > 0) {
      const latest = history.runs[history.runs.length - 1];
      dispatch({
        type: "RESTORE",
        pending: latest.pending,
        results: new Map(Object.entries(latest.results)),
        accepted: latest.accepted,
        scanName: latest.name,
        pastRuns: history.runs.slice(0, -1),
      });
    }
  }, []);

  // Persist current run to history
  useEffect(() => {
    if (scan.pending.length === 0 || !mountedRef.current) return;
    const safeResults: Record<string, AgentResult> = {};
    for (const [k, v] of scan.results) safeResults[k] = stripPii(v);
    const currentRun: ScanRun = {
      id: historyRef.current.nextId,
      name: scan.scanName,
      pending: scan.pending,
      results: safeResults,
      accepted: scan.accepted.map((a) => ({ field_type: a.field_type, status: a.status })),
    };
    const history: HistoryCache = {
      runs: [...scan.pastRuns, currentRun],
      nextId: historyRef.current.nextId + 1,
    };
    historyRef.current = history;
    saveHistoryCache(history);
  }, [scan.pending, scan.results, scan.accepted, scan.pastRuns, scan.scanName]);

  // Timer
  useEffect(() => {
    if (scan.phase === "scanning" && scan.startTime) {
      timerRef.current = setInterval(() => {
        dispatch({ type: "TICK", elapsed: Math.floor((Date.now() - scan.startTime!) / 1000) });
      }, 1000);
      return () => { if (timerRef.current) clearInterval(timerRef.current); };
    }
    if (timerRef.current) clearInterval(timerRef.current);
  }, [scan.phase, scan.startTime]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }
      if (timerRef.current) clearInterval(timerRef.current);
      localStorage.removeItem(CACHE_KEY);
    };
  }, []);

  // Fetch brokers
  useEffect(() => {
    if (!auth) return;
    fetch("/brokers", { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) throw new Error("Failed to load brokers");
        setBrokers((await res.json()).brokers);
      })
      .catch((err) => dispatch({ type: "ERROR", error: err instanceof Error ? err.message : "Failed to load brokers" }))
      .finally(() => setLoading(false));
  }, [auth]);

  // Fetch timeout config
  useEffect(() => {
    fetch("/health")
      .then(async (res) => { if (res.ok) setAgentTimeoutSeconds((await res.json()).agent_timeout_seconds); })
      .catch(() => {});
  }, []);

  // ── Handlers ────────────────────────────────────────────────

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
    if (saveResults && scanNameInput.trim()) {
      try {
        const res = await fetch("/fetch/scans", { credentials: "include" });
        if (res.ok) {
          const data = await res.json();
          if (data.scans.some((s: { name: string | null }) => s.name && s.name.toLowerCase() === scanNameInput.trim().toLowerCase())) {
            setNameConflict(true);
            return;
          }
        }
      } catch {}
    }
    if (hasIdentityInput()) {
      dispatch({ type: "CONFIRM" });
    } else {
      runScan();
    }
  }

  async function runScan() {
    if (!auth || selected.size === 0) return;
    dispatch({ type: "CANCEL_CONFIRM" });
    if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }

    // Archive current run if one exists
    if (scan.pending.length > 0) {
      const safeResults: Record<string, AgentResult> = {};
      for (const [k, v] of scan.results) safeResults[k] = stripPii(v);
      for (const broker of scan.pending) {
        if (!safeResults[broker.name]) {
          safeResults[broker.name] = {
            name: broker.name, search_url: broker.search_url,
            status_code: null, content_length: null, message: "Cancelled.",
            input_fields_found: [], matched_inputs: [], opt_out_url: null,
          };
        }
      }
      dispatch({
        type: "ARCHIVE_RUN",
        run: {
          id: historyRef.current.nextId,
          name: scan.scanName,
          pending: scan.pending,
          results: safeResults,
          accepted: scan.accepted.map((a) => ({ field_type: a.field_type, status: a.status })),
        },
      });
      historyRef.current.nextId += 1;
    }

    dispatch({ type: "START", startTime: Date.now() });

    const payload: Record<string, unknown> = { broker_keys: Array.from(selected), save: saveResults };
    if (scanNameInput.trim()) payload.scan_name = scanNameInput.trim();
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
        if (res.status === 409) { setNameConflict(true); dispatch({ type: "NAME_CONFLICT" }); return; }
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
                dispatch({ type: "STARTED", pending: parsed.brokers ?? [], accepted: parsed.accepted ?? [], scanName: parsed.scan_name ?? null });
              } else if (currentEvent === "result") {
                dispatch({ type: "RESULT", name: parsed.name, result: parsed });
              } else if (currentEvent === "done") {
                dispatch({ type: "DONE" });
              }
            } catch {}
            currentEvent = "";
          }
        }
      }
    } catch (err) {
      if (!mountedRef.current) return;
      if (!abort.signal.aborted) {
        dispatch({ type: "ERROR", error: err instanceof Error ? err.message : "Something went wrong" });
      }
    } finally {
      if (mountedRef.current && scan.phase === "scanning") {
        dispatch({ type: "DONE" });
      }
      abortRef.current = null;
    }
  }

  const showResults = scan.pending.length > 0;

  return (
    <div className="audit">
      <header className="audit__header">
        <div>
          <h1 className="audit__title">Run Audit</h1>
          <p className="audit__subtitle">Enter your information and select brokers to audit</p>
        </div>
      </header>

      {loading && <p className="audit__status">Loading brokers...</p>}
      {scan.error && <p className="audit__error msg-box msg-box--red">{scan.error}</p>}

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
            scanName={scanNameInput}
            setScanName={setScanNameInput}
            nameConflict={nameConflict}
            setNameConflict={setNameConflict}
            onSubmit={handleSubmitClick}
            submitting={scan.phase === "scanning"}
          />
        </>
      )}

      {scan.accepted.length > 0 && (
        <section className="audit__accepted panel">
          <h2 className="section-label" style={{ color: "var(--accent)" }}>Searching for matches in...</h2>
          <ul className="audit__accepted-list">
            {scan.accepted.map((a) => (
              <li key={a.field_type} className="audit__accepted-item tag tag--accent">
                <span>&#10003;</span> {a.status}
              </li>
            ))}
          </ul>
        </section>
      )}

      {showResults && (
        <ScanProgress
          pending={scan.pending}
          results={scan.results}
          scanName={scan.scanName}
          elapsed={scan.elapsed}
          scanComplete={scan.phase === "complete"}
          scanStartTime={scan.startTime}
        />
      )}

      {scan.pastRuns.length > 0 && (
        <ScanHistory
          runs={scan.pastRuns}
          expandedRun={expandedRun}
          onToggleRun={(id) => setExpandedRun(expandedRun === id ? null : id)}
        />
      )}

      {scan.phase === "confirming" && (
        <ConsentModal
          onClose={() => dispatch({ type: "CANCEL_CONFIRM" })}
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
