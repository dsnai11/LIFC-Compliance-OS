import type { ManagedUser, Me, StateResponse } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: { "X-CCT": "1", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, typeof data.detail === "string" ? data.detail : `Request failed (${r.status})`);
  return data as T;
}

export const api = {
  bootstrap: () => call<{ setupNeeded: boolean }>("GET", "/api/bootstrap"),
  setup: (username: string, name: string, password: string) => call("POST", "/api/setup", { username, name, password }),
  login: (username: string, password: string) => call<{ user: Me }>("POST", "/api/login", { username, password }),
  logout: () => call("POST", "/api/logout"),
  me: () => call<{ user: Me }>("GET", "/api/me"),
  changePassword: (old: string, next: string) => call("POST", "/api/password", { old, new: next }),
  state: () => call<StateResponse>("GET", "/api/state"),
  users: () => call<{ users: ManagedUser[] }>("GET", "/api/users"),
  createUser: (username: string, name: string, role: string) => call<{ tempPassword: string }>("POST", "/api/users", { username, name, role }),
  updateUser: (id: number, patch: Record<string, unknown>) => call<{ tempPassword?: string }>("POST", `/api/users/${id}`, patch),
};
