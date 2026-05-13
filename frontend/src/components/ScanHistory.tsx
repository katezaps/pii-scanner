import BrokerRow from "./BrokerRow";
import { agentResultToRow } from "./ScanProgress";
import type { AgentResult, PendingBroker } from "./ScanProgress";
import { compareBrokerResults } from "../sort";
import "./ScanHistory.css";

interface AcceptedField {
  field_type: string;
  status: string;
}

interface ScanRun {
  id: number;
  name: string | null;
  pending: PendingBroker[];
  results: Record<string, AgentResult>;
  accepted: AcceptedField[];
}

export type { ScanRun, AcceptedField };

interface ScanHistoryProps {
  runs: ScanRun[];
  expandedRun: number | null;
  onToggleRun: (id: number) => void;
}

export default function ScanHistory({ runs, expandedRun, onToggleRun }: ScanHistoryProps) {
  return (
    <section className="history panel">
      <h2 className="history__title section-label" style={{ color: "var(--accent)" }}>
        Previous Runs ({runs.length})
      </h2>
      <div className="history__list">
        {[...runs].reverse().map((run) => {
          const isOpen = expandedRun === run.id;
          const completedResults = Object.values(run.results);
          const violationCount = completedResults.filter(
            (r) => r.matched_inputs.some((m) => m.found === true),
          ).length;
          const clearCount = completedResults.filter(
            (r) =>
              (!r.message || r.message === "Completed at timeout.") &&
              !r.matched_inputs.some((m) => m.found === true),
          ).length;
          const cancelledCount = completedResults.filter(
            (r) => r.message === "Cancelled.",
          ).length;
          const errorCount = completedResults.filter(
            (r) =>
              !!r.message &&
              r.message !== "Cancelled." &&
              r.message !== "Completed at timeout.",
          ).length;

          return (
            <div key={run.id} className="history__item">
              <div className="history__row" onClick={() => onToggleRun(run.id)}>
                <span className="history__label">
                  {run.name ?? `Run #${run.id}`} &mdash; {run.pending.length} broker
                  {run.pending.length > 1 ? "s" : ""}
                </span>
                <div className="history__summary">
                  {violationCount > 0 && (
                    <span className="status-label status-label--red">
                      {violationCount} violation{violationCount > 1 ? "s" : ""}
                    </span>
                  )}
                  {clearCount > 0 && (
                    <span className="status-label status-label--green">
                      {clearCount} clear
                    </span>
                  )}
                  {cancelledCount > 0 && (
                    <span className="status-label status-label--amber">
                      {cancelledCount} cancelled
                    </span>
                  )}
                  {errorCount > 0 && (
                    <span className="status-label status-label--red">
                      {errorCount} error{errorCount > 1 ? "s" : ""}
                    </span>
                  )}
                  <span className={`chevron ${isOpen ? "chevron--open" : ""}`}>
                    &#x276F;
                  </span>
                </div>
              </div>

              {isOpen && (
                <div className="history__expanded">
                  <div className="history__broker-list">
                    {[...run.pending]
                      .filter((b) => run.results[b.name])
                      .map((b) => agentResultToRow(b.name, run.results[b.name]))
                      .sort((a, b) =>
                        compareBrokerResults(
                          { name: a.name, violationCount: a.foundCount, isCancelled: a.state === "CANCELLED", isFailed: a.state === "FAILED" },
                          { name: b.name, violationCount: b.foundCount, isCancelled: b.state === "CANCELLED", isFailed: b.state === "FAILED" },
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
  );
}
