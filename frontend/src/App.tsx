import { NavLink, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import { useApp } from "./store";
import Dashboard from "./pages/Dashboard";
import Connections from "./pages/Connections";
import MappingStudio from "./pages/MappingCanvas";
import Lookups from "./pages/Lookups";
import Migrate from "./pages/Migrate";
import Attachments from "./pages/Attachments";
import Reports from "./pages/Reports";
import Exports from "./pages/Exports";
import SplitFile from "./pages/SplitFile";
import CopyDescription from "./pages/CopyDescription";

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
};

const NAV: { to: string; label: string; icon: ReactNode; end?: boolean }[] = [
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
];

function StatusPill({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span className="pill-status">
      <span className={`dot ${ok ? "ok" : "idle"}`} /> {label}
    </span>
  );
}

export default function App() {
  const { jiraVerified, rallyVerified } = useApp();
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
        {NAV.map((n) => (
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
          </div>
        </header>
        <div className="content">
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
          </Routes>
        </div>
      </div>
    </div>
  );
}
