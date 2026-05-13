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
  optOutUrl: string | null;
}

interface BrokerRowProps {
  row: BrokerRowData;
}

function OptOutRow({ url }: { url: string | null }) {
  return (
    <div className="broker-row__pill-section">
      <span className="broker-row__pill-header">Opt Out</span>
      {url ? (
        <p className="broker-row__empty">
          <a href={url} target="_blank" rel="noopener noreferrer">{url}</a>
        </p>
      ) : (
        <p className="broker-row__empty">Opt out link unavailable</p>
      )}
    </div>
  );
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
            <span className="status-label status-label--cancelled">
              CANCELLED ({row.foundCount})
            </span>
          ) : isFailed ? (
            <span className="status-label status-label--failed">
              FAILED ({row.foundCount})
            </span>
          ) : hasMatches ? (
            <span className="status-label status-label--detected">
              DETECTED PII ({row.foundCount})
            </span>
          ) : (
            <span className="status-label status-label--clear">
              CLEAR (0)
            </span>
          )}
          <span className={`chevron ${open ? "chevron--open" : ""}`}>
            &#x276F;
          </span>
        </div>
      </div>

      {open && (
        <div className="broker-row__expanded">
          {isCancelled && (
            <>
              <div className="msg-box msg-box--amber" style={{ marginTop: 8, marginBottom: 10 }}>
                {row.message ?? "This scan was cancelled before this broker could be checked."}
              </div>
              <div className="broker-row__pill-section">
                <span className="broker-row__pill-header">PII Detected</span>
                {row.fields.filter((f) => f.found).length > 0 ? (
                  <div className="broker-row__pill-list">
                    {row.fields.filter((f) => f.found).map((f) => (
                      <span key={f.field_type} className="tag tag--amber">
                        {f.field_type}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="broker-row__empty">No fields detected before cancellation</p>
                )}
              </div>
              <OptOutRow url={row.optOutUrl} />
            </>
          )}
          {isFailed && (
            <>
              <div className="msg-box msg-box--red" style={{ marginTop: 8, marginBottom: 10 }}>
                Error: {row.message ?? "Broker agent encountered an error during scanning."}
              </div>
              <div className="broker-row__pill-section">
                <span className="broker-row__pill-header">PII Detected</span>
                {row.fields.filter((f) => f.found).length > 0 ? (
                  <div className="broker-row__pill-list">
                    {row.fields.filter((f) => f.found).map((f) => (
                      <span key={f.field_type} className="tag tag--red">
                        {f.field_type}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="broker-row__empty">No fields detected before failure</p>
                )}
              </div>
              <OptOutRow url={row.optOutUrl} />
            </>
          )}
          {!isIncomplete && !hasMatches && (
            <>
              <p className="msg-box msg-box--green" style={{ marginTop: 8 }}>
                No identity fields matched any form inputs on this site.
              </p>
              <OptOutRow url={row.optOutUrl} />
            </>
          )}
          {hasMatches && !isIncomplete && (
            <>
            <div className="broker-row__pill-section">
              <span className="broker-row__pill-header">PII Detected</span>
              <div className="broker-row__pill-list">
                {row.fields.filter((f) => f.found).map((f) => (
                  <span key={f.field_type} className="tag tag--red">
                    {f.field_type}
                  </span>
                ))}
              </div>
            </div>
            <OptOutRow url={row.optOutUrl} />
            </>
          )}
        </div>
      )}
    </div>
  );
}
