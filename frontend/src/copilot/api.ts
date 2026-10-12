import type { EntryDiff } from "../types";

export interface PageContext {
  route: string;
  mapping_id?: number;
  artifact?: string;
  lookup_kind?: string;
  source_id?: string;
}

export interface MappingDiff {
  artifacts: Record<string, {
    added: Record<string, string[]>;
    removed: Record<string, string[]>;
    changed: Record<string, { from: string[]; to: string[] }>;
  }>;
  summary: string;
}

export interface Proposal {
  id: string;
  tool: string;
  risk: string;
  args: Record<string, any>;
  preview: {
    kind: "mapping" | "catalog";
    title: string;
    summary: string;
    catalog?: string;
    base?: string;
    new_name?: string;
    diff: EntryDiff & MappingDiff;
  };
  status: "pending" | "applied" | "rejected";
  result: { id?: number; name?: string; refresh?: string[] };
}

export type CopilotEvent =
  | { type: "meta"; conversation_id: string; skill: { key: string; label: string } }
  | { type: "token"; text: string }
  | { type: "tool_call"; name: string; args: Record<string, any> }
  | { type: "tool_result"; name: string; ok: boolean; summary: string }
  | { type: "proposal"; proposal: Proposal }
  | { type: "error"; message: string }
  | { type: "done"; conversation_id: string };

export interface CopilotSettings {
  enabled: boolean;
  base_url: string;
  model: string;
  mode: "readonly" | "propose";
  redact: boolean;
  max_steps: number;
}

export interface CopilotStatus {
  settings: CopilotSettings;
  llm: { reachable: boolean; models: string[]; model_available: boolean; detail: string };
}

export interface ConversationSummary { id: string; title: string; updated_at: string; }
export interface StoredMessage { role: "user" | "assistant"; content: string; meta: { skill?: string; tools?: string[]; proposals?: string[] }; }
export interface ConversationDetail extends ConversationSummary { messages: StoredMessage[]; proposals: Proposal[]; }

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/copilot${path}`, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const copilotApi = {
  status: () => json<CopilotStatus>("/status"),
  saveSettings: (patch: Partial<CopilotSettings>) => json<CopilotSettings>("/settings", { method: "PUT", body: JSON.stringify(patch) }),
  suggestions: (route: string) => json<string[]>(`/suggestions?route=${encodeURIComponent(route)}`),
  conversations: () => json<ConversationSummary[]>("/conversations"),
  conversation: (id: string) => json<ConversationDetail>(`/conversations/${id}`),
  deleteConversation: (id: string) => json<unknown>(`/conversations/${id}`, { method: "DELETE" }),
  apply: (id: string) => json<{ proposal: Proposal; result: Proposal["result"] }>(`/proposals/${id}/apply`, { method: "POST" }),
  reject: (id: string) => json<{ proposal: Proposal }>(`/proposals/${id}/reject`, { method: "POST" }),
};

/** POST /chat and dispatch each server-sent event as it arrives. */
export async function streamChat(
  body: { message: string; conversation_id: string; page: PageContext },
  onEvent: (e: CopilotEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/copilot/chat", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      if (frame.startsWith("data: ")) onEvent(JSON.parse(frame.slice(6)) as CopilotEvent);
    }
  }
}

/** Pages listen for this to reload data the copilot just changed. */
export const DATA_CHANGED = "portage:data-changed";
export function notifyDataChanged(refresh: string[], result: Proposal["result"]): void {
  window.dispatchEvent(new CustomEvent(DATA_CHANGED, { detail: { refresh, result } }));
}
