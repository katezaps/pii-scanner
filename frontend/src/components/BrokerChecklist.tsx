import "./BrokerChecklist.css";

interface Broker {
  key: string;
  name: string;
  search_url: string;
}

interface BrokerChecklistProps {
  brokers: Broker[];
  selected: Set<string>;
  onToggle: (key: string) => void;
  onToggleAll: () => void;
  saveResults: boolean;
  setSaveResults: (v: boolean) => void;
  scanName: string;
  setScanName: (v: string) => void;
  nameConflict: boolean;
  setNameConflict: (v: boolean) => void;
  onSubmit: () => void;
  submitting: boolean;
}

export default function BrokerChecklist({
  brokers,
  selected,
  onToggle,
  onToggleAll,
  saveResults,
  setSaveResults,
  scanName,
  setScanName,
  nameConflict,
  setNameConflict,
  onSubmit,
  submitting,
}: BrokerChecklistProps) {
  return (
    <section className="checklist panel">
      <div className="checklist__header">
        <h2 className="checklist__title section-label" style={{ color: "var(--accent)" }}>
          Brokers ({selected.size} of {brokers.length} selected)
        </h2>
        <button className="checklist__toggle btn" onClick={onToggleAll} type="button">
          {selected.size === brokers.length ? "Deselect all" : "Select all"}
        </button>
      </div>

      <ul className="checklist__list">
        {brokers.map((broker) => (
          <li key={broker.key} className="checklist__item">
            <label className="checklist__label">
              <input
                type="checkbox"
                className="checklist__checkbox"
                checked={selected.has(broker.key)}
                onChange={() => onToggle(broker.key)}
              />
              <span className="checklist__name">{broker.name}</span>
              <span className="checklist__url">{broker.search_url}</span>
            </label>
          </li>
        ))}
      </ul>

      <div className="checklist__submit-bar">
        <div className="checklist__options">
          <label className="checklist__save-toggle">
            <input
              type="checkbox"
              checked={saveResults}
              onChange={(e) => setSaveResults(e.target.checked)}
            />
            <span>Save results</span>
          </label>
          <div className="checklist__name-wrap">
            <input
              className={`checklist__scan-name input ${nameConflict ? "checklist__scan-name--conflict" : ""}`}
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
              <span className="checklist__name-error">
                A scan with this name already exists
              </span>
            )}
          </div>
        </div>
        <button
          className="checklist__submit btn btn--primary"
          onClick={onSubmit}
          disabled={selected.size === 0}
        >
          {submitting ? `Restart (${selected.size})` : `Submit (${selected.size})`}
        </button>
      </div>
    </section>
  );
}
