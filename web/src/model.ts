// Scoring / applicability model – mirrors the classic client (server/static/index.html) so both agree.
import type { AppState, Cycle, LibItem, Result, Role, Settings, Snap, StatusCode } from "./types";

export const STATUS: Record<StatusCode, string> = { NT: "Not tested", C: "Compliant", CO: "Compliant – with observation", PC: "Partially compliant", NC: "Non-compliant", NA: "Not applicable" };
export const TESTED: StatusCode[] = ["C", "CO", "PC", "NC"];
export const REV_OK = "Reviewed – agreed";
export const REV_RET = "Returned for rework";
export const RANK: Record<Role, number> = { Viewer: 0, Tester: 1, Reviewer: 2, CCO: 3, Admin: -1 };
export const CONDS: Record<string, string> = {
  dep: "Deposit-taking NBFC (NBFC-D)", a5k: "Asset size ≥ ₹5,000 crore (LCR, RBIA)", dl: "Digital lending (own app / LSPs)", gold: "Loans against gold / silver",
  las: "Loans against shares / IPO financing", transfer: "Loan transfers (buy / sell)", colend: "Co-lending arrangements", sec: "Securitisation",
  ufs: "Insurance / MF / third-party product distribution", io: "Internal Ombudsman criteria met",
};

type Cfg = Pick<Settings, "mdMult" | "factors" | "conds" | "bands" | "capCritical"> & { lib: Snap["lib"] };
/** Finalised cycles score with their frozen snapshot, others with live settings. */
export function cfg(st: AppState, c: Cycle): Cfg {
  if (c.status === "Finalised" && c.snap) return c.snap;
  const s = st.settings;
  return { mdMult: s.mdMult, factors: s.factors, conds: s.conds, bands: s.bands, capCritical: s.capCritical, lib: null };
}
export const frozen = (k: Cfg, it: LibItem): LibItem => (k.lib && k.lib[it.code]) || it;
export const riskScore = (k: Cfg, it: LibItem) => { const x = frozen(k, it); return x.I * x.L; };
export const riskBand = (s: number) => (s >= 16 ? "Critical" : s >= 10 ? "High" : s >= 5 ? "Medium" : "Low");
export function weight(k: Cfg, it: LibItem) {
  const x = frozen(k, it);
  const base = x.w !== "" && x.w != null && !isNaN(+x.w) ? +x.w : x.I * x.L;
  const m = k.mdMult[it.md];
  return base * (m == null ? 1 : +m);
}
export function applicable(k: Cfg, it: LibItem) {
  if (k.lib && !k.lib[it.code]) return false;
  return !it.cond || !!k.conds[it.cond];
}
export const result = (c: Cycle, code: string): Result => c.results[code] || {};
export function status(k: Cfg, c: Cycle, it: LibItem): StatusCode {
  if (!applicable(k, it)) return "NA";
  return result(c, code(it)).st || "NT";
}
const code = (it: LibItem) => it.code;
export const activeAtt = (r: Result) => (r.att || []).filter((a) => !a.del);

export interface Summary { score: number | null; applicable: number; tested: number; reviewed: number; returned: number; counts: Record<StatusCode, number> }
export function summarise(st: AppState, c: Cycle, items: LibItem[]): Summary {
  const k = cfg(st, c);
  const counts: Record<StatusCode, number> = { NT: 0, C: 0, CO: 0, PC: 0, NC: 0, NA: 0 };
  let W = 0, WF = 0, app = 0, tested = 0, rev = 0, ret = 0;
  for (const it of items) {
    const s = status(k, c, it); counts[s]++;
    if (s === "NA") continue;
    app++;
    if (s === "NT") continue;
    tested++;
    const w = weight(k, it); W += w; WF += w * +k.factors[s];
    const r = result(c, it.code);
    if (r.revStat === REV_OK) rev++;
    if (r.revStat === REV_RET) ret++;
  }
  return { score: W ? (WF / W) * 100 : null, applicable: app, tested, reviewed: rev, returned: ret, counts };
}
