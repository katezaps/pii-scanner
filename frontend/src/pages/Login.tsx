import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import "./Login.css";

export default function Login() {
  const { error, loading, login } = useAuth();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || !password) return;
    try {
      await login(name.trim(), password);
    } catch {
      // error surfaced via context
    }
  }

  return (
    <div className="login">
      <div className="login__glow" />
      <div className="login__card">
        <h1 className="login__title">Broker Audit</h1>
        <p className="login__subtitle">Sign in with your credentials</p>

        <form className="login__form" onSubmit={handleSubmit}>
          <label className="login__label" htmlFor="name">
            Username
          </label>
          <input
            id="name"
            className="login__input"
            type="text"
            placeholder="your username"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
            autoComplete="username"
          />

          <label className="login__label" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            className="login__input"
            type="password"
            placeholder="your password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />

          {error && <p className="login__error">{error}</p>}

          <button
            className="login__submit"
            type="submit"
            disabled={loading || !name.trim() || !password}
          >
            {loading ? "Verifying\u2026" : "Log in"}
          </button>
        </form>

        <p className="login__switch">
          Don't have an account? <Link to="/signup">Sign up</Link>
        </p>
      </div>
    </div>
  );
}
