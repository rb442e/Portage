import React, { createContext, useContext, useEffect, useState } from "react";
import type { JiraConnection, JiraMetaResult, RallyConnection, SourcePreview } from "./types";
import { api } from "./api";

// Secrets (api_token / api_key) are kept in memory only. Non-secret connection
// details are persisted to localStorage for convenience.
const NON_SECRET_KEY = "portage.connections.v1";

const emptyJira: JiraConnection = {
  base_url: "", email: "", api_token: "", deployment: "cloud", project_key: "",
  sprint_field: "", story_points_field: "", team_field: "", epic_link_field: "",
  rally_id_field: "",
};
const emptyRally: RallyConnection = { base_url: "https://rally1.rallydev.com", api_key: "", project_object_id: "" };

interface AppState {
  jira: JiraConnection;
  rally: RallyConnection;
  setJira: (j: Partial<JiraConnection>) => void;
  setRally: (r: Partial<RallyConnection>) => void;
  jiraVerified: boolean;
  rallyVerified: boolean;
  setJiraVerified: (v: boolean) => void;
  setRallyVerified: (v: boolean) => void;
  connectionsSaved: boolean;
  connectionsSavedAt: string;
  saveConnections: () => Promise<void>;
  forgetConnections: () => Promise<void>;
  source: SourcePreview | null;
  setSource: (s: SourcePreview | null) => void;
  jiraMeta: JiraMetaResult | null;
  setJiraMeta: (m: JiraMetaResult | null) => void;
}

const Ctx = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [jira, setJiraState] = useState<JiraConnection>(emptyJira);
  const [rally, setRallyState] = useState<RallyConnection>(emptyRally);
  const [jiraVerified, setJiraVerified] = useState(false);
  const [rallyVerified, setRallyVerified] = useState(false);
  const [connectionsSaved, setConnectionsSaved] = useState(false);
  const [connectionsSavedAt, setConnectionsSavedAt] = useState("");
  const [source, setSource] = useState<SourcePreview | null>(null);
  const [jiraMeta, setJiraMeta] = useState<JiraMetaResult | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(NON_SECRET_KEY);
      if (raw) {
        const saved = JSON.parse(raw);
        setJiraState((j) => ({ ...j, ...saved.jira, api_token: "" }));
        setRallyState((r) => ({ ...r, ...saved.rally, api_key: "" }));
      }
    } catch { /* ignore */ }
    // Server-saved profile (secrets encrypted at rest) takes precedence and
    // restores the API keys into memory so they survive a browser reload.
    api.savedConnections().then((s) => {
      if (!s.saved) return;
      if (s.jira) setJiraState((j) => ({ ...j, ...s.jira! }));
      if (s.rally) setRallyState((r) => ({ ...r, ...s.rally! }));
      setConnectionsSaved(true);
      setConnectionsSavedAt(s.saved_at);
    }).catch(() => { /* backend may be down */ });
  }, []);

  const persist = (j: JiraConnection, r: RallyConnection) => {
    const { api_token, ...jiraSafe } = j;
    const { api_key, ...rallySafe } = r;
    localStorage.setItem(NON_SECRET_KEY, JSON.stringify({ jira: jiraSafe, rally: rallySafe }));
  };

  const setJira = (patch: Partial<JiraConnection>) => {
    setJiraState((prev) => {
      const next = { ...prev, ...patch };
      persist(next, rally);
      return next;
    });
    setJiraVerified(false);
  };
  const setRally = (patch: Partial<RallyConnection>) => {
    setRallyState((prev) => {
      const next = { ...prev, ...patch };
      persist(jira, next);
      return next;
    });
    setRallyVerified(false);
  };

  const saveConnections = async () => {
    const s = await api.saveConnections(jira, rally);
    setConnectionsSaved(s.saved);
    setConnectionsSavedAt(s.saved_at);
  };
  const forgetConnections = async () => {
    await api.forgetConnections();
    setConnectionsSaved(false);
    setConnectionsSavedAt("");
  };

  return (
    <Ctx.Provider value={{
      jira, rally, setJira, setRally,
      jiraVerified, rallyVerified, setJiraVerified, setRallyVerified,
      connectionsSaved, connectionsSavedAt, saveConnections, forgetConnections,
      source, setSource,
      jiraMeta, setJiraMeta,
    }}>
      {children}
    </Ctx.Provider>
  );
}

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}
