export type Role = "Admin" | "CCO" | "Reviewer" | "Tester" | "Viewer";
export interface Me { username: string; name: string; role: Role; mustChange?: boolean }
export interface ManagedUser { id: number; username: string; name: string; role: Role; active: boolean; mustChange: boolean; locked: boolean; lastLogin: string | null }
export interface Cycle { id: string; name: string; from?: string; to?: string; status: string; version: number; results: Record<string, { st?: string; revStat?: string }> }
export interface LibItem { code: string; req?: string; area?: string }
export interface AppState { settings: { entity?: string }; library: LibItem[]; cycles: Cycle[]; rbiObs: unknown[] }
export interface StateResponse { rev: number; state: AppState; user: Me; unchanged?: boolean }
