import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import type { FetchResult, FetchResponse, ScanListItem } from "../api";
import BrokerRow from "../components/BrokerRow";
import type { BrokerRowData } from "../components/BrokerRow";
import { compareBrokerResults } from "../sort";
import "./Results.css";

function groupByBroker(results: FetchResult[]): BrokerRowData[] {
  const map = new Map<string, BrokerRowData>();
  const statusStates = new Map<string, { state: string; message: string | null }>();

  for (const r of results) {
    // _status rows are markers — track state separately, don't add as a field
    if (r.field_type === "_status") {
      statusStates.set(r.broker_id, { state: r.state, message: r.message });
      if (!map.has(r.broker_id)) {
        map.set(r.broker_id, { name: r.broker_name, state: "SUCCESS", message: null, fields: [], foundCount: 0, optOutUrl: r.opt_out_url });
      }
      continue;
    }

    let row = map.get(r.broker_id);
    if (!row) {
      row = { name: r.broker_name, state: "SUCCESS", message: null, fields: [], foundCount: 0, optOutUrl: r.opt_out_url };
      map.set(r.broker_id, row);
    }
    if (r.opt_out_url && !row.optOutUrl) {
      row.optOutUrl = r.opt_out_url;
    }
    row.fields.push({ field_type: r.field_type, found: r.found });
    if (r.found) {
      row.foundCount++;
    }
  }

  // Apply _status state and message only for brokers with no field results
  for (const [brokerId, row] of map) {
    if (row.fields.length === 0) {
      const status = statusStates.get(brokerId);
      if (status) {
        row.state = status.state;
        row.message = status.message;
      }
    }
  }

  return Array.from(map.values()).sort((a, b) =>
    compareBrokerResults(
      {
        name: a.name,
        violationCount: a.foundCount,
        isCancelled: a.state === "CANCELLED" || a.state === "RUNNING",
        isFailed: a.state === "FAILED",
      },
      {
        name: b.name,
        violationCount: b.foundCount,
        isCancelled: b.state === "CANCELLED" || b.state === "RUNNING",
        isFailed: b.state === "FAILED",
      },
    ),
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function Results() {
  const navigate = useNavigate();
  const location = useLocation();
  const { auth } = useAuth();
  const [scans, setScans] = useState<ScanListItem[]>([]);
  const [expandedScan, setExpandedScan] = useState<string | null>(null);
  const [scanData, setScanData] = useState<Map<string, FetchResponse>>(
    new Map(),
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadScans = useCallback(() => {
    if (!auth) return;

    fetch("/fetch/scans", {
      credentials: "include",
    })
      .then(async (res) => {
        if (!res.ok) throw new Error("Failed to load scans");
        const body = await res.json();
        const sorted = (body.scans as ScanListItem[]).sort(
          (a, b) =>
            new Date(b.expires_at).getTime() -
            new Date(a.expires_at).getTime(),
        );
        setScans(sorted);
        setScanData(new Map());
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Something went wrong"),
      )
      .finally(() => setLoading(false));
  }, [auth]);

  // Reload on mount, navigation, and window focus
  useEffect(() => {
    loadScans();
  }, [loadScans, location.key]);

  useEffect(() => {
    const onFocus = () => loadScans();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [loadScans]);

  async function toggleScan(executionId: string) {
    if (expandedScan === executionId) {
      setExpandedScan(null);
      return;
    }

    setExpandedScan(executionId);

    // Load scan data if not already cached
    if (!scanData.has(executionId) && auth) {
      try {
        const res = await fetch(`/fetch?execution_id=${executionId}`, {
          credentials: "include",
        });
        if (res.ok) {
          const data = await res.json();
          setScanData((prev) => new Map(prev).set(executionId, data));
        }
      } catch {
        // silently fail — row stays expanded with no data
      }
    }
  }



  return (
    <div className="results">
      <header className="results__header">
        <h1 className="results__title">Scan Results</h1>
        <p className="results__subtitle">
          {scans.length > 0
            ? `${scans.length} saved scan${scans.length > 1 ? "s" : ""}`
            : "No saved scans"}
        </p>
      </header>

      {loading && <p className="results__status">Loading...</p>}

      {error && <p className="results__error">{error}</p>}

      {!loading && !error && scans.length === 0 && (
        <div className="results__empty">
          <p>No saved scans found.</p>
          <p className="results__empty-hint">
            Run an audit with "Save results" enabled to see results here.
          </p>
        </div>
      )}

      {scans.length > 0 && (
        <section className="results__scans-wrap">
          <div className="results__scans-list">
            {scans.map((scan) => {
              const isOpen = expandedScan === scan.execution_id;
              const data = scanData.get(scan.execution_id);
              const rows = data ? groupByBroker(data.results) : [];

              return (
                <div
                  key={scan.execution_id}
                  className={`results__scan-item ${isOpen ? "results__scan-item--open" : ""}`}
                >
                  <div
                    className="results__scan-row"
                    onClick={() => toggleScan(scan.execution_id)}
                  >
                    <div className="results__scan-info">
                      <span className="results__scan-name">
                        {scan.name ?? "Unnamed scan"}
                      </span>
                      <span className="results__scan-date">
                        expires {formatDate(scan.expires_at)}
                      </span>
                    </div>
                    <div className="results__scan-right">
                      <span className="results__scan-summary">
                        {scan.found_count} violation{scan.found_count !== 1 ? "s" : ""}, {scan.broker_count - scan.incomplete_count}/{scan.broker_count} scans complete
                      </span>
                      <span
                        className={`results__chevron ${isOpen ? "results__chevron--open" : ""}`}
                      >
                        &#x276F;
                      </span>
                    </div>
                  </div>

                  {isOpen && (
                    <div className="results__scan-detail">
                      {!data && (
                        <p className="results__status">Loading...</p>
                      )}

                      {data && rows.length === 0 && (
                        <div className="results__expanded-clear-block">
                          {scan.state === "CANCELLED"
                            ? "This scan was cancelled before any brokers were checked."
                            : "No results in this scan."}
                        </div>
                      )}

                      {data && rows.length > 0 && (
                        <div className="results__broker-list">
                          {rows.map((row) => (
                            <BrokerRow key={row.name} row={row} />
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      <footer className="results__footer">
        <button className="results__back" onClick={() => navigate("/")}>
          &larr; Back to Dashboard
        </button>
      </footer>
    </div>
  );
}
