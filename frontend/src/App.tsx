import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useApp } from "./store";
import { ROLE_LABEL, useAuth } from "./auth/AuthContext";
import type { Role } from "./types";
import Users from "./pages/Users";
import Dashboard from "./pages/Dashboard";
import Connections from "./pages/Connections";
import MappingStudio from "./pages/MappingCanvas";
import Lookups from "./pages/Lookups";
import Migrate from "./pages/Migrate";
import Attachments from "./pages/Attachments";
import Reports from "./pages/Reports";
import Exports from "./pages/Exports";
import Settings from "./pages/Settings";
import SplitFile from "./pages/SplitFile";
import CopyDescription from "./pages/CopyDescription";
import CopilotDrawer from "./copilot/CopilotDrawer";
import SoraIcon from "./copilot/SoraIcon";
import { useCopilot } from "./copilot/CopilotContext";

const s = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
const NavIcon = {
  dashboard: (<svg width="18" height="18" viewBox="0 0 24 24" {...s}><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></svg>),
  connections: (<svg width="18" height="18" viewBox="0 0 24 24" {...s}><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" /><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" /></svg>),
  mapping: (<svg width="18" height="18" viewBox="0 0 24 24" {...s}><rect x="3" y="4" width="6" height="6" rx="1.5" /><rect x="15" y="14" width="6" height="6" rx="1.5" /><path d="M9 7h4a3 3 0 0 1 3 3v4" /></svg>),
  catalog: (<svg width="18" height="18" viewBox="0 0 24 24" {...s}><path d="M4 6h16M4 12h16M4 18h16" /><circle cx="4" cy="6" r="0.5" fill="currentColor" /></svg>),
  migrate: (<svg width="18" height="18" viewBox="0 0 24 24" {...s}><path d="M5 12h14M13 6l6 6-6 6" /></svg>),
  exports: (<svg width="18" height="18" viewBox="0 0 24 24" {...s}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M8 13h8M8 17h8" /></svg>),
  attachments: (<svg width="18" height="18" viewBox="0 0 24 24" {...s}><path d="M21.44 11.05 12.25 20.24a5 5 0 0 1-7.07-7.07l9.19-9.19a3.5 3.5 0 0 1 4.95 4.95l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" /></svg>),
  reports: (<svg width="18" height="18" viewBox="0 0 24 24" {...s}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></svg>),
  split: (<svg width="18" height="18" viewBox="0 0 24 24" {...s}><circle cx="6" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M20 4 8.12 15.88M14.47 14.48 20 20M8.12 8.12 12 12" /></svg>),
  copydesc: (<svg width="18" height="18" viewBox="0 0 24 24" {...s}><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>),
  settings: (<svg width="18" height="18" viewBox="0 0 24 24" {...s}><path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h12M20 18h0" /><circle cx="16" cy="6" r="2" /><circle cx="8" cy="12" r="2" /><circle cx="18" cy="18" r="2" /></svg>),
  users: (<svg width="18" height="18" viewBox="0 0 24 24" {...s}><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6" /></svg>),
};

const NAV: { to: string; label: string; icon: ReactNode; end?: boolean; role?: Role }[] = [
  { to: "/", label: "Dashboard", icon: NavIcon.dashboard, end: true },
  { to: "/connections", label: "Connections", icon: NavIcon.connections },
  { to: "/mapping", label: "Mapping Studio", icon: NavIcon.mapping },
  { to: "/lookups", label: "Jira Catalog", icon: NavIcon.catalog },
  { to: "/migrate", label: "Migrate", icon: NavIcon.migrate },
  { to: "/attachments", label: "Attachments", icon: NavIcon.attachments },
  { to: "/exports", label: "Exports", icon: NavIcon.exports },
  { to: "/split", label: "Split File", icon: NavIcon.split },
  { to: "/copy-description", label: "Copy Description", icon: NavIcon.copydesc },
  { to: "/reports", label: "Reports", icon: NavIcon.reports },
  { to: "/settings", label: "Settings", icon: NavIcon.settings, role: "admin" },
  { to: "/users", label: "Users", icon: NavIcon.users, role: "admin" },
];

function StatusPill({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span className="pill-status">
      <span className={`dot ${ok ? "ok" : "idle"}`} /> {label}
    </span>
  );
}

function UserMenu() {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  if (user.auth_disabled) return <span className="badge warn" title="PORTAGE_AUTH_DISABLED is set">Sign-in off</span>;
  return (
    <div className="um-menu" ref={ref}>
      <button className="um-trigger" onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open}>
        <span className="um-avatar">{(user.name || user.email)[0].toUpperCase()}</span>
        <span className={`um-badge ${user.role}`}>{ROLE_LABEL[user.role]}</span>
      </button>
      {open && (
        <div className="um-pop" role="menu">
          <div className="um-pop-head">
            <div className="um-email">{user.name || user.email}</div>
            <div className="um-meta">{user.name ? `${user.email} · ` : ""}{ROLE_LABEL[user.role]}</div>
          </div>
          <button role="menuitem" className="um-pop-item" onClick={() => void signOut()}>Sign out</button>
        </div>
      )}
    </div>
  );
}

export default function App() {
  const { jiraVerified, rallyVerified } = useApp();
  const { open, setOpen } = useCopilot();
  const { can } = useAuth();
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">P</div>
          <div>
            <div className="brand-name">Portage</div>
            <div className="brand-tag">carry your work across</div>
          </div>
        </div>
        <div className="nav-section">Workspace</div>
        {NAV.filter((n) => !n.role || can(n.role)).map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end}
            className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
            <span className="nav-icon">{n.icon}</span> {n.label}
          </NavLink>
        ))}
        <div className="sidebar-footer">
          Portage v0.1 · self-hosted<br />ALM migration platform
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <h1>Rally → Jira Migration</h1>
          <div className="row" style={{ gap: 18 }}>
            <StatusPill label="Rally source" ok={rallyVerified} />
            <StatusPill label="Jira target" ok={jiraVerified} />
            <button className={`cp-ask ${open ? "on" : ""}`} onClick={() => setOpen(!open)} title="Ask Sora (Ctrl/Cmd+K)" aria-label="Ask Sora">
              <SoraIcon size={22} /> Ask Sora
            </button>
            <UserMenu />
          </div>
        </header>
        <div className="content">
          {!can("member") && (
            <div className="um-viewonly" role="note">You have view-only access. Ask an admin if you need to make changes.</div>
          )}
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/connections" element={<Connections />} />
            <Route path="/mapping" element={<MappingStudio />} />
            <Route path="/lookups" element={<Lookups />} />
            <Route path="/migrate" element={<Migrate />} />
            <Route path="/attachments" element={<Attachments />} />
            <Route path="/exports" element={<Exports />} />
            <Route path="/split" element={<SplitFile />} />
            <Route path="/copy-description" element={<CopyDescription />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/settings" element={can("admin") ? <Settings /> : <Navigate to="/" replace />} />
            <Route path="/users" element={can("admin") ? <Users /> : <Navigate to="/" replace />} />
          </Routes>
        </div>
      </div>
      <CopilotDrawer />
    </div>
  );
}
