import { useState } from "react";
import "./BrokerRow.css";

export interface BrokerFieldResult {
  field_type: string;
  found: boolean;
}

export interface BrokerRowData {
  name: string;
  state: string;
  message: string | null;
  fields: BrokerFieldResult[];
  foundCount: number;
}

interface BrokerRowProps {
  row: BrokerRowData;
}

export default function BrokerRow({ row }: BrokerRowProps) {
  const [open, setOpen] = useState(false);

  const isCancelled = row.state === "CANCELLED" || row.state === "RUNNING";
  const isFailed = row.state === "FAILED";
  const isIncomplete = isCancelled || isFailed;
  const hasMatches = row.foundCount > 0;

  return (
    <div className="broker-row">
      <div
        className={`broker-row__header ${hasMatches ? "broker-row__header--detected" : ""} ${!isIncomplete && !hasMatches ? "broker-row__header--clear" : ""} ${isCancelled ? "broker-row__header--warn" : ""} ${isFailed ? "broker-row__header--error" : ""}`}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="broker-row__name">{row.name}</span>
        <div className="broker-row__output">
          {isCancelled ? (
            <span className="broker-row__status broker-row__status--cancelled">
              CANCELLED ({row.foundCount})
            </span>
          ) : isFailed ? (
            <span className="broker-row__status broker-row__status--failed">
              FAILED ({row.foundCount})
            </span>
          ) : hasMatches ? (
            <span className="broker-row__status broker-row__status--detected">
              DETECTED PII ({row.foundCount})
            </span>
          ) : (
            <span className="broker-row__status broker-row__status--clear">
              CLEAR (0)
            </span>
          )}
          <span className={`broker-row__chevron ${open ? "broker-row__chevron--open" : ""}`}>
            &#x276F;
          </span>
        </div>
      </div>

      {open && (
        <div className="broker-row__expanded">
          {isCancelled && (
            <>
              <div className="broker-row__msg broker-row__msg--cancelled">
                {row.message ?? "This scan was cancelled before this broker could be checked."}
              </div>
              <div className="broker-row__pill-section">
                <span className="broker-row__pill-header">PII Detected</span>
                {row.fields.filter((f) => f.found).length > 0 ? (
                  <div className="broker-row__pill-list">
                    {row.fields.filter((f) => f.found).map((f) => (
                      <span key={f.field_type} className="broker-row__pill broker-row__pill--cancelled">
                        {f.field_type}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="broker-row__empty">No fields detected before cancellation</p>
                )}
              </div>
            </>
          )}
          {isFailed && (
            <>
              <div className="broker-row__msg broker-row__msg--error">
                Error: {row.message ?? "Broker agent encountered an error during scanning."}
              </div>
              <div className="broker-row__pill-section">
                <span className="broker-row__pill-header">PII Detected</span>
                {row.fields.filter((f) => f.found).length > 0 ? (
                  <div className="broker-row__pill-list">
                    {row.fields.filter((f) => f.found).map((f) => (
                      <span key={f.field_type} className="broker-row__pill broker-row__pill--failed">
                        {f.field_type}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="broker-row__empty">No fields detected before failure</p>
                )}
              </div>
            </>
          )}
          {!isIncomplete && !hasMatches && (
            <p className="broker-row__clear-msg">
              No identity fields matched any form inputs on this site.
            </p>
          )}
          {hasMatches && !isIncomplete && (
            <div className="broker-row__pill-section">
              <span className="broker-row__pill-header">PII Detected</span>
              <div className="broker-row__pill-list">
                {row.fields.filter((f) => f.found).map((f) => (
                  <span key={f.field_type} className="broker-row__pill broker-row__pill--detected">
                    {f.field_type}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
