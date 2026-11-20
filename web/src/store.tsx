import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "./api";
import type { AppState, Me, StateResponse } from "./types";

interface Ctx {
  state: AppState | null; me: Me; rev: number; cycleId: string; setCycleId: (id: string) => void;
  notice: string; say: (m: string) => void; busy: boolean;
  /** Save one field of one requirement result. Sends immediately; the server answers with the authoritative state. */
  setField: (code: string, field: string, value: unknown) => Promise<void>;
  apply: (r: StateResponse) => void;
}
const C = createContext<Ctx | null>(null);
export const useStore = () => { const v = useContext(C); if (!v) throw new Error("store"); return v; };

export function StoreProvider({ me, children }: { me: Me; children: ReactNode }) {
  const [state, setState] = useState<AppState | null>(null);
  const [rev, setRev] = useState(-1);
  const [cycleId, setCycleId] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const pending = useRef(0);
  const say = useCallback((m: string) => { setNotice(m); window.setTimeout(() => setNotice((x) => (x === m ? "" : x)), 6000); }, []);

  const apply = useCallback((r: StateResponse) => {
    if (r.unchanged) return;
    setState(r.state); setRev(r.rev);
    setCycleId((cur) => (cur && r.state.cycles.some((c) => c.id === cur) ? cur : r.state.cycles[0]?.id ?? ""));
    if (r.rejected?.length) say(`⚠ ${r.rejected[0].reason}${r.rejected.length > 1 ? ` (+${r.rejected.length - 1} more)` : ""}`);
  }, [say]);

  useEffect(() => { api.state().then(apply).catch((e) => say(e instanceof ApiError ? e.message : "Could not load data")); }, [apply, say]);

  // Poll for other users' changes, but never while saving or while someone is typing.
  useEffect(() => {
    const t = window.setInterval(() => {
      const a = document.activeElement;
      if (pending.current || (a && /INPUT|TEXTAREA|SELECT/.test(a.tagName))) return;
      api.state(rev).then(apply).catch(() => undefined);
    }, 30000);
    return () => window.clearInterval(t);
  }, [rev, apply]);

  const setField = useCallback((code: string, field: string, value: unknown) => {
    // Serialise saves so edits reach the server in the order they were made.
    pending.current++; setBusy(true);
    const run = chain.current.then(() => api.ops(cycleId, [{ op: "set", path: ["cycles", cycleId, "results", code, field], value }]).then(apply))
      .catch((e) => say(e instanceof ApiError ? e.message : "Not saved – check your connection"))
      .finally(() => { if (--pending.current === 0) setBusy(false); });
    chain.current = run;
    return run as Promise<void>;
  }, [cycleId, apply, say]);

  return <C.Provider value={{ state, me, rev, cycleId, setCycleId, notice, say, busy, setField, apply }}>{children}</C.Provider>;
}
