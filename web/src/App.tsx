import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api";
import type { ManagedUser, Me } from "./types";
import { summarise } from "./model";
import { StoreProvider, useStore } from "./store";
import Testing from "./Testing";

type Phase = "loading" | "setup" | "login" | "mustChange" | "app";
const msg = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : "Something went wrong");

function Field(p: { label: string; value: string; onChange: (v: string) => void; type?: string; auto?: string }) {
  return (<><label>{p.label}</label><input type={p.type ?? "text"} value={p.value} autoComplete={p.auto} autoCapitalize="none" autoCorrect="off" spellCheck={false} onChange={(e) => p.onChange(e.target.value)} /></>);
}

function Setup({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState(""), [user, setUser] = useState(""), [pw, setPw] = useState(""), [pw2, setPw2] = useState(""), [err, setErr] = useState("");
  const go = async () => {
    if (pw !== pw2) return setErr("Passwords do not match.");
    try { await api.setup(user.trim(), name.trim(), pw); onDone(); } catch (e) { setErr(msg(e)); }
  };
  return (<div className="center"><div className="card"><h1>First-time setup</h1>
    <p className="hint">Create the administrator account. The administrator manages users and roles only.</p>
    <Field label="Full name" value={name} onChange={setName} /><Field label="Username" value={user} onChange={setUser} auto="username" />
    <Field label="Password" type="password" value={pw} onChange={setPw} auto="new-password" /><Field label="Confirm password" type="password" value={pw2} onChange={setPw2} auto="new-password" />
    <p className="hint">At least 10 characters with three of: lower case, upper case, digit, symbol.</p>{err && <p className="err">{err}</p>}
    <button className="full" onClick={go}>Create administrator</button></div></div>);
}

function Login({ onDone }: { onDone: (u: Me) => void }) {
  const [user, setUser] = useState(""), [pw, setPw] = useState(""), [err, setErr] = useState(""), [busy, setBusy] = useState(false);
  const go = async () => { setBusy(true); setErr(""); try { onDone((await api.login(user.trim(), pw)).user); } catch (e) { setErr(msg(e)); } setBusy(false); };
  return (<div className="center"><form className="card" onSubmit={(e) => { e.preventDefault(); void go(); }}><h1>LIFC Compliance OS</h1>
    <Field label="Username" value={user} onChange={setUser} auto="username" /><Field label="Password" type="password" value={pw} onChange={setPw} auto="current-password" />
    {err && <p className="err">{err}</p>}<button className="full" disabled={busy}>Sign in</button>
    <p className="hint" style={{ textAlign: "center", marginTop: 14 }}>Authorised users only. All access and changes are logged.</p></form></div>);
}

function ChangePassword({ onDone }: { onDone: () => void }) {
  const [old, setOld] = useState(""), [n1, setN1] = useState(""), [n2, setN2] = useState(""), [err, setErr] = useState("");
  const go = async () => { if (n1 !== n2) return setErr("Passwords do not match."); try { await api.changePassword(old, n1); onDone(); } catch (e) { setErr(msg(e)); } };
  return (<div className="center"><div className="card"><h1>Choose a new password</h1><p className="hint">Your temporary password must be changed before you continue.</p>
    <Field label="Current (temporary) password" type="password" value={old} onChange={setOld} auto="current-password" />
    <Field label="New password" type="password" value={n1} onChange={setN1} auto="new-password" /><Field label="Confirm new password" type="password" value={n2} onChange={setN2} auto="new-password" />
    {err && <p className="err">{err}</p>}<button className="full" onClick={go}>Change password</button></div></div>);
}

function Cycles() {
  const { state } = useStore();
  if (!state) return <p className="hint">Loading…</p>;
  return (<><h2>Testing cycles</h2>{state.cycles.length === 0 ? <p className="hint">No cycles yet – a Reviewer or the CCO creates one in the classic client (Setup &amp; Workflow).</p> :
    <table><thead><tr><th>Cycle</th><th>Status</th><th>Version</th><th>Tested / applicable</th><th>Reviewed</th></tr></thead><tbody>
      {state.cycles.map((c) => { const s = summarise(state, c, state.library);
        return <tr key={c.id}><td>{c.name}{c.demo ? " (demo)" : ""}</td><td>{c.status}</td><td>v{c.version}</td><td>{s.tested} / {s.applicable}</td><td>{s.reviewed}</td></tr>; })}
    </tbody></table>}
    <p className="hint" style={{ marginTop: 12 }}>Scoring, the dashboard and the inspection report are still being ported from the classic client (available at /).</p></>);
}

function Users() {
  const [users, setUsers] = useState<ManagedUser[]>([]), [err, setErr] = useState(""), [temp, setTemp] = useState("");
  const [un, setUn] = useState(""), [nm, setNm] = useState(""), [role, setRole] = useState("Tester");
  const load = useCallback(() => api.users().then((r) => setUsers(r.users)).catch((e) => setErr(msg(e))), []);
  useEffect(() => { void load(); }, [load]);
  const add = async () => { setErr(""); try { const r = await api.createUser(un.trim(), nm.trim(), role); setTemp(`${un.trim()}: ${r.tempPassword}`); setUn(""); setNm(""); void load(); } catch (e) { setErr(msg(e)); } };
  const act = async (id: number, patch: Record<string, unknown>) => { setErr(""); try { const r = await api.updateUser(id, patch); if (r.tempPassword) setTemp(`Temporary password: ${r.tempPassword}`); void load(); } catch (e) { setErr(msg(e)); } };
  return (<><h2>Users</h2>{err && <p className="err">{err}</p>}{temp && <div className="note">One-time temporary password — {temp}. Share it securely; it is shown only now.</div>}
    <div className="row"><div><Field label="Username" value={un} onChange={setUn} /></div><div><Field label="Full name" value={nm} onChange={setNm} /></div>
      <div><label>Role</label><select value={role} onChange={(e) => setRole(e.target.value)}>{["Tester", "Reviewer", "CCO", "Viewer", "Admin"].map((r) => <option key={r}>{r}</option>)}</select></div>
      <div><button onClick={add}>Add user</button></div></div>
    <table><thead><tr><th>User</th><th>Role</th><th>Status</th><th /></tr></thead><tbody>{users.map((u) => (
      <tr key={u.id}><td>{u.name} <span className="hint">({u.username})</span></td><td>{u.role}</td><td>{!u.active ? "Disabled" : u.locked ? "Locked" : u.mustChange ? "Temp password" : "Active"}</td>
        <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
          <button className="ghost" onClick={() => act(u.id, { reset: true })}>Reset</button>{" "}
          {u.locked && <><button className="ghost" onClick={() => act(u.id, { unlock: true })}>Unlock</button>{" "}</>}
          <button className="ghost" onClick={() => act(u.id, { active: !u.active })}>{u.active ? "Disable" : "Enable"}</button></td></tr>))}</tbody></table></>);
}

function Shell({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const admin = me.role === "Admin";
  const [view, setView] = useState<"testing" | "cycles" | "users">(admin ? "users" : "testing");
  const nav = (v: typeof view, label: string) => <button className={view === v ? "on" : ""} onClick={() => setView(v)}>{label}</button>;
  const body = view === "users" ? <Users /> : view === "cycles" ? <Cycles /> : <Testing />;
  const frame = (<div className="shell"><nav className="side"><b>LIFC Compliance OS</b>
    {admin ? nav("users", "Users") : <>{nav("testing", "Testing")}{nav("cycles", "Cycles")}</>}
    <div className="who">{me.name} · {me.role}</div><button onClick={onLogout}>Sign out</button></nav>
    <main>{body}</main></div>);
  return admin ? frame : <StoreProvider me={me}>{frame}</StoreProvider>;
}

export default function App() {
  const [phase, setPhase] = useState<Phase>("loading"), [me, setMe] = useState<Me | null>(null);
  const boot = useCallback(async () => {
    try {
      if ((await api.bootstrap()).setupNeeded) return setPhase("setup");
      const u = (await api.me()).user; setMe(u); setPhase(u.mustChange ? "mustChange" : "app");
    } catch { setPhase("login"); }
  }, []);
  useEffect(() => { void boot(); }, [boot]);
  useEffect(() => { window.scrollTo(0, 0); }, [phase]);  // keyboard leaves the page scrolled on phones
  if (phase === "loading") return <div className="center"><p className="hint">Loading…</p></div>;
  if (phase === "setup") return <Setup onDone={() => setPhase("login")} />;
  if (phase === "login") return <Login onDone={(u) => { setMe(u); setPhase(u.mustChange ? "mustChange" : "app"); }} />;
  if (phase === "mustChange") return <ChangePassword onDone={() => void boot()} />;
  return <Shell me={me!} onLogout={async () => { await api.logout(); setMe(null); setPhase("login"); }} />;
}
