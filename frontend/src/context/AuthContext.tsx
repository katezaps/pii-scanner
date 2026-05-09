import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

/** Fully authenticated session. */
interface AuthState {
  userId: string;
  userName: string | null;
}

interface AuthContextValue {
  auth: AuthState | null;
  loading: boolean;
  error: string | null;
  /** Log in with username + password. Server sets httponly cookie. */
  login: (name: string, password: string) => Promise<void>;
  logout: () => void;
  clearError: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const verifySession = useCallback(async (): Promise<AuthState> => {
    const res = await fetch("/me", { credentials: "include" });
    if (!res.ok) {
      throw new Error("Not authenticated");
    }
    const data = await res.json();
    return { userId: data.user_id, userName: data.name };
  }, []);

  // Check for existing session on mount
  useEffect(() => {
    verifySession()
      .then(setAuth)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [verifySession]);

  const login = useCallback(
    async (name: string, password: string) => {
      setError(null);
      setLoading(true);
      try {
        const res = await fetch("/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ name, password }),
        });
        if (!res.ok) {
          throw new Error("Denied.");
        }
        // Server set the httponly cookie; verify the session
        const state = await verifySession();
        setAuth(state);
      } catch (err) {
        setError("Denied.");
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [verifySession],
  );

  const logout = useCallback(() => {
    fetch("/logout", { method: "POST", credentials: "include" }).catch(() => {});
    setAuth(null);
    setError(null);
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return (
    <AuthContext.Provider
      value={{ auth, loading, error, login, logout, clearError }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
