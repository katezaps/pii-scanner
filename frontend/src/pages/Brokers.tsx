import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import "./Brokers.css";

interface Broker {
  version: number;
  key: string;
  name: string;
  search_url: string;
  created_at: string;
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
                  <tr
                    key={broker.key}
                    className={`brokers__row ${isOpen ? "brokers__row--open" : ""}`}
                    onClick={() => toggle(broker.key)}
                  >
                    <td className="brokers__td brokers__td--name">
                      <span className="brokers__name">{broker.name}</span>
                      {isOpen && (
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
                        </div>
                      )}
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
                );
              })}
            </tbody>
          </table>
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
