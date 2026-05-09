import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import "./Dashboard.css";

interface ActionCard {
  id: string;
  title: string;
  description: string;
  icon: string;
  path: string | null;
}

const actions: ActionCard[] = [
  {
    id: "audit",
    title: "Run Audit",
    description: "Scan brokers for your personal data",
    icon: "\u{1F50D}",
    path: "/audit",
  },
  {
    id: "view",
    title: "View Results",
    description: "Check the status of previous scans",
    icon: "\u{1F4CA}",
    path: "/results",
  },
  {
    id: "brokers",
    title: "Available Brokers",
    description: "Browse the list of supported data brokers",
    icon: "\u{1F3E2}",
    path: "/brokers",
  },
];

export default function Dashboard() {
  const navigate = useNavigate();
  const { auth, logout } = useAuth();

  return (
    <div className="dash">
      <header className="dash__header">
        <div className="dash__glow" />
        <h1 className="dash__logo">Broker Audit</h1>
        <p className="dash__subtitle">Personal data broker scanning service</p>
        <div className="dash__user-bar">
          <span className="dash__user">
            {auth?.userName ?? auth?.userId}
          </span>
          <button className="dash__logout" onClick={logout}>
            Log out
          </button>
        </div>
      </header>

      <main className="dash__grid">
        {actions.map((action) => (
          <button
            key={action.id}
            className={`card ${action.id === "audit" ? "card--full" : ""}`}
            onClick={() => action.path && navigate(action.path)}
            disabled={!action.path}
          >
            <span className="card__icon">{action.icon}</span>
            <h2 className="card__title">{action.title}</h2>
            <p className="card__desc">{action.description}</p>
            {action.path ? (
              <span className="card__arrow">&rarr;</span>
            ) : (
              <span className="card__badge">Coming soon</span>
            )}
          </button>
        ))}
      </main>

      <footer className="dash__footer">
        <p>pii-scanner v0</p>
      </footer>
    </div>
  );
}
