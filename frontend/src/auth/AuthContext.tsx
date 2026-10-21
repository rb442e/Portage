import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api";
import type { AuthUser, Role } from "../types";
import AuthScreen from "./AuthScreen";

const RANK: Record<Role, number> = { viewer: 0, member: 1, admin: 2 };
export const ROLE_LABEL: Record<Role, string> = { admin: "Admin", member: "Team member", viewer: "Viewer" };

interface AuthState { user: AuthUser; can: (role: Role) => boolean; signOut: () => Promise<void> }
const Ctx = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null | undefined>(undefined);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.me().then((r) => { setUser(r.user); setError(""); })
      .catch((e: Error) => { setUser(null); if (!/sign in/i.test(e.message)) setError(e.message); });
  }, []);

  useEffect(() => {
    load();
    const out = () => setUser(null);
    window.addEventListener("portage:signed-out", out);
    return () => window.removeEventListener("portage:signed-out", out);
  }, [load]);

  const signOut = useCallback(async () => {
    try { await api.logout(); } finally { setUser(null); }
  }, []);

  if (user === undefined) return <div className="auth-loading" aria-busy="true">Loading Portage…</div>;
  if (user === null) return <AuthScreen onSignedIn={setUser} notice={error} />;
  return <Ctx.Provider value={{ user, can: (r) => RANK[user.role] >= RANK[r], signOut }}>{children}</Ctx.Provider>;
}
