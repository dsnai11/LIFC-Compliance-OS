export type Role = "Admin" | "CCO" | "Reviewer" | "Tester" | "Viewer";
export interface Me { username: string; name: string; role: Role; mustChange?: boolean }
export interface ManagedUser { id: number; username: string; name: string; role: Role; active: boolean; mustChange: boolean; locked: boolean; lastLogin: string | null }

export type StatusCode = "NT" | "C" | "CO" | "PC" | "NC" | "NA";
export interface Attachment { id: string; name: string; size: number; mime?: string; sha?: string; by?: string; at?: string; del?: boolean; delBy?: string; delReason?: string }
export interface Result {
  st?: StatusCode; date?: string; pop?: string; sample?: string; exc?: string; ev?: string; tester?: string;
  obs?: string; rc?: string; mgmt?: string; owner?: string; due?: string; act?: string; closed?: string;
  revStat?: string; revNote?: string; revBy?: string; revOn?: string; att?: Attachment[];
  prior?: { cycle: string; st: string; obs?: string; mgmt?: string };
}
export interface LibItem {
  code: string; md: string; area: string; req: string; proc?: string; evid?: string; freq?: string; dept?: string;
  cond?: string; I: number; L: number; w?: number | string | null; ref?: string; custom?: boolean;
}
export interface Settings {
  entity?: string; requireProof?: boolean; conds: Record<string, boolean>; factors: Record<string, number>;
  bands: { strong: number; sat: number; ni: number }; mdMult: Record<string, number>; capCritical?: boolean;
}
export interface Snap { mdMult: Record<string, number>; factors: Record<string, number>; conds: Record<string, boolean>; bands: Settings["bands"]; capCritical?: boolean; lib: Record<string, LibItem> | null }
export interface Cycle { id: string; name: string; from?: string; to?: string; status: string; version: number; demo?: boolean; snap?: Snap; results: Record<string, Result> }
export interface MasterDirection { k: string; t: string }
export interface AppState { settings: Settings; library: LibItem[]; cycles: Cycle[]; rbiObs: unknown[]; mds: MasterDirection[]; mdRef: Record<string, { circ?: string; date?: string }> }
export interface StateResponse { rev: number; state: AppState; user: Me; unchanged?: boolean; rejected?: { path?: unknown[]; reason: string }[] }
