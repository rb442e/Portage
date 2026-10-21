"""Email-code sign-in, sessions and role-based access."""
import pytest
from fastapi.testclient import TestClient

from app import auth, store
from app.main import app

ADMIN, MEMBER, OUTSIDER = "boss@corp.com", "dev@corp.com", "someone@elsewhere.org"


@pytest.fixture
def codes(monkeypatch):
    sent = {}
    monkeypatch.delenv("PORTAGE_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("PORTAGE_ADMIN_EMAILS", ADMIN)
    monkeypatch.setenv("PORTAGE_ALLOWED_EMAIL_DOMAINS", "corp.com")
    monkeypatch.setenv("PORTAGE_AUTH_DEV_LOG_CODES", "1")
    monkeypatch.setattr(auth, "_send", lambda email, code, purpose="signin": sent.__setitem__(email, code))
    mails = sent.setdefault("__mail__", [])
    monkeypatch.setattr(auth, "_mail", lambda to, subject, body: mails.append((to, subject)))
    return sent


def new_client():
    return TestClient(app)


def sign_in(client, codes, email):
    assert client.post("/api/auth/request-code", json={"email": email}).status_code == 200
    r = client.post("/api/auth/verify", json={"email": email, "code": codes[email]})
    assert r.status_code == 200, r.text
    return r.json()["user"]


def test_api_requires_sign_in(codes):
    with new_client() as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/mappings").status_code == 401
        assert c.get("/api/auth/me").status_code == 401
        assert c.get("/api/auth/config").json()["enabled"] is True


def test_admin_from_env_signs_in_with_code_and_gets_httponly_cookie(codes):
    with new_client() as c:
        c.post("/api/auth/request-code", json={"email": "  Boss@Corp.com "})
        r = c.post("/api/auth/verify", json={"email": ADMIN, "code": codes[ADMIN]})
        assert r.json()["user"]["role"] == "admin"
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        assert c.get("/api/auth/me").json()["user"]["email"] == ADMIN
        assert c.get("/api/mappings").status_code == 200
        c.post("/api/auth/logout")
        assert c.get("/api/mappings").status_code == 401


def test_unknown_address_gets_same_answer_and_no_code(codes):
    with new_client() as c:
        a = c.post("/api/auth/request-code", json={"email": OUTSIDER}).json()
        b = c.post("/api/auth/request-code", json={"email": MEMBER}).json()
        assert a == b
        assert OUTSIDER not in codes and MEMBER in codes
        assert c.post("/api/auth/verify", json={"email": OUTSIDER, "code": "123456"}).status_code == 400


def test_domain_sign_up_creates_viewer(codes):
    with new_client() as c:
        assert sign_in(c, codes, MEMBER)["role"] == "viewer"


def test_codes_are_hashed_single_use_and_attempt_limited(codes):
    with new_client() as c:
        c.post("/api/auth/request-code", json={"email": MEMBER})
        code = codes[MEMBER]
        stored = str([tuple(r) for r in store._conn().execute("SELECT * FROM auth_codes").fetchall()])
        assert code not in stored
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(auth.MAX_ATTEMPTS):
            assert c.post("/api/auth/verify", json={"email": MEMBER, "code": wrong}).status_code == 400
        assert c.post("/api/auth/verify", json={"email": MEMBER, "code": code}).status_code == 400


def test_code_cannot_be_reused_and_resend_is_throttled(codes):
    with new_client() as c:
        sign_in(c, codes, MEMBER)
        first = codes.pop(MEMBER)
        assert c.post("/api/auth/verify", json={"email": MEMBER, "code": first}).status_code == 400
        c.post("/api/auth/request-code", json={"email": MEMBER})
        assert MEMBER not in codes          # within the resend cooldown no new code is sent


def test_email_must_be_configured(codes, monkeypatch):
    monkeypatch.delenv("PORTAGE_AUTH_DEV_LOG_CODES")
    monkeypatch.delenv("PORTAGE_SMTP_HOST", raising=False)
    with new_client() as c:
        assert c.post("/api/auth/request-code", json={"email": ADMIN}).status_code == 503


def test_roles_control_access(codes):
    with new_client() as admin, new_client() as viewer:
        sign_in(admin, codes, ADMIN)
        sign_in(viewer, codes, MEMBER)
        tpl = admin.get("/api/mappings/builtin").json()
        assert viewer.get("/api/mappings").status_code == 200
        r = viewer.post("/api/mappings", json=tpl)
        assert r.status_code == 403 and "Viewer" in r.json()["detail"]
        assert viewer.get("/api/auth/users").status_code == 403

        assert admin.patch(f"/api/auth/users/{MEMBER}", json={"role": "member"}).status_code == 200
        assert viewer.post("/api/mappings", json=tpl).status_code == 200      # takes effect immediately
        assert viewer.put("/api/settings/graph", json={"values": {"default_depth": 3}}).status_code == 403
        assert admin.put("/api/settings/graph", json={"values": {"default_depth": 3}}).status_code == 200


def test_admin_manages_users_and_last_admin_is_protected(codes):
    with new_client() as admin, new_client() as other:
        sign_in(admin, codes, ADMIN)
        r = admin.post("/api/auth/users", json={"email": "contractor@partner.io", "role": "member"})
        assert r.status_code == 200
        assert {u["email"] for u in r.json()["users"]} >= {ADMIN, "contractor@partner.io"}
        assert admin.post("/api/auth/users", json={"email": "contractor@partner.io", "role": "member"}).status_code == 409
        assert admin.post("/api/auth/users", json={"email": "x@y.io", "role": "owner"}).status_code == 400
        assert admin.patch(f"/api/auth/users/{ADMIN}", json={"role": "viewer"}).status_code == 400
        assert admin.delete(f"/api/auth/users/{ADMIN}").status_code == 400

        sign_in(other, codes, "contractor@partner.io")          # invited address outside the allowed domain
        assert other.get("/api/mappings").status_code == 200
        assert admin.patch("/api/auth/users/contractor@partner.io", json={"status": "disabled"}).status_code == 200
        assert other.get("/api/mappings").status_code == 401     # sessions end when a user is disabled
        codes.pop("contractor@partner.io", None)
        other.post("/api/auth/request-code", json={"email": "contractor@partner.io"})
        assert "contractor@partner.io" not in codes
        events = {a["event"] for a in store.list_audit()}
        assert {"signed_in", "user_added", "user_updated"} <= events


def test_viewer_chat_gets_no_change_tools(codes, monkeypatch):
    from app.routers import copilot as copilot_router
    seen = {}

    def fake_run_chat(*args, read_only=False, **kwargs):
        seen["read_only"] = read_only
        yield {"type": "done"}

    monkeypatch.setattr(copilot_router, "run_chat", fake_run_chat)
    with new_client() as viewer:
        sign_in(viewer, codes, MEMBER)
        assert viewer.post("/api/copilot/chat", json={"message": "hi"}).status_code == 200
        assert seen["read_only"] is True


def test_cross_site_writes_are_blocked(codes):
    with new_client() as c:
        sign_in(c, codes, ADMIN)
        r = c.post("/api/auth/users", json={"email": "a@b.io", "role": "viewer"}, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403


def test_auth_can_be_disabled_for_local_use(monkeypatch):
    monkeypatch.setenv("PORTAGE_AUTH_DISABLED", "1")
    with new_client() as c:
        assert c.get("/api/mappings").status_code == 200
        assert c.get("/api/auth/me").json()["user"]["auth_disabled"] is True


PW = "correct horse battery"


def sign_up(client, codes, email, password=PW):
    r = client.post("/api/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return client.post("/api/auth/signup/verify", json={"email": email, "code": codes.get(email, "000000")})


def test_sign_up_in_allowed_domain_signs_in_and_password_works(codes):
    with new_client() as c:
        r = sign_up(c, codes, MEMBER)
        assert r.json()["status"] == "signed_in" and r.json()["user"]["role"] == "viewer"
        assert r.json()["user"]["has_password"] is True
        stored = str([tuple(x) for x in store._conn().execute("SELECT * FROM users").fetchall()])
        assert PW not in stored and "scrypt$" in stored
        c.post("/api/auth/logout")
        assert c.post("/api/auth/login", json={"email": MEMBER, "password": "wrong password!!"}).status_code == 401
        ok = c.post("/api/auth/login", json={"email": MEMBER, "password": PW})
        assert ok.status_code == 200 and c.get("/api/mappings").status_code == 200


def test_outside_sign_up_waits_for_admin_approval(codes):
    with new_client() as admin, new_client() as guest:
        sign_in(admin, codes, ADMIN)
        assert sign_up(guest, codes, OUTSIDER).json() == {"status": "pending"}
        assert any(to == ADMIN and "access request" in subj for to, subj in codes["__mail__"])
        r = guest.post("/api/auth/login", json={"email": OUTSIDER, "password": PW})
        assert r.status_code == 403 and "approve" in r.json()["detail"]
        users = admin.get("/api/auth/users").json()["users"]
        assert users[0]["email"] == OUTSIDER and users[0]["status"] == "pending"
        assert admin.patch(f"/api/auth/users/{OUTSIDER}", json={"status": "active", "role": "member"}).status_code == 200
        assert any(to == OUTSIDER and "ready" in subj for to, subj in codes["__mail__"])
        assert guest.post("/api/auth/login", json={"email": OUTSIDER, "password": PW}).json()["user"]["role"] == "member"


def test_sign_up_can_be_closed_and_existing_accounts_are_not_revealed(codes, monkeypatch):
    monkeypatch.setenv("PORTAGE_SIGNUP", "off")
    with new_client() as c:
        r = c.post("/api/auth/signup", json={"email": OUTSIDER, "name": "X", "password": PW})
        assert r.status_code == 200 and OUTSIDER not in codes
        sign_up(c, codes, MEMBER)                       # allowed domain still works
        codes.pop(MEMBER)
        again = c.post("/api/auth/signup", json={"email": MEMBER, "name": "X", "password": PW})
        assert again.json() == r.json() and MEMBER not in codes
        assert any(to == MEMBER and "already have" in subj for to, subj in codes["__mail__"])


def test_weak_passwords_are_rejected(codes):
    with new_client() as c:
        for pw in ("short", "password123", "aaaaaaaaaaaaa", "1234567890"):
            r = c.post("/api/auth/signup", json={"email": MEMBER, "name": "Pat", "password": pw})
            assert r.status_code == 400, pw


def test_forgot_password_resets_and_signs_out_other_sessions(codes):
    with new_client() as first, new_client() as second:
        sign_up(first, codes, MEMBER)
        assert first.get("/api/mappings").status_code == 200
        codes.pop(MEMBER)
        assert second.post("/api/auth/password/forgot", json={"email": OUTSIDER}).status_code == 200
        assert OUTSIDER not in codes
        auth._conn().execute("UPDATE auth_codes SET created_at = created_at - 60").connection.commit()
        second.post("/api/auth/password/forgot", json={"email": MEMBER})
        new_pw = "a brand new passphrase"
        bad = second.post("/api/auth/password/reset", json={"email": MEMBER, "code": "000000" if codes[MEMBER] != "000000" else "111111", "password": new_pw})
        assert bad.status_code == 400
        r = second.post("/api/auth/password/reset", json={"email": MEMBER, "code": codes[MEMBER], "password": new_pw})
        assert r.status_code == 200 and second.get("/api/mappings").status_code == 200
        assert first.get("/api/mappings").status_code == 401
        second.post("/api/auth/logout")
        assert second.post("/api/auth/login", json={"email": MEMBER, "password": PW}).status_code == 401
        assert second.post("/api/auth/login", json={"email": MEMBER, "password": new_pw}).status_code == 200


def test_repeated_wrong_passwords_lock_the_account_temporarily(codes):
    with new_client() as c:
        sign_up(c, codes, MEMBER)
        c.post("/api/auth/logout")
        for _ in range(auth.MAX_LOGIN_FAILURES):
            assert c.post("/api/auth/login", json={"email": MEMBER, "password": "not the password"}).status_code == 401
        assert c.post("/api/auth/login", json={"email": MEMBER, "password": PW}).status_code == 429
        assert c.post("/api/auth/login", json={"email": "nobody@corp.com", "password": PW}).status_code == 401
