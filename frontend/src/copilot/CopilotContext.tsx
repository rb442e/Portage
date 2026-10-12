import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { useApp } from "../store";
import { DATA_CHANGED, type PageContext } from "./api";

interface CopilotCtx {
  open: boolean;
  setOpen: (v: boolean) => void;
  page: PageContext;
  setPageContext: (patch: Partial<PageContext>) => void;
  /** Text queued for the drawer to send (e.g. from a button that asks Sora a question). */
  queued: string;
  ask: (text: string) => void;
  clearQueued: () => void;
}

const Ctx = createContext<CopilotCtx | null>(null);

export function CopilotProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [extra, setExtra] = useState<Partial<PageContext>>({});
  const [queued, setQueued] = useState("");
  const { pathname } = useLocation();
  const { source } = useApp();

  useEffect(() => { setExtra({}); }, [pathname]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((o) => !o); }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const setPageContext = useCallback((patch: Partial<PageContext>) => setExtra((p) => ({ ...p, ...patch })), []);
  const ask = useCallback((text: string) => { setQueued(text); setOpen(true); }, []);
  const clearQueued = useCallback(() => setQueued(""), []);

  const page = useMemo<PageContext>(
    () => ({ route: pathname, source_id: source?.source_id, ...extra }),
    [pathname, source?.source_id, extra],
  );

  return (
    <Ctx.Provider value={{ open, setOpen, page, setPageContext, queued, ask, clearQueued }}>
      {children}
    </Ctx.Provider>
  );
}

export function useCopilot(): CopilotCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useCopilot must be used within CopilotProvider");
  return c;
}

/** Tell the copilot what the user is working on (cleared automatically on navigation). */
export function useCopilotPage(patch: Partial<PageContext>): void {
  const { setPageContext } = useCopilot();
  const key = JSON.stringify(patch);
  useEffect(() => { setPageContext(JSON.parse(key)); }, [key, setPageContext]);
}

/** Run `fn` when the copilot applies a change that touches one of `scopes`. */
export function useDataChanged(scopes: string[], fn: (result: { id?: number; name?: string }) => void): void {
  const key = scopes.join(",");
  useEffect(() => {
    const h = (e: Event) => {
      const d = (e as CustomEvent).detail as { refresh: string[]; result: { id?: number; name?: string } };
      if (d.refresh.some((r) => key.split(",").includes(r))) fn(d.result);
    };
    window.addEventListener(DATA_CHANGED, h);
    return () => window.removeEventListener(DATA_CHANGED, h);
  });  // re-subscribed every render so `fn` is never stale
}
