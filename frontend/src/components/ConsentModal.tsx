interface ConsentModalProps {
  onClose: () => void;
  onConfirm: () => void;
  timeoutSeconds: number | null;
}

export default function ConsentModal({ onClose, onConfirm, timeoutSeconds }: ConsentModalProps) {
  const minutes = timeoutSeconds ? Math.ceil(timeoutSeconds / 60) : null;
  const timeLabel = minutes ? `${minutes} minute${minutes === 1 ? "" : "s"}` : "a few minutes";

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <h2 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: 12 }}>
          Before we scan
        </h2>
        <p style={{ fontSize: "0.9rem", lineHeight: 1.5, marginBottom: 12 }}>
          To check if your data appears on these broker sites, we need to
          submit your information to each selected broker's search page.
          This means:
        </p>
        <ul style={{ margin: "0 0 16px 20px", fontSize: "0.85rem", lineHeight: 1.6 }}>
          <li>Your identity fields will be sent to each broker's website</li>
          <li>The broker will see the search query and may log it</li>
          <li>We check the results for your data and discard the response</li>
        </ul>
        <p style={{ fontSize: "0.9rem", lineHeight: 1.5, marginBottom: 12 }}>
          No data is stored on our end. The broker receives only what you
          would enter if you searched their site manually.
        </p>
        <p style={{ fontSize: "0.9rem", lineHeight: 1.5, marginBottom: 12 }}>
          Scans can take up to {timeLabel} per broker.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "flex-end", marginTop: 20 }}>
          <button
            className="btn btn--secondary"
            style={{ padding: "10px 20px", fontSize: "0.85rem" }}
            onClick={onClose}
          >
            Nevermind
          </button>
          <button
            className="btn btn--primary"
            style={{ padding: "10px 20px", fontSize: "0.85rem" }}
            onClick={onConfirm}
          >
            I understand, scan
          </button>
        </div>
      </div>
    </div>
  );
}
