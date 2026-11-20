"""Server-side tests for authentication, role rules and maker-checker. Run: pytest -q (from server/)."""
import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

H = {"X-CCT": "1"}
PW = "Str0ng!Passw0rd"
LIB = [{"code": "T-01", "I": 3, "L": 3, "req": "Test requirement", "custom": True},
       {"code": "T-02", "I": 3, "L": 3, "req": "Second test requirement", "custom": True}]


@pytest.fixture(scope="module")
def mod(tmp_path_factory):
    import os
    os.environ["CCT_DATA"] = str(tmp_path_factory.mktemp("data"))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def client(mod):
    return TestClient(mod.app)


def login(c, un, pw):
    return c.post("/api/login", json={"username": un, "password": pw}, headers=H)


@pytest.fixture(scope="module")
def env(mod):
    admin = client(mod)
    assert admin.post("/api/setup", json={"username": "admin", "name": "Admin One", "password": PW}, headers=H).status_code == 200
    assert login(admin, "admin", PW).status_code == 200
    clients = {}
    for un, role in [("cco", "CCO"), ("rev", "Reviewer"), ("tst", "Tester"), ("vwr", "Viewer")]:
        r = admin.post("/api/users", json={"username": un, "name": un.upper() + " User", "role": role}, headers=H)
        tmp = r.json()["tempPassword"]
        c = client(mod)
        assert login(c, un, tmp).status_code == 200
        # temp password blocks everything until changed
        assert c.get("/api/state").status_code == 403
        assert c.post("/api/password", json={"old": tmp, "new": PW}, headers=H).status_code == 200
        clients[un] = c
    r = clients["cco"].post("/api/init", json={"state": {"library": LIB, "settings": {}}}, headers=H)
    assert r.status_code == 200
    return admin, clients


def op(c, ops, cycle="cy1"):
    return c.post("/api/ops", json={"cycleId": cycle, "ops": ops}, headers=H).json()


def test_csrf_header_required(mod):
    assert client(mod).post("/api/login", json={}).status_code == 400


def test_password_policy(mod):
    assert mod.check_policy("short1A!") is not None
    assert mod.check_policy("alllowercaseonly") is not None
    assert mod.check_policy(PW) is None


def test_setup_only_once(mod, env):
    r = client(mod).post("/api/setup", json={"username": "x1x", "name": "X", "password": PW}, headers=H)
    assert r.status_code == 409


def test_unauthenticated_rejected(mod, env):
    assert client(mod).get("/api/state").status_code == 401


def test_admin_cannot_write_compliance_data(env):
    admin, _ = env
    res = op(admin, [{"op": "set", "path": ["settings", "entity"], "value": "Hacked"}])
    assert res["rejected"] and "read-only" in res["rejected"][0]["reason"]


def test_tester_cannot_change_settings_or_create_cycle(env):
    _, c = env
    res = op(c["tst"], [{"op": "set", "path": ["settings", "entity"], "value": "X"},
                        {"op": "set", "path": ["cycles", "cy1"], "value": {"name": "C"}}])
    assert len(res["rejected"]) == 2


def test_viewer_is_read_only(env):
    _, c = env
    res = op(c["vwr"],[{"op": "set", "path": ["settings", "entity"], "value": "X"}])
    assert res["rejected"]


def test_cco_can_change_settings(env):
    _, c = env
    res = op(c["cco"], [{"op": "set", "path": ["settings", "entity"], "value": "LIFC"}])
    assert not res["rejected"]


def test_maker_checker_and_proof_rule(env):
    _, c = env
    assert not op(c["rev"], [{"op": "set", "path": ["cycles", "cy1"], "value": {"name": "Q1", "results": {}}}])["rejected"]
    # tester records Compliant; server stamps the tester name
    assert not op(c["tst"], [{"op": "set", "path": ["cycles", "cy1", "results", "T-01", "st"], "value": "C"}])["rejected"]
    # tester cannot review
    r = op(c["tst"], [{"op": "set", "path": ["cycles", "cy1", "results", "T-01", "revStat"], "value": mod_ok()}])
    assert r["rejected"]
    # reviewer is blocked: no attachment yet (proof rule)
    r = op(c["rev"], [{"op": "set", "path": ["cycles", "cy1", "results", "T-01", "revStat"], "value": mod_ok()}])
    assert r["rejected"] and "Proof required" in r["rejected"][0]["reason"]


def test_maker_checker_same_person(env):
    _, c = env
    # reviewer tests a fresh record, then cannot review their own test
    op(c["rev"], [{"op": "set", "path": ["cycles", "cy1", "results", "T-02", "st"], "value": "NC"}])
    r = op(c["rev"], [{"op": "set", "path": ["cycles", "cy1", "results", "T-02", "revStat"], "value": mod_ok()}])
    assert r["rejected"] and "Maker-checker" in r["rejected"][0]["reason"]


def test_server_owned_fields_cannot_be_set(env):
    _, c = env
    r = op(c["cco"], [{"op": "set", "path": ["cycles", "cy1", "status"], "value": "Finalised"},
                      {"op": "set", "path": ["cycles", "cy1", "results", "T-01", "att"], "value": []}])
    assert len(r["rejected"]) == 2


def test_lockout_after_five_failures(mod, env):
    admin, _ = env
    admin.post("/api/users", json={"username": "victim", "name": "Victim", "role": "Tester"}, headers=H)
    c = client(mod)
    for _ in range(5):
        assert login(c, "victim", "wrong-Password1!").status_code == 401
    assert login(c, "victim", "wrong-Password1!").status_code == 423


def test_last_admin_protected(env):
    admin, _ = env
    users = admin.get("/api/users").json()["users"]
    me = next(u for u in users if u["username"] == "admin")
    assert admin.post(f"/api/users/{me['id']}", json={"role": "Tester"}, headers=H).status_code == 400
    assert admin.post(f"/api/users/{me['id']}", json={"active": False}, headers=H).status_code == 400


def mod_ok():
    return "Reviewed – agreed"
