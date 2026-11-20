"""
LIFC Compliance OS – server
Login-based RBI compliance testing (NBFC-ML) with roles, maker-checker, audit trail,
evidence attachments and tamper-evident finalisation.

Run:  uvicorn app:app --host 0.0.0.0 --port 8080 --proxy-headers
"""
import os, json, sqlite3, secrets, hashlib, hmac, time, datetime, threading, re, uuid, copy, tempfile, shutil
from pathlib import Path
from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("CCT_DATA", BASE / "data"))
ATT = DATA / "attachments"
DATA.mkdir(parents=True, exist_ok=True)
ATT.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / "cct.sqlite3"
STATIC = BASE / "static"

IDLE_SEC = int(os.environ.get("CCT_IDLE_MIN", "30")) * 60
ABS_SEC = int(os.environ.get("CCT_SESSION_HOURS", "12")) * 3600
MAX_UPLOAD = int(os.environ.get("CCT_MAX_MB", "25")) * 1024 * 1024
LOCK_AFTER = 5
LOCK_MIN = 15
PBKDF2_ITER = 310_000
COOKIE = "cct_s"

ROLES = ["Viewer", "Tester", "Reviewer", "CCO", "Admin"]
RANK = {"Viewer": 0, "Tester": 1, "Reviewer": 2, "CCO": 3, "Admin": -1}  # Admin: user administration only
REV_OK = "Reviewed – agreed"
TESTED = {"C", "CO", "PC", "NC"}
SENSITIVE = {"st", "obs", "exc", "sample", "pop", "ev", "rc"}
REV_FIELDS = {"revStat", "revNote", "revBy", "revOn"}
SERVER_RES_FIELDS = {"att"}
CYC_EDIT = {"name", "from", "to", "reportDate", "tester", "reviewer", "approver", "scope", "demo"}
CYC_SERVER = {"status", "version", "snap", "hash", "finalisedOn", "finalisedBy", "submittedOn", "submittedBy", "id", "log"}
SET_KEYS = {"entity", "layer", "cor", "cco", "docNo", "classification", "logo", "logoRemoved", "sampling", "capCritical", "requireProof"}
SET_MAPS = {"conds", "factors", "bands", "mdMult"}
FLD = {"st": "Status", "date": "Test date", "pop": "Population", "sample": "Sample size", "exc": "Exceptions", "ev": "WP ref",
       "tester": "Tested by", "obs": "Observation", "rc": "Root cause", "mgmt": "Management response", "owner": "Owner",
       "due": "Target date", "act": "Action status", "closed": "Closure date", "revStat": "Review status", "revNote": "Reviewer note"}
ALLOWED_EXT = {"pdf", "png", "jpg", "jpeg", "webp", "heic", "heif", "gif", "bmp", "tif", "tiff", "doc", "docx", "xls", "xlsx", "xlsm",
               "csv", "txt", "ppt", "pptx", "msg", "eml", "zip", "odt", "ods", "rtf", "mp4", "m4a", "mp3"}
INLINE_EXT = {"pdf", "png", "jpg", "jpeg", "webp", "gif"}
MIME = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif",
        "heic": "image/heic", "heif": "image/heif", "txt": "text/plain", "csv": "text/csv", "zip": "application/zip", "mp4": "video/mp4"}

LOCK = threading.RLock()
app = FastAPI(title="LIFC Compliance OS", docs_url=None, redoc_url=None, openapi_url=None)


# ------------------------------------------------------------------ database
def _connect():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


DB = _connect()
DB.executescript("""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE, name TEXT NOT NULL,
  role TEXT NOT NULL, pw_hash TEXT NOT NULL, pw_salt TEXT NOT NULL, must_change INTEGER DEFAULT 1, active INTEGER DEFAULT 1,
  failed INTEGER DEFAULT 0, locked_until REAL DEFAULT 0, created_at TEXT, last_login TEXT);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created REAL, last_seen REAL, ip TEXT, ua TEXT);
CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1), json TEXT, rev INTEGER DEFAULT 0, updated TEXT);
CREATE TABLE IF NOT EXISTS auditlog(id INTEGER PRIMARY KEY, cycle_id TEXT, ts TEXT, username TEXT, name TEXT, role TEXT, action TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_audit_cycle ON auditlog(cycle_id, id);
CREATE TABLE IF NOT EXISTS seclog(id INTEGER PRIMARY KEY, ts TEXT, username TEXT, event TEXT, detail TEXT, ip TEXT);
CREATE TABLE IF NOT EXISTS attachments(id TEXT PRIMARY KEY, cycle_id TEXT, code TEXT, name TEXT, mime TEXT, size INTEGER,
  sha256 TEXT, by_user TEXT, at TEXT, deleted INTEGER DEFAULT 0, deleted_by TEXT, deleted_at TEXT);
""")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def today():
    return datetime.date.today().isoformat()


def client_ip(req: Request):
    return (req.headers.get("x-forwarded-for", "").split(",")[0].strip() or (req.client.host if req.client else ""))[:64]


def seclog(username, event, detail="", ip=""):
    DB.execute("INSERT INTO seclog(ts,username,event,detail,ip) VALUES(?,?,?,?,?)", (now_iso(), username or "", event, detail[:500], ip))


def audit(cycle_id, u, action, detail):
    DB.execute("INSERT INTO auditlog(cycle_id,ts,username,name,role,action,detail) VALUES(?,?,?,?,?,?,?)",
               (cycle_id or "global", now_iso(), u["username"] if u else "system", u["name"] if u else "System",
                u["role"] if u else "", action, str(detail)[:2000]))


# ------------------------------------------------------------------ passwords & sessions
def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), PBKDF2_ITER).hex(), salt


def check_policy(pw):
    if len(pw) < 10:
        return "Password must be at least 10 characters."
    classes = sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 3:
        return "Password must contain at least three of: lower case, upper case, digit, symbol."
    return None


def temp_password():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10)) + secrets.choice("!@#$%") + str(secrets.randbelow(10))


def user_public(r):
    return {"id": r["id"], "username": r["username"], "name": r["name"], "role": r["role"], "active": bool(r["active"]),
            "mustChange": bool(r["must_change"]), "locked": (r["locked_until"] or 0) > time.time(),
            "lastLogin": r["last_login"], "createdAt": r["created_at"]}


def current_user(req: Request, allow_must_change=False):
    tok = req.cookies.get(COOKIE)
    if not tok:
        raise HTTPException(401, "not_authenticated")
    th = hashlib.sha256(tok.encode()).hexdigest()
    s = DB.execute("SELECT * FROM sessions WHERE token_hash=?", (th,)).fetchone()
    t = time.time()
    if not s or t - s["last_seen"] > IDLE_SEC or t - s["created"] > ABS_SEC:
        if s:
            DB.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
        raise HTTPException(401, "session_expired")
    u = DB.execute("SELECT * FROM users WHERE id=?", (s["user_id"],)).fetchone()
    if not u or not u["active"]:
        raise HTTPException(401, "account_disabled")
    if t - s["last_seen"] > 30:
        DB.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (t, th))
    if u["must_change"] and not allow_must_change:
        raise HTTPException(403, "password_change_required")
    return dict(u)


def require(u, min_rank=None, roles=None):
    if roles and u["role"] not in roles:
        raise HTTPException(403, "Your role does not permit this action.")
    if min_rank is not None and RANK.get(u["role"], -1) < min_rank:
        raise HTTPException(403, "Your role does not permit this action.")


@app.middleware("http")
async def security(req: Request, call_next):
    if req.method in ("POST", "PUT", "PATCH", "DELETE") and req.url.path.startswith("/api/") and req.headers.get("x-cct") != "1":
        return JSONResponse({"detail": "Missing request header"}, status_code=400)
    resp = await call_next(req)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                                               "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    if req.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ------------------------------------------------------------------ state helpers
def load_state():
    r = DB.execute("SELECT json, rev FROM state WHERE id=1").fetchone()
    if not r or not r["json"]:
        return None, 0
    return json.loads(r["json"]), r["rev"]


def save_state(st):
    rev = (DB.execute("SELECT rev FROM state WHERE id=1").fetchone() or {"rev": 0})["rev"] + 1
    DB.execute("INSERT INTO state(id,json,rev,updated) VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET json=excluded.json, rev=excluded.rev, updated=excluded.updated",
               (json.dumps(st, ensure_ascii=False), rev, now_iso()))
    return rev


def normalize(st):
    st.setdefault("settings", {})
    st["settings"].pop("user", None)
    st["settings"].pop("role", None)
    st["settings"].setdefault("requireProof", True)
    st.setdefault("rbiObs", [])
    for o in st["rbiObs"]:
        o.setdefault("id", "o" + secrets.token_hex(5))
    st.setdefault("mdRef", {})
    st.setdefault("library", [])
    st.setdefault("cycles", [])
    for c in st["cycles"]:
        c.pop("log", None)
        c.setdefault("status", "Draft")
        c.setdefault("version", 1)
        c.setdefault("results", {})
    st.pop("active", None)
    return st


def find(lst, key, val):
    return next((x for x in lst if isinstance(x, dict) and x.get(key) == val), None)


def short(v, n=60):
    v = "" if v is None else (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v))
    return v if len(v) <= n else v[:n] + "…"


def names_match(a, u):
    a = (a or "").strip().lower()
    return a and (a == u["name"].strip().lower() or a == u["username"].strip().lower())


def active_atts(rec):
    return [a for a in (rec or {}).get("att", []) if not a.get("del")]


class Rej(Exception):
    pass


def apply_op(st, op, u, ctx_cycle, logs):
    kind, path, val = op.get("op"), op.get("path") or [], op.get("value")
    if not path or not isinstance(path, list):
        raise Rej("Invalid path")
    rank = RANK.get(u["role"], -1)
    top = path[0]
    if rank < 1:
        raise Rej("Your role has read-only access to compliance data.")

    # ---------- settings
    if top == "settings":
        if rank < 3:
            raise Rej("Only the CCO can change settings.")
        s = st["settings"]
        if len(path) == 2 and path[1] in SET_KEYS and kind == "set":
            old = s.get(path[1]); s[path[1]] = val
            logs.append((ctx_cycle, "Settings", f"{path[1]}: \"{short(old)}\" → \"{short(val)}\"" if path[1] != "logo" else "Logo updated"))
            return
        if len(path) == 3 and path[1] in SET_MAPS and kind == "set":
            m = s.setdefault(path[1], {}); old = m.get(path[2]); m[path[2]] = val
            logs.append((ctx_cycle, "Settings", f"{path[1]}.{path[2]}: {short(old)} → {short(val)}"))
            return
        if len(path) == 2 and path[1] in SET_MAPS and kind == "set" and isinstance(val, dict):
            s[path[1]] = val; logs.append((ctx_cycle, "Settings", f"{path[1]} replaced")); return
        raise Rej("Setting not editable")

    # ---------- regulatory reference register
    if top == "mdRef":
        if rank < 3:
            raise Rej("Only the CCO can change the reference register.")
        if len(path) == 3 and kind == "set":
            r = st["mdRef"].setdefault(path[1], {}); old = r.get(path[2]); r[path[2]] = val
            logs.append((ctx_cycle, "Reference", f"{path[1]} · {path[2]}: \"{short(old)}\" → \"{short(val)}\"")); return
        if len(path) == 2 and kind == "set" and isinstance(val, dict):
            st["mdRef"][path[1]] = val; logs.append((ctx_cycle, "Reference", f"{path[1]} set")); return
        raise Rej("Invalid reference operation")

    if top == "mds":
        if rank < 3:
            raise Rej("Only the CCO can change the Master Direction list.")
        if len(path) == 2 and kind == "set" and isinstance(val, dict) and not find(st.setdefault("mds", []), "k", path[1]):
            st["mds"].append(val); logs.append((ctx_cycle, "Library", f"Master Direction added: {path[1]}")); return
        raise Rej("Invalid operation")

    # ---------- library
    if top == "library":
        if rank < 3:
            raise Rej("Only the CCO can change the requirement library.")
        code = path[1] if len(path) > 1 else None
        it = find(st["library"], "code", code)
        if len(path) == 2:
            if kind == "set" and isinstance(val, dict):
                if it:
                    raise Rej("Requirement code already exists")
                val["code"] = code; st["library"].append(val)
                logs.append((ctx_cycle, "Library", f"Requirement added: {code} – {short(val.get('req'))}")); return
            if kind == "del" and it:
                if not it.get("custom"):
                    raise Rej("Built-in requirements cannot be deleted")
                st["library"].remove(it); logs.append((ctx_cycle, "Library", f"Custom requirement deleted: {code}")); return
        if len(path) == 3 and it and kind == "set" and path[2] in {"I", "L", "w", "freq", "dept", "ref", "req", "proc", "evid", "area", "cond"}:
            old = it.get(path[2]); it[path[2]] = val
            logs.append((ctx_cycle, "Library", f"{code} · {path[2]}: \"{short(old)}\" → \"{short(val)}\"")); return
        raise Rej("Invalid library operation")

    # ---------- RBI inspection observations
    if top == "rbiObs":
        oid = path[1] if len(path) > 1 else None
        o = find(st["rbiObs"], "id", oid)
        if len(path) == 2 and kind == "set" and isinstance(val, dict):
            if o:
                raise Rej("Observation exists")
            val["id"] = oid; st["rbiObs"].append(val)
            logs.append((ctx_cycle, "RBI observation", f"Added {short(val.get('insp'))} {short(val.get('obs'))}")); return
        if len(path) == 2 and kind == "del" and o:
            if rank < 2:
                raise Rej("Only a Reviewer or the CCO can delete observations.")
            st["rbiObs"].remove(o); logs.append((ctx_cycle, "RBI observation", f"Deleted {short(o.get('insp'))} {short(o.get('obs'))}")); return
        if len(path) == 3 and o and kind == "set" and path[2] != "id":
            old = o.get(path[2]); o[path[2]] = val
            logs.append((ctx_cycle, "RBI observation", f"{o.get('insp') or oid} · {path[2]}: \"{short(old)}\" → \"{short(val)}\"")); return
        raise Rej("Invalid observation operation")

    # ---------- cycles
    if top == "cycles":
        cid = path[1] if len(path) > 1 else None
        c = find(st["cycles"], "id", cid)
        if len(path) == 2:
            if kind == "set" and isinstance(val, dict):
                if c:
                    raise Rej("Cycle exists")
                if rank < 2:
                    raise Rej("Only a Reviewer or the CCO can create cycles.")
                nc = {k: v for k, v in val.items() if k not in CYC_SERVER}
                nc.update({"id": cid, "status": "Draft", "version": 1})
                nc.setdefault("results", {})
                for rec in nc["results"].values():
                    rec.pop("att", None)
                st["cycles"].append(nc)
                logs.append((cid, "Workflow", f"Cycle created: {short(nc.get('name'))} ({nc.get('from')} – {nc.get('to')}); {len(nc['results'])} record(s) carried forward"))
                return
            if kind == "del" and c:
                if rank < 3:
                    raise Rej("Only the CCO can delete a cycle.")
                if c.get("status") == "Finalised" or c.get("hash"):
                    raise Rej("A finalised cycle is a permanent record and cannot be deleted.")
                st["cycles"].remove(c); logs.append(("global", "Workflow", f"Cycle deleted: {c.get('name')}")); return
            raise Rej("Invalid cycle operation")
        if not c:
            raise Rej("Cycle not found")
        if c.get("status") == "Finalised":
            raise Rej("Cycle is finalised and locked.")
        field = path[2]
        if field in CYC_EDIT and len(path) == 3 and kind == "set":
            if rank < 2:
                raise Rej("Only a Reviewer or the CCO can edit cycle details.")
            old = c.get(field); c[field] = val
            logs.append((cid, "Cycle", f"{field}: \"{short(old)}\" → \"{short(val)}\"")); return
        if field != "results":
            raise Rej("Field is controlled by the workflow")
        res = c.setdefault("results", {})
        if len(path) == 3:
            if kind == "set" and isinstance(val, dict):
                if rank < 2:
                    raise Rej("Only a Reviewer or the CCO can replace all results.")
                if res and any(active_atts(r) for r in res.values()) and val:
                    raise Rej("Results with attachments cannot be bulk-replaced.")
                if not val:
                    if any(active_atts(r) for r in res.values()):
                        raise Rej("Results with evidence attachments cannot be cleared.")
                    n = len(res); c["results"] = {}
                    logs.append((cid, "Workflow", f"All results cleared ({n} records); attachments retained on server")); return
                for r in val.values():
                    r.pop("att", None)
                c["results"] = val; logs.append((cid, "Workflow", f"Results replaced ({len(val)} records)")); return
            raise Rej("Invalid results operation")
        code = path[3]
        if not find(st["library"], "code", code):
            raise Rej("Unknown requirement")
        rec = res.get(code)
        if len(path) == 4:
            if kind == "set" and isinstance(val, dict):
                val = {k: v for k, v in val.items() if k not in SERVER_RES_FIELDS}
                if rank < 2:
                    for k in list(val):
                        if k in REV_FIELDS:
                            val.pop(k)
                    val["tester"] = u["name"]
                if rec and rec.get("att"):
                    val["att"] = rec["att"]
                res[code] = val
                logs.append((cid, "Edit", f"{code} · record set (status {val.get('st', '–')})")); return
            if kind == "del":
                if rank < 2:
                    raise Rej("Only a Reviewer or the CCO can delete a result record.")
                if rec and active_atts(rec):
                    raise Rej("Record has evidence attachments; delete them first.")
                res.pop(code, None); logs.append((cid, "Edit", f"{code} · record removed")); return
            raise Rej("Invalid record operation")
        f = path[4]
        if f in SERVER_RES_FIELDS:
            raise Rej("Attachments are managed by upload")
        if f in ("revBy", "revOn"):
            return  # stamped by server
        rec = res.setdefault(code, {})
        if f == "revStat":
            if rank < 2:
                raise Rej("Only a Reviewer or the CCO can record the review.")
            if val:
                if names_match(rec.get("tester"), u):
                    raise Rej(f"Maker-checker: you tested {code} and cannot review it.")
                if (rec.get("st") or "NT") in ("NT",):
                    raise Rej("Record a test status before review.")
                if val == REV_OK and st["settings"].get("requireProof", True) and rec.get("st") in TESTED and not active_atts(rec):
                    raise Rej(f"Proof required: attach evidence to {code} before agreeing the review.")
                old = rec.get("revStat", "")
                rec.update({"revStat": val, "revBy": u["name"], "revOn": today()})
                logs.append((cid, "Review", f"{code} · {short(old) or 'not reviewed'} → {val}")); return
            rec.update({"revStat": "", "revBy": "", "revOn": ""}); logs.append((cid, "Review", f"{code} · review cleared")); return
        if f == "revNote":
            if rank < 2:
                raise Rej("Only a Reviewer or the CCO can write reviewer comments.")
        if f == "tester":
            val = u["name"]
        old = rec.get(f, "")
        if f not in REV_FIELDS and str(old) == str(val if val is not None else ""):
            return
        rec[f] = val
        logs.append((cid, "Edit", f"{code} · {FLD.get(f, f)}: \"{short(old)}\" → \"{short(val)}\""))
        if f == "st":
            if not rec.get("tester") or rank < 2:
                rec["tester"] = u["name"]
            if not rec.get("date"):
                rec["date"] = today()
        if f in SENSITIVE and rec.get("revStat") == REV_OK:
            rec["revStat"] = ""
            rec["revNote"] = ((rec.get("revNote") or "") + f" | Review reset on {today()} after change to {FLD.get(f, f)}").strip(" |")
            logs.append((cid, "Review reset", f"{code} – re-review required after change to {FLD.get(f, f)}"))
        return
    raise Rej("Unknown path")


def applicable(st, c, it):
    snap = c.get("snap") if c.get("status") == "Finalised" else None
    if snap and snap.get("lib") is not None and it["code"] not in snap["lib"]:
        return False
    conds = (snap or st["settings"]).get("conds", {})
    return not it.get("cond") or bool(conds.get(it["cond"]))


def cycle_stats(st, c):
    tested = rev = noproof = app = 0
    for it in st["library"]:
        if not applicable(st, c, it):
            continue
        app += 1
        r = c["results"].get(it["code"], {})
        s = r.get("st") or "NT"
        if s in ("NT", "NA"):
            continue
        tested += 1
        if r.get("revStat") == REV_OK:
            rev += 1
        if s in TESTED and not active_atts(r):
            noproof += 1
    return {"applicable": app, "tested": tested, "reviewed": rev, "noProof": noproof}


def hash_payload(c):
    p = {k: c.get(k) for k in ("id", "name", "from", "to", "version", "results", "snap", "finalisedOn", "finalisedBy")}
    return json.dumps(p, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def state_response(u, st, rev):
    return {"rev": rev, "state": st, "user": {"username": u["username"], "name": u["name"], "role": u["role"]}}


# ------------------------------------------------------------------ auth API
@app.get("/api/bootstrap")
def bootstrap():
    n = DB.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    return {"setupNeeded": n == 0}


@app.post("/api/setup")
async def setup(req: Request):
    body = await req.json()
    with LOCK:
        if DB.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]:
            raise HTTPException(409, "Setup already completed.")
        un, nm, pw = (body.get("username") or "").strip(), (body.get("name") or "").strip(), body.get("password") or ""
        if not re.fullmatch(r"[A-Za-z0-9._@-]{3,40}", un) or not nm:
            raise HTTPException(400, "Enter a valid username (3–40 letters, digits, . _ @ -) and full name.")
        err = check_policy(pw)
        if err:
            raise HTTPException(400, err)
        h, s = hash_pw(pw)
        DB.execute("INSERT INTO users(username,name,role,pw_hash,pw_salt,must_change,created_at) VALUES(?,?,?,?,?,0,?)", (un, nm, "Admin", h, s, now_iso()))
        seclog(un, "Setup", "First administrator account created", client_ip(req))
    return {"ok": True}


@app.post("/api/login")
async def login(req: Request, resp: Response):
    body = await req.json()
    un, pw, ip = (body.get("username") or "").strip(), body.get("password") or "", client_ip(req)
    with LOCK:
        u = DB.execute("SELECT * FROM users WHERE username=?", (un,)).fetchone()
        t = time.time()
        if not u or not u["active"]:
            hash_pw(pw)  # constant-ish timing
            seclog(un, "Login failed", "Unknown or disabled account", ip)
            raise HTTPException(401, "Invalid username or password.")
        if (u["locked_until"] or 0) > t:
            seclog(un, "Login blocked", "Account locked", ip)
            raise HTTPException(423, f"Account locked after repeated failures. Try again after {int((u['locked_until'] - t) // 60) + 1} minute(s) or contact the administrator.")
        h, _ = hash_pw(pw, u["pw_salt"])
        if not hmac.compare_digest(h, u["pw_hash"]):
            failed = u["failed"] + 1
            lock = t + LOCK_MIN * 60 if failed >= LOCK_AFTER else 0
            DB.execute("UPDATE users SET failed=?, locked_until=? WHERE id=?", (0 if lock else failed, lock, u["id"]))
            seclog(un, "Login failed", f"Wrong password (attempt {failed})" + (" – account locked" if lock else ""), ip)
            raise HTTPException(401, "Invalid username or password.")
        tok = secrets.token_urlsafe(32)
        DB.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?)", (hashlib.sha256(tok.encode()).hexdigest(), u["id"], t, t, ip, (req.headers.get("user-agent") or "")[:200]))
        DB.execute("UPDATE users SET failed=0, locked_until=0, last_login=? WHERE id=?", (now_iso(), u["id"]))
        DB.execute("DELETE FROM sessions WHERE last_seen < ?", (t - ABS_SEC,))
        seclog(un, "Login", f"Role {u['role']}", ip)
    secure = req.url.scheme == "https" or req.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(COOKIE, tok, httponly=True, samesite="strict", secure=secure, max_age=ABS_SEC, path="/")
    return {"user": {"username": u["username"], "name": u["name"], "role": u["role"], "mustChange": bool(u["must_change"])}}


@app.post("/api/logout")
def logout(req: Request, resp: Response):
    tok = req.cookies.get(COOKIE)
    if tok:
        th = hashlib.sha256(tok.encode()).hexdigest()
        s = DB.execute("SELECT u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE token_hash=?", (th,)).fetchone()
        DB.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
        if s:
            seclog(s["username"], "Logout", "", client_ip(req))
    resp.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(req: Request):
    u = current_user(req, allow_must_change=True)
    return {"user": {"username": u["username"], "name": u["name"], "role": u["role"], "mustChange": bool(u["must_change"])}}


@app.post("/api/password")
async def change_password(req: Request):
    u = current_user(req, allow_must_change=True)
    body = await req.json()
    h, _ = hash_pw(body.get("old") or "", u["pw_salt"])
    if not hmac.compare_digest(h, u["pw_hash"]):
        seclog(u["username"], "Password change failed", "Wrong current password", client_ip(req))
        raise HTTPException(400, "Current password is incorrect.")
    new = body.get("new") or ""
    err = check_policy(new)
    if err:
        raise HTTPException(400, err)
    if new == body.get("old"):
        raise HTTPException(400, "New password must differ from the current password.")
    nh, ns = hash_pw(new)
    DB.execute("UPDATE users SET pw_hash=?, pw_salt=?, must_change=0 WHERE id=?", (nh, ns, u["id"]))
    seclog(u["username"], "Password changed", "", client_ip(req))
    return {"ok": True}


# ------------------------------------------------------------------ users (Admin)
@app.get("/api/users")
def list_users(req: Request):
    u = current_user(req); require(u, roles=["Admin"])
    return {"users": [user_public(r) for r in DB.execute("SELECT * FROM users ORDER BY username")]}


@app.post("/api/users")
async def create_user(req: Request):
    u = current_user(req); require(u, roles=["Admin"])
    b = await req.json()
    un, nm, role = (b.get("username") or "").strip(), (b.get("name") or "").strip(), b.get("role")
    if not re.fullmatch(r"[A-Za-z0-9._@-]{3,40}", un) or not nm or role not in ROLES:
        raise HTTPException(400, "Enter a valid username, full name and role.")
    if DB.execute("SELECT 1 FROM users WHERE username=?", (un,)).fetchone():
        raise HTTPException(409, "Username already exists.")
    tmp = temp_password(); h, s = hash_pw(tmp)
    DB.execute("INSERT INTO users(username,name,role,pw_hash,pw_salt,must_change,created_at) VALUES(?,?,?,?,?,1,?)", (un, nm, role, h, s, now_iso()))
    seclog(u["username"], "User created", f"{un} ({nm}) role {role}", client_ip(req))
    return {"ok": True, "tempPassword": tmp}


@app.post("/api/users/{uid}")
async def update_user(uid: int, req: Request):
    u = current_user(req); require(u, roles=["Admin"])
    b = await req.json()
    t = DB.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not t:
        raise HTTPException(404, "User not found")
    out, changes = {"ok": True}, []
    with LOCK:
        if "role" in b and b["role"] != t["role"]:
            if b["role"] not in ROLES:
                raise HTTPException(400, "Invalid role")
            if t["role"] == "Admin" and DB.execute("SELECT COUNT(*) n FROM users WHERE role='Admin' AND active=1").fetchone()["n"] <= 1:
                raise HTTPException(400, "At least one active administrator is required.")
            DB.execute("UPDATE users SET role=? WHERE id=?", (b["role"], uid)); changes.append(f"role {t['role']} → {b['role']}")
            DB.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        if "name" in b and (b["name"] or "").strip() and b["name"] != t["name"]:
            DB.execute("UPDATE users SET name=? WHERE id=?", (b["name"].strip(), uid)); changes.append(f"name → {b['name'].strip()}")
        if "active" in b and bool(b["active"]) != bool(t["active"]):
            if not b["active"] and t["id"] == u["id"]:
                raise HTTPException(400, "You cannot disable your own account.")
            if not b["active"] and t["role"] == "Admin" and DB.execute("SELECT COUNT(*) n FROM users WHERE role='Admin' AND active=1").fetchone()["n"] <= 1:
                raise HTTPException(400, "At least one active administrator is required.")
            DB.execute("UPDATE users SET active=? WHERE id=?", (1 if b["active"] else 0, uid)); changes.append("enabled" if b["active"] else "disabled")
            if not b["active"]:
                DB.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        if b.get("unlock"):
            DB.execute("UPDATE users SET failed=0, locked_until=0 WHERE id=?", (uid,)); changes.append("unlocked")
        if b.get("reset"):
            tmp = temp_password(); h, s = hash_pw(tmp)
            DB.execute("UPDATE users SET pw_hash=?, pw_salt=?, must_change=1, failed=0, locked_until=0 WHERE id=?", (h, s, uid))
            DB.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            out["tempPassword"] = tmp; changes.append("password reset")
    if changes:
        seclog(u["username"], "User updated", f"{t['username']}: " + "; ".join(changes), client_ip(req))
    return out


@app.get("/api/seclog")
def get_seclog(req: Request):
    u = current_user(req); require(u, roles=["Admin", "CCO"])
    rows = DB.execute("SELECT * FROM seclog ORDER BY id DESC LIMIT 2000").fetchall()
    return {"log": [dict(r) for r in rows]}


# ------------------------------------------------------------------ state API
@app.get("/api/state")
def get_state(req: Request, rev: int = -1):
    u = current_user(req)
    st, r = load_state()
    if rev == r and st is not None:
        return {"rev": r, "unchanged": True}
    return state_response(u, st, r)


@app.post("/api/init")
async def init_state(req: Request):
    u = current_user(req)
    if u["role"] == "Viewer":
        raise HTTPException(403, "Viewer cannot initialise data.")
    body = await req.json()
    with LOCK:
        st, r = load_state()
        if st is not None:
            return state_response(u, st, r)
        st = normalize(body.get("state") or {})
        r = save_state(st)
        audit("global", u, "Initialise", "Compliance library and settings initialised")
    return state_response(u, st, r)


@app.post("/api/ops")
async def ops(req: Request):
    u = current_user(req)
    body = await req.json()
    ctx = body.get("cycleId") or "global"
    rejected, logs = [], []
    with LOCK:
        st, _ = load_state()
        if st is None:
            raise HTTPException(409, "Data not initialised")
        for op in body.get("ops", [])[:5000]:
            if op.get("op") == "log":
                if op.get("action") in ("Demo data", "Export", "Report", "Note"):
                    logs.append((ctx, op["action"], short(op.get("detail"), 500)))
                continue
            try:
                apply_op(st, op, u, ctx, logs)
            except Rej as e:
                rejected.append({"path": op.get("path"), "reason": str(e)})
            except Exception as e:  # noqa
                rejected.append({"path": op.get("path"), "reason": "Invalid operation"})
        r = save_state(st)
        for cid, action, detail in logs:
            audit(cid, u, action, detail)
        for rj in rejected[:20]:
            audit(ctx, u, "Rejected", f"{'/'.join(map(str, rj['path'] or []))}: {rj['reason']}")
    out = state_response(u, st, r)
    out["rejected"] = rejected
    return out


@app.get("/api/log")
def get_log(req: Request, cycle: str):
    current_user(req)
    rows = DB.execute("SELECT ts,username,name,role,action,detail FROM auditlog WHERE cycle_id IN (?, 'global') ORDER BY id", (cycle,)).fetchall()
    return {"log": [{"ts": r["ts"], "user": f"{r['name']} ({r['username']})", "role": r["role"], "action": r["action"], "detail": r["detail"]} for r in rows]}


@app.post("/api/workflow")
async def workflow(req: Request):
    u = current_user(req)
    b = await req.json()
    action, cid = b.get("action"), b.get("cycleId")
    with LOCK:
        st, _ = load_state()
        c = find(st["cycles"], "id", cid) if st else None
        if not c:
            raise HTTPException(404, "Cycle not found")
        rank = RANK.get(u["role"], -1)
        result = {}
        if action == "submit":
            require(u, min_rank=1)
            if c["status"] != "Draft":
                raise HTTPException(400, "Only a draft cycle can be submitted.")
            c.update({"status": "Under review", "submittedOn": now_iso(), "submittedBy": u["name"]})
            audit(cid, u, "Workflow", "Submitted for review")
        elif action == "return":
            require(u, min_rank=2)
            if c["status"] != "Under review":
                raise HTTPException(400, "Cycle is not under review.")
            c["status"] = "Draft"; audit(cid, u, "Workflow", "Returned to draft. " + (b.get("reason") or ""))
        elif action == "precheck":
            result = cycle_stats(st, c)
        elif action == "finalise":
            require(u, min_rank=2)
            if c["status"] == "Finalised":
                raise HTTPException(400, "Already finalised.")
            if c.get("demo"):
                raise HTTPException(400, "This cycle contains demo data and cannot be finalised. Clear the results first.")
            if not (c.get("reviewer") and c.get("approver") and c.get("from") and c.get("to")):
                raise HTTPException(400, "Enter period dates, 'Reviewed by' and 'Approved / noted by' first.")
            stats = cycle_stats(st, c)
            if not stats["tested"]:
                raise HTTPException(400, "No requirements have been tested in this cycle.")
            s = st["settings"]
            c["snap"] = {"mdMult": dict(s.get("mdMult", {})), "factors": dict(s.get("factors", {})), "conds": dict(s.get("conds", {})),
                         "bands": dict(s.get("bands", {})), "capCritical": s.get("capCritical", True),
                         "lib": {i["code"]: {"I": i["I"], "L": i["L"], "w": i.get("w", "")} for i in st["library"]}}
            c.update({"status": "Finalised", "finalisedOn": now_iso(), "finalisedBy": u["name"]})
            c["hash"] = hashlib.sha256(hash_payload(c).encode()).hexdigest()
            audit(cid, u, "Finalised", f"Version {c['version']} finalised; {stats['tested']} tested, {stats['reviewed']} reviewed, "
                                       f"{stats['noProof']} without proof; SHA-256 {c['hash']}")
            result = stats
        elif action == "unlock":
            require(u, roles=["CCO"])
            if c["status"] != "Finalised":
                raise HTTPException(400, "Cycle is not finalised.")
            why = (b.get("reason") or "").strip()
            if not why:
                raise HTTPException(400, "A reason is required.")
            audit(cid, u, "Unlocked", f"Version {c['version']} unlocked. Reason: {why}. Previous hash {c.get('hash')}")
            c.update({"status": "Draft", "version": c.get("version", 1) + 1, "hash": "", "finalisedOn": "", "finalisedBy": ""})
            c.pop("snap", None)
        elif action == "verify":
            if not c.get("hash"):
                raise HTTPException(400, "Cycle has no integrity hash.")
            h = hashlib.sha256(hash_payload(c).encode()).hexdigest()
            bad = []
            for code, rec in c["results"].items():
                for a in active_atts(rec):
                    p = ATT / a["id"]
                    if not p.exists() or sha256_file(p) != a.get("sha"):
                        bad.append(f"{code}: {a.get('name')}")
            ok = h == c["hash"] and not bad
            audit(cid, u, "Integrity check", ("Verified – record and %d evidence file(s) unchanged" % sum(len(active_atts(r)) for r in c["results"].values())) if ok
                  else f"MISMATCH – record hash {'OK' if h == c['hash'] else 'CHANGED'}; evidence problems: {', '.join(bad) or 'none'}")
            result = {"ok": ok, "stored": c["hash"], "computed": h, "evidenceProblems": bad}
        else:
            raise HTTPException(400, "Unknown action")
        r = save_state(st)
    out = state_response(u, st, r)
    out["result"] = result
    return out


# ------------------------------------------------------------------ attachments
@app.post("/api/attach")
async def upload(req: Request, cycleId: str = Form(...), code: str = Form(...), file: UploadFile = File(...)):
    u = current_user(req)
    require(u, min_rank=1)
    name = os.path.basename(file.filename or "file").replace("\\", "_")[:150] or "file"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"File type .{ext or '?'} is not allowed as evidence.")
    tmp = tempfile.NamedTemporaryFile(delete=False, dir=ATT, prefix=".up_")
    h, size = hashlib.sha256(), 0
    try:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD:
                raise HTTPException(413, f"File exceeds {MAX_UPLOAD // 1048576} MB.")
            h.update(chunk); tmp.write(chunk)
        tmp.close()
        if size == 0:
            raise HTTPException(400, "Empty file.")
        with LOCK:
            st, _ = load_state()
            c = find(st["cycles"], "id", cycleId) if st else None
            if not c:
                raise HTTPException(404, "Cycle not found")
            if c.get("status") == "Finalised":
                raise HTTPException(400, "Cycle is finalised and locked.")
            if not find(st["library"], "code", code):
                raise HTTPException(404, "Requirement not found")
            aid = uuid.uuid4().hex
            shutil.move(tmp.name, ATT / aid)
            meta = {"id": aid, "name": name, "size": size, "mime": MIME.get(ext, "application/octet-stream"), "sha": h.hexdigest(), "by": u["name"], "at": now_iso()}
            rec = c["results"].setdefault(code, {})
            rec.setdefault("att", []).append(meta)
            DB.execute("INSERT INTO attachments(id,cycle_id,code,name,mime,size,sha256,by_user,at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (aid, cycleId, code, name, meta["mime"], size, meta["sha"], u["username"], meta["at"]))
            audit(cycleId, u, "Evidence", f"{code} · uploaded \"{name}\" ({size:,} bytes) SHA-256 {meta['sha']}")
            if rec.get("revStat") == REV_OK:
                rec["revStat"] = ""
                audit(cycleId, u, "Review reset", f"{code} – re-review required after new evidence")
            r = save_state(st)
        out = state_response(u, st, r); out["attachment"] = meta
        return out
    finally:
        if os.path.exists(tmp.name):
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


@app.get("/api/attach/{aid}")
def download(aid: str, req: Request, dl: int = 0):
    u = current_user(req)
    if not re.fullmatch(r"[0-9a-f]{32}", aid):
        raise HTTPException(404, "Not found")
    a = DB.execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
    p = ATT / aid
    if not a or not p.exists():
        raise HTTPException(404, "Not found")
    ext = a["name"].rsplit(".", 1)[-1].lower() if "." in a["name"] else ""
    disp = "inline" if (ext in INLINE_EXT and not dl) else "attachment"
    DB.execute("INSERT INTO seclog(ts,username,event,detail,ip) VALUES(?,?,?,?,?)", (now_iso(), u["username"], "Evidence viewed", f"{a['code']} {a['name']}", client_ip(req)))
    return FileResponse(p, media_type=a["mime"], filename=a["name"], content_disposition_type=disp,
                        headers={"Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"})


@app.post("/api/attach/{aid}/delete")
async def delete_attachment(aid: str, req: Request):
    u = current_user(req)
    require(u, min_rank=1)
    b = await req.json()
    with LOCK:
        a = DB.execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
        if not a or a["deleted"]:
            raise HTTPException(404, "Not found")
        if a["by_user"].lower() != u["username"].lower() and u["role"] != "CCO":
            raise HTTPException(403, "Only the uploader or the CCO can remove evidence.")
        st, _ = load_state()
        c = find(st["cycles"], "id", a["cycle_id"])
        if not c:
            raise HTTPException(404, "Cycle not found")
        if c.get("status") == "Finalised":
            raise HTTPException(400, "Cycle is finalised and locked.")
        why = (b.get("reason") or "").strip() or "not stated"
        rec = c["results"].get(a["code"], {})
        for m in rec.get("att", []):
            if m["id"] == aid:
                m.update({"del": True, "delBy": u["name"], "delAt": now_iso(), "delReason": why})
        if rec.get("revStat") == REV_OK:
            rec["revStat"] = ""
        DB.execute("UPDATE attachments SET deleted=1, deleted_by=?, deleted_at=? WHERE id=?", (u["username"], now_iso(), aid))
        audit(a["cycle_id"], u, "Evidence", f"{a['code']} · removed \"{a['name']}\" (file retained on server). Reason: {why}")
        r = save_state(st)
    return state_response(u, st, r)


# ------------------------------------------------------------------ backup / import
@app.get("/api/backup")
def backup(req: Request):
    u = current_user(req); require(u, roles=["CCO", "Admin"])
    st, r = load_state()
    logs = [dict(x) for x in DB.execute("SELECT * FROM auditlog ORDER BY id")]
    atts = [dict(x) for x in DB.execute("SELECT * FROM attachments ORDER BY at")]
    seclog(u["username"], "Backup exported", f"rev {r}", client_ip(req))
    return JSONResponse({"exportedAt": now_iso(), "exportedBy": u["username"], "rev": r, "state": st, "auditlog": logs, "attachments": atts},
                        headers={"Content-Disposition": f'attachment; filename="cct_backup_{today()}.json"'})


@app.post("/api/import")
async def import_state(req: Request):
    u = current_user(req); require(u, roles=["CCO"])
    b = await req.json()
    st = b.get("state") or b
    if not isinstance(st, dict) or "library" not in st or "cycles" not in st:
        raise HTTPException(400, "Invalid backup file")
    with LOCK:
        cur, _ = load_state()
        if cur and any(c.get("hash") for c in cur.get("cycles", [])):
            keep = {c["id"]: c for c in cur["cycles"] if c.get("hash")}
            st["cycles"] = [c for c in st["cycles"] if c.get("id") not in keep] + list(keep.values())
        st = normalize(st)
        r = save_state(st)
        audit("global", u, "Import", "Data imported from backup (finalised cycles on server preserved)")
        seclog(u["username"], "Data imported", "", client_ip(req))
    return state_response(u, st, r)


# ------------------------------------------------------------------ static
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


APP_DIR = (STATIC / "app").resolve()


@app.get("/app")
def app_root_redirect():
    return RedirectResponse("/app/")


@app.get("/app/{path:path}")
def react_app(path: str = ""):
    """React client (web/ → built into static/app). Unknown paths fall back to index.html (SPA routing)."""
    f = (APP_DIR / path).resolve()
    if path and f.is_file() and APP_DIR in f.parents:
        return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable" if "/assets/" in f"/{path}" else "no-cache"})
    idx = APP_DIR / "index.html"
    if not idx.exists():
        raise HTTPException(404, "React client not built (run: cd web && npm run build)")
    return FileResponse(idx, headers={"Cache-Control": "no-cache"})


@app.get("/{name}")
def static_file(name: str):
    allowed = {"manifest.webmanifest": "application/manifest+json", "sw.js": "text/javascript", "icon-192.png": "image/png",
               "icon-512.png": "image/png", "icon-maskable.png": "image/png", "favicon.png": "image/png"}
    if name not in allowed:
        raise HTTPException(404, "Not found")
    return FileResponse(STATIC / name, media_type=allowed[name], headers={"Cache-Control": "no-cache"})
