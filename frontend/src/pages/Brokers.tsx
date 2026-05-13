import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import "./Brokers.css";

interface Broker {
  version: number;
  key: string;
  name: string;
  search_url: string;
  created_at: string;
  opt_out_url: string | null;
  opt_out_url_source: string | null;
}

interface BrokersResponse {
  version: number;
  brokers: Broker[];
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export default function Brokers() {
  const { auth } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState<BrokersResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [discovery, setDiscovery] = useState<{
    brokerKey: string;
    phase: "confirm" | "loading" | "result" | "error";
    discoveredUrl?: string | null;
    errorMessage?: string;
  } | null>(null);

  useEffect(() => {
    if (!auth) return;
    fetch("/brokers", {
      credentials: "include",
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`Failed to load brokers (${res.status})`);
        return res.json();
      })
      .then(setData)
      .catch((err) => setError(err.message));
  }, [auth]);

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div className="brokers">
      <div className="brokers__glow" />

      <header className="brokers__header">
        <h1 className="brokers__title">Available Brokers</h1>
        <p className="brokers__subtitle">
          {data
            ? `${data.brokers.length} brokers in registry v${data.version}`
            : "Loading\u2026"}
        </p>
      </header>

      {error && <p className="brokers__error">{error}</p>}

      {data && (
        <div className="brokers__table-wrap">
          <table className="brokers__table">
            <thead>
              <tr>
                <th className="brokers__th">Name</th>
                <th className="brokers__th">Search URL</th>
                <th className="brokers__th brokers__th--expand" />
              </tr>
            </thead>
            <tbody>
              {data.brokers.map((broker) => {
                const isOpen = expanded.has(broker.key);
                return (
                  <React.Fragment key={broker.key}>
                    <tr
                      className={`brokers__row ${isOpen ? "brokers__row--open" : ""}`}
                      onClick={() => toggle(broker.key)}
                    >
                      <td className="brokers__td brokers__td--name">
                        <span className="brokers__name">{broker.name}</span>
                      </td>
                      <td className="brokers__td brokers__td--url">
                        <a
                          className="brokers__link"
                          href={broker.search_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {broker.search_url.replace(/^https?:\/\//, "")}
                        </a>
                      </td>
                      <td className="brokers__td brokers__td--chevron">
                        <span
                          className={`brokers__chevron ${isOpen ? "brokers__chevron--open" : ""}`}
                        >
                          &#x276F;
                        </span>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="brokers__row brokers__row--expanded">
                        <td className="brokers__td" colSpan={3}>
                          <div className="brokers__details">
                            <div className="brokers__detail">
                              <span className="brokers__detail-label">Key</span>
                              <span className="brokers__detail-value">
                                {broker.key}
                              </span>
                            </div>
                            <div className="brokers__detail">
                              <span className="brokers__detail-label">
                                Version
                              </span>
                              <span className="brokers__detail-value">
                                {broker.version}
                              </span>
                            </div>
                            <div className="brokers__detail">
                              <span className="brokers__detail-label">
                                Added on
                              </span>
                              <span className="brokers__detail-value">
                                {formatDate(broker.created_at)}
                              </span>
                            </div>
                            <div className="brokers__detail brokers__detail--opt-out">
                              <span className="brokers__detail-label">
                                Opt-out
                              </span>
                              <span className="brokers__detail-value brokers__opt-out-value">
                                {broker.opt_out_url_source !== "SEED" && (
                                  <button
                                    className="brokers__refresh-btn"
                                    title="Re-run URL discovery"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setDiscovery({
                                        brokerKey: broker.key,
                                        phase: "confirm",
                                      });
                                    }}
                                  >
                                    &#x21BB;
                                  </button>
                                )}
                                {broker.opt_out_url ? (
                                  <a
                                    className="brokers__link"
                                    href={broker.opt_out_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    {broker.opt_out_url.replace(/^https?:\/\//, "")}
                                  </a>
                                ) : (
                                  <span className="brokers__detail-empty">
                                    Not yet discovered
                                  </span>
                                )}
                              </span>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {discovery && (
        <div
          className="brokers__overlay"
          onClick={() => {
            if (discovery.phase !== "loading") setDiscovery(null);
          }}
        >
          <div
            className="brokers__dialog"
            onClick={(e) => e.stopPropagation()}
          >
            {discovery.phase === "confirm" && (
              <>
                <p className="brokers__dialog-text">
                  Are you sure? This will reset the opt-out URL for everyone.
                </p>
                <div className="brokers__dialog-actions">
                  <button
                    className="brokers__dialog-btn brokers__dialog-btn--cancel"
                    onClick={() => setDiscovery(null)}
                  >
                    Cancel
                  </button>
                  <button
                    className="brokers__dialog-btn brokers__dialog-btn--confirm"
                    onClick={() => {
                      setDiscovery({ ...discovery, phase: "loading" });
                      fetch(
                        `/brokers/${discovery.brokerKey}/discover-opt-out`,
                        { method: "POST", credentials: "include" },
                      )
                        .then(async (res) => {
                          if (!res.ok) {
                            const body = await res.json().catch(() => ({}));
                            throw new Error(
                              body.detail || `Discovery failed (${res.status})`,
                            );
                          }
                          return res.json();
                        })
                        .then((result) => {
                          setDiscovery({
                            ...discovery,
                            phase: "result",
                            discoveredUrl: result.opt_out_url,
                          });
                        })
                        .catch((err) => {
                          setDiscovery({
                            ...discovery,
                            phase: "error",
                            errorMessage: err.message,
                          });
                        });
                    }}
                  >
                    Reset
                  </button>
                </div>
              </>
            )}

            {discovery.phase === "loading" && (
              <div className="brokers__dialog-loading">
                <span className="brokers__dots" />
                <p className="brokers__dialog-text">
                  Running opt-out discovery agent...
                </p>
              </div>
            )}

            {discovery.phase === "error" && (
              <>
                <p className="brokers__dialog-text brokers__dialog-text--error">
                  {discovery.errorMessage}
                </p>
                <div className="brokers__dialog-actions">
                  <button
                    className="brokers__dialog-btn brokers__dialog-btn--cancel"
                    onClick={() => setDiscovery(null)}
                  >
                    Close
                  </button>
                </div>
              </>
            )}

            {discovery.phase === "result" && (
              <>
                {discovery.discoveredUrl ? (
                  <p className="brokers__dialog-text">
                    Found:{" "}
                    <a
                      className="brokers__link"
                      href={discovery.discoveredUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {discovery.discoveredUrl.replace(/^https?:\/\//, "")}
                    </a>
                  </p>
                ) : (
                  <p className="brokers__dialog-text">
                    No opt-out page found for this broker.
                  </p>
                )}
                <div className="brokers__dialog-actions">
                  <button
                    className="brokers__dialog-btn brokers__dialog-btn--cancel"
                    onClick={() => setDiscovery(null)}
                  >
                    Dismiss
                  </button>
                  {discovery.discoveredUrl && (
                    <button
                      className="brokers__dialog-btn brokers__dialog-btn--approve"
                      onClick={() => {
                        fetch(
                          `/brokers/${discovery.brokerKey}/opt-out-url`,
                          {
                            method: "PUT",
                            credentials: "include",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                              opt_out_url: discovery.discoveredUrl,
                            }),
                          },
                        )
                          .then(async (res) => {
                            if (!res.ok) throw new Error("Failed to save");
                            // Update local state
                            setData((prev) => {
                              if (!prev) return prev;
                              return {
                                ...prev,
                                brokers: prev.brokers.map((b) =>
                                  b.key === discovery.brokerKey
                                    ? {
                                        ...b,
                                        opt_out_url: discovery.discoveredUrl!,
                                        opt_out_url_source: "GENERATED",
                                      }
                                    : b,
                                ),
                              };
                            });
                            setDiscovery(null);
                          })
                          .catch(() => {
                            setDiscovery({
                              ...discovery,
                              phase: "error",
                              errorMessage: "Failed to save opt-out URL",
                            });
                          });
                      }}
                    >
                      Looks good, save it
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      <footer className="brokers__footer">
        <button className="brokers__back" onClick={() => navigate("/")}>
          &larr; Back to Dashboard
        </button>
      </footer>
    </div>
  );
}
