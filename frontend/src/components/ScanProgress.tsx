import type { AgentResult, PendingBroker } from "../api";
import BrokerRow from "./BrokerRow";
import type { BrokerRowData } from "./BrokerRow";
import { compareBrokerResults } from "../sort";
import "./ScanProgress.css";

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
    optOutUrl: r.opt_out_url,
  };
}

interface ScanProgressProps {
  pending: PendingBroker[];
  results: Map<string, AgentResult>;
  scanName: string | null;
  elapsed: number;
  scanComplete: boolean;
  scanStartTime: number | null;
}

export { agentResultToRow };

export default function ScanProgress({
  pending,
  results,
  scanName,
  elapsed,
  scanComplete,
  scanStartTime,
}: ScanProgressProps) {
  const maxSeconds = pending.length * 120;
  const progress = scanComplete ? 100 : Math.min((elapsed / maxSeconds) * 100, 100);
  const elapsedMin = Math.floor(elapsed / 60);
  const elapsedSec = elapsed % 60;
  const maxMin = Math.floor(maxSeconds / 60);

  const completedRows = [...pending]
    .filter((b) => results.has(b.name))
    .map((b) => agentResultToRow(b.name, results.get(b.name)!))
    .sort((a, b) =>
      compareBrokerResults(
        { name: a.name, violationCount: a.foundCount, isCancelled: a.state === "CANCELLED", isFailed: a.state === "FAILED" },
        { name: b.name, violationCount: b.foundCount, isCancelled: b.state === "CANCELLED", isFailed: b.state === "FAILED" },
      ),
    );

  const stillScanning = [...pending].filter((b) => !results.has(b.name));

  return (
    <>
      {scanStartTime && (
        <div className="progress panel">
          <div className="progress__track">
            <div
              className={`progress__fill ${scanComplete ? "progress__fill--done" : ""}`}
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="progress__labels">
            <span className="progress__elapsed">
              {elapsedMin}:{elapsedSec.toString().padStart(2, "0")}
            </span>
            <span className="progress__status">
              {scanComplete ? "Complete" : "Scanning..."}
            </span>
            <span className="progress__max">
              {maxMin}:{(maxSeconds % 60).toString().padStart(2, "0")} max
            </span>
          </div>
        </div>
      )}

      <section className="scan-results panel">
        <div className="scan-results__header">
          <h2 className="scan-results__name">
            {scanName ?? "Scan Results"}
          </h2>
          <span className="scan-results__count status-label" style={{ color: "var(--accent)" }}>
            ({results.size}/{pending.length} Scans Complete)
          </span>
        </div>
        <div className="scan-results__list">
          {completedRows.map((row) => (
            <BrokerRow key={row.name} row={row} />
          ))}
          {stillScanning.map((broker) => (
            <div key={broker.name} className="scan-results__pending-item">
              <div className="scan-results__pending-row">
                <span className="scan-results__pending-name">{broker.name}</span>
                <span className="scan-results__scanning-text">Scanning...</span>
              </div>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
