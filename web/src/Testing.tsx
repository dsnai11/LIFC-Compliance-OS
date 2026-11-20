import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { CONDS, REV_OK, REV_RET, RANK, STATUS, TESTED, activeAtt, applicable, cfg, result, riskBand, riskScore, status, summarise, weight } from "./model";
import { useStore } from "./store";
import type { Attachment, Cycle, LibItem, Result, StatusCode } from "./types";

const fmt = (n: number) => (Math.round(n * 10) / 10).toString();
const sameName = (a: string | undefined, me: { name: string; username: string }) => {
  const x = (a || "").trim().toLowerCase();
  return !!x && (x === me.name.trim().toLowerCase() || x === me.username.trim().toLowerCase());
};

/** Text input that keeps a local draft and saves on blur / after a short pause. */
function Field(p: { code: string; field: keyof Result; label: string; value?: string; type?: "text" | "date" | "area"; disabled?: boolean }) {
  const { setField } = useStore();
  const [draft, setDraft] = useState(p.value ?? "");
  const focused = useRef(false);
  const timer = useRef<number>();
  useEffect(() => { if (!focused.current) setDraft(p.value ?? ""); }, [p.value]);
  const commit = (v: string) => { window.clearTimeout(timer.current); if (v !== (p.value ?? "")) void setField(p.code, p.field, v); };
  const on = (v: string) => { setDraft(v); window.clearTimeout(timer.current); timer.current = window.setTimeout(() => commit(v), 900); };
  const common = { value: draft, disabled: p.disabled, onFocus: () => { focused.current = true; }, onBlur: () => { focused.current = false; commit(draft); }, autoCapitalize: "sentences" as const };
  return (<div><label>{p.label}</label>{p.type === "area"
    ? <textarea {...common} rows={3} onChange={(e) => on(e.target.value)} />
    : <input {...common} type={p.type ?? "text"} onChange={(e) => on(e.target.value)} />}</div>);
}

function Evidence({ cycle, it, r, locked }: { cycle: Cycle; it: LibItem; r: Result; locked: boolean }) {
  const { apply, say, state } = useStore();
  const [up, setUp] = useState(false), [rm, setRm] = useState<string | null>(null), [why, setWhy] = useState("");
  const st = r.st || "NT", act = activeAtt(r), need = TESTED.includes(st) && !act.length && state?.settings.requireProof !== false;
  const upload = async (files: FileList | null) => {
    if (!files?.length) return; setUp(true);
    for (const f of Array.from(files)) {
      if (f.size > 25 * 1048576) { say(`${f.name} exceeds 25 MB`); continue; }
      try { apply(await api.upload(cycle.id, it.code, f)); } catch (e) { say(e instanceof ApiError ? e.message : "Upload failed"); }
    }
    setUp(false);
  };
  const remove = async (a: Attachment) => {
    if (!why.trim()) return say("Enter a reason for removing this evidence.");
    try { apply(await api.deleteAttachment(a.id, why.trim())); setRm(null); setWhy(""); } catch (e) { say(e instanceof ApiError ? e.message : "Could not remove"); }
  };
  return (<div className={"evid" + (need ? " need" : "")}>
    <h4>📎 Proof / evidence <span className="badge">{act.length} file(s)</span>{need && <span className="bad"> Attach proof for this {STATUS[st as StatusCode].toLowerCase()} result</span>}</h4>
    {(r.att || []).length === 0 && <p className="hint">No evidence attached yet.</p>}
    {(r.att || []).map((a) => (<div key={a.id} className={"file" + (a.del ? " del" : "")}>
      <a href={`/api/attach/${a.id}`} target="_blank" rel="noopener">{a.name}</a>
      <div className="hint">{Math.max(1, Math.round((a.size || 0) / 1024))} KB · {a.by} · SHA-256 {(a.sha || "").slice(0, 10)}…{a.del ? ` · removed by ${a.delBy}: ${a.delReason ?? ""}` : ""}</div>
      {!a.del && !locked && (rm === a.id
        ? <div className="row"><div><input placeholder="Reason for removal" value={why} onChange={(e) => setWhy(e.target.value)} /></div><button className="ghost" onClick={() => remove(a)}>Remove</button><button className="ghost" onClick={() => setRm(null)}>Cancel</button></div>
        : <button className="ghost small" onClick={() => setRm(a.id)}>Remove…</button>)}
    </div>))}
    {!locked && (<div className="row">
      <label className="btn">📎 Attach files<input type="file" multiple hidden onChange={(e) => { void upload(e.target.files); e.target.value = ""; }} /></label>
      <label className="btn ghost">📷 Take photo<input type="file" accept="image/*" capture="environment" hidden onChange={(e) => { void upload(e.target.files); e.target.value = ""; }} /></label>
      {up && <span className="hint">Uploading…</span>}
    </div>)}
    <p className="hint">PDF, images, Office, e-mail, ZIP · max 25 MB each · SHA-256 fingerprint recorded by the server.</p>
  </div>);
}

function Review({ it, r, locked }: { it: LibItem; r: Result; locked: boolean }) {
  const { me, setField, say, state } = useStore();
  const can = RANK[me.role] >= 2 && !locked;
  const mine = sameName(r.tester, me);
  const pick = (v: string) => {
    // Friendly pre-checks; the server enforces all of these again.
    if (v) {
      const st = r.st || "NT";
      if (st === "NT" || st === "NA") return say("Record a test status before review.");
      if (mine) return say(`Maker-checker control: you tested ${it.code} and cannot review it.`);
      if (v === REV_OK && state?.settings.requireProof !== false && TESTED.includes(st) && !activeAtt(r).length) return say(`Proof required: attach evidence to ${it.code} before agreeing the review.`);
      if (v === REV_RET && !(r.revNote || "").trim()) return say("Add reviewer comments first, then return the item.");
    }
    void setField(it.code, "revStat", v);
  };
  return (<div className="revbox"><h4>Review (checker)</h4>
    <div className="grid2"><div><label>Review status</label>
      <select disabled={!can} value={r.revStat || ""} onChange={(e) => pick(e.target.value)}>
        <option value="">– Not reviewed –</option><option>{REV_OK}</option><option>{REV_RET}</option></select>
      {can && mine && <p className="hint">You tested this item, so you can't review it (maker-checker).</p>}
      {!can && !locked && <p className="hint">Only a Reviewer or the CCO can record the review.</p>}</div>
      <div><label>Reviewed by / on</label><p>{r.revBy || "–"} {r.revOn ? `· ${r.revOn}` : ""}</p></div></div>
    <Field code={it.code} field="revNote" label="Reviewer comments" type="area" value={r.revNote} disabled={!can} />
  </div>);
}

function Card({ cycle, it, open, toggle }: { cycle: Cycle; it: LibItem; open: boolean; toggle: () => void }) {
  const { state, me, setField } = useStore();
  const st0 = state!, k = cfg(st0, cycle), r = result(cycle, it.code), st = status(k, cycle, it);
  const auto = !applicable(k, it), rs = riskScore(k, it), locked = cycle.status === "Finalised" || RANK[me.role] < 1;
  const na = activeAtt(r).length, tested = st !== "NT" && st !== "NA";
  const mdTitle = st0.mds.find((m) => m.k === it.md)?.t ?? it.md;
  const circ = st0.mdRef[it.md];
  return (<article className="req">
    <div className="reqhead">
      <button className="reqtext" onClick={toggle} aria-expanded={open}>
        <b>{it.code}</b> <span className="muted">· {it.area}</span>
        <span className="reqline">{it.req}{r.obs ? " " : ""}{r.obs && <span className="badge pc">obs</span>}{r.prior && <span className="badge"> c/f</span>}</span>
      </button>
      <div className="reqmeta">
        <span className={"badge r-" + riskBand(rs)}>{riskBand(rs)} · {rs}</span>
        <span className="hint">wt {fmt(weight(k, it))}</span>
        {auto ? <span className="badge">N/A (auto)</span>
          : <select className={"st s-" + st} disabled={locked} value={st} onChange={(e) => void setField(it.code, "st", e.target.value)} aria-label={`Status for ${it.code}`}>
            {(Object.keys(STATUS) as StatusCode[]).map((s) => <option key={s} value={s}>{STATUS[s]}</option>)}</select>}
        {r.revStat === REV_OK ? <span className="badge ok">✓ reviewed</span> : r.revStat === REV_RET ? <span className="badge bad">↩ returned</span> : tested ? <span className="badge">pending review</span> : null}
        {na ? <span className="badge">📎 {na}</span> : TESTED.includes(st) ? <span className="badge bad">proof missing</span> : null}
      </div>
    </div>
    {open && (<div className="detail">
      <div className="grid3">
        <div><label>Regulatory reference</label><p className="small">{[mdTitle, circ?.circ, circ?.date ? `dated ${circ.date}` : "", it.ref ? `Para/Clause: ${it.ref}` : ""].filter(Boolean).join(" · ")}</p></div>
        <div><label>Test procedure</label><p className="small">{it.proc}</p></div>
        <div><label>Evidence expected</label><p className="small">{it.evid}{it.cond ? <><br /><span className="muted">Applicability condition: {CONDS[it.cond] ?? it.cond}</span></> : null}</p></div>
      </div>
      {r.prior && <div className="note">Carried forward from {r.prior.cycle}: {STATUS[r.prior.st as StatusCode] ?? r.prior.st}{r.prior.obs ? ` – ${r.prior.obs}` : ""}{r.prior.mgmt ? ` | Mgmt: ${r.prior.mgmt}` : ""}</div>}
      <div className="grid3">
        <Field code={it.code} field="date" label="Test date" type="date" value={r.date} disabled={locked} />
        <Field code={it.code} field="pop" label="Population" value={r.pop} disabled={locked} />
        <Field code={it.code} field="sample" label="Sample size" value={r.sample} disabled={locked} />
        <Field code={it.code} field="exc" label="Exceptions" value={r.exc} disabled={locked} />
        <Field code={it.code} field="ev" label="Working-paper ref" value={r.ev} disabled={locked} />
        <div><label>Tested by</label><p>{r.tester || "–"}</p></div>
      </div>
      <Field code={it.code} field="obs" label="Observation / finding" type="area" value={r.obs} disabled={locked} />
      <Field code={it.code} field="rc" label="Root cause & risk implication" type="area" value={r.rc} disabled={locked} />
      <Field code={it.code} field="mgmt" label="Management response / action plan" type="area" value={r.mgmt} disabled={locked} />
      <div className="grid3">
        <Field code={it.code} field="owner" label="Action owner" value={r.owner} disabled={locked} />
        <Field code={it.code} field="due" label="Target date" type="date" value={r.due} disabled={locked} />
        <div><label>Action status</label>
          <select disabled={locked} value={r.act || ""} onChange={(e) => void setField(it.code, "act", e.target.value)}>{["", "Open", "In progress", "Closed"].map((o) => <option key={o}>{o}</option>)}</select></div>
        <Field code={it.code} field="closed" label="Closure date" type="date" value={r.closed} disabled={locked} />
      </div>
      <Evidence cycle={cycle} it={it} r={r} locked={cycle.status === "Finalised" || RANK[me.role] < 1} />
      <Review it={it} r={r} locked={cycle.status === "Finalised"} />
    </div>)}
  </article>);
}

export default function Testing() {
  const { state, me, cycleId, setCycleId, notice, busy } = useStore();
  const [q, setQ] = useState(""), [md, setMd] = useState(""), [risk, setRisk] = useState(""), [stf, setStf] = useState(""), [rv, setRv] = useState(""), [dept, setDept] = useState(""), [sort, setSort] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const cycle = state?.cycles.find((c) => c.id === cycleId);
  const rows = useMemo(() => {
    if (!state || !cycle) return [];
    const k = cfg(state, cycle), needle = q.toLowerCase().trim();
    const list = state.library.filter((it) => {
      if (md && it.md !== md) return false;
      if (dept && it.dept !== dept) return false;
      if (risk && riskBand(riskScore(k, it)) !== risk) return false;
      const s = status(k, cycle, it), r = result(cycle, it.code);
      if (stf === "EXC") { if (!["NC", "PC", "CO"].includes(s)) return false; } else if (stf && s !== stf) return false;
      if (rv) { const tested = s !== "NT" && s !== "NA"; if (rv === "pending" && !(tested && !r.revStat)) return false; if (rv === "ok" && r.revStat !== REV_OK) return false; if (rv === "ret" && r.revStat !== REV_RET) return false; }
      if (needle && !`${it.code} ${it.area} ${it.req} ${it.proc ?? ""} ${r.obs ?? ""}`.toLowerCase().includes(needle)) return false;
      return true;
    });
    if (sort === "risk") list.sort((a, b) => riskScore(k, b) - riskScore(k, a) || a.code.localeCompare(b.code));
    else if (sort === "weight") list.sort((a, b) => weight(k, b) - weight(k, a));
    return list;
  }, [state, cycle, q, md, risk, stf, rv, dept, sort]);
  if (!state || !cycle) return <p className="hint">Loading…</p>;
  const sum = summarise(state, cycle, rows);
  const depts = [...new Set(state.library.map((i) => i.dept).filter(Boolean))].sort() as string[];
  const toggle = (c: string) => setOpen((o) => { const n = new Set(o); if (n.has(c)) n.delete(c); else n.add(c); return n; });
  const ro = RANK[me.role] < 1;
  return (<>
    <div className="row"><h2 style={{ flex: 2 }}>Compliance testing</h2>
      <div><label>Cycle</label><select value={cycleId} onChange={(e) => setCycleId(e.target.value)}>{state.cycles.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.status}</option>)}</select></div>
      <span className="hint">{busy ? "Saving…" : "Saved"}</span></div>
    {cycle.demo && <div className="note"><b>Demo data</b> – sample results for presentation only; cannot be finalised.</div>}
    {cycle.status === "Finalised" && <div className="note"><b>Finalised and locked</b> – results and evidence can no longer be changed.</div>}
    {ro && <div className="note"><b>Read-only access</b> – your role ({me.role}) can view but not change compliance data.</div>}
    {notice && <div className="note warn" role="alert">{notice}</div>}
    <details className="filterbox" open={typeof window === "undefined" || window.innerWidth > 700}><summary>Filters{(q || md || risk || stf || rv || dept || sort) ? " (active)" : ""}</summary>
    <div className="filters">
      <div><label>Search</label><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Code, area, requirement…" autoCapitalize="none" /></div>
      <div><label>Master Direction</label><select value={md} onChange={(e) => setMd(e.target.value)}><option value="">All</option>{state.mds.map((m) => <option key={m.k} value={m.k}>{m.t.replace(/ Directions?,? ?\d{4}.*$/, "").replace(/ \(.*\)$/, "")}</option>)}</select></div>
      <div><label>Risk</label><select value={risk} onChange={(e) => setRisk(e.target.value)}><option value="">All</option>{["Critical", "High", "Medium", "Low"].map((x) => <option key={x}>{x}</option>)}</select></div>
      <div><label>Status</label><select value={stf} onChange={(e) => setStf(e.target.value)}><option value="">All</option>{(Object.keys(STATUS) as StatusCode[]).map((s) => <option key={s} value={s}>{STATUS[s]}</option>)}<option value="EXC">Exceptions (NC+PC+C-Obs)</option></select></div>
      <div><label>Review</label><select value={rv} onChange={(e) => setRv(e.target.value)}><option value="">All</option><option value="pending">Tested – pending review</option><option value="ok">Reviewed – agreed</option><option value="ret">Returned</option></select></div>
      <div><label>Department</label><select value={dept} onChange={(e) => setDept(e.target.value)}><option value="">All</option>{depts.map((d) => <option key={d}>{d}</option>)}</select></div>
      <div><label>Sort</label><select value={sort} onChange={(e) => setSort(e.target.value)}><option value="">Library order</option><option value="risk">Inherent risk</option><option value="weight">Weight</option></select></div>
    </div></details>
    <p className="hint">{rows.length} requirements shown · tested {sum.tested}/{sum.applicable} applicable · reviewed {sum.reviewed} · weighted score of filtered set: {sum.score == null ? "–" : fmt(sum.score) + "%"}</p>
    {rows.length === 0 ? <p className="hint">No requirements match the filters.</p> : rows.map((it) => <Card key={it.code} cycle={cycle} it={it} open={open.has(it.code)} toggle={() => toggle(it.code)} />)}
  </>);
}
