"""Shared hermetic helpers for run-behavior tests.

Every run test must leave zero rows behind: moto persists across pytest
invocations, and seeded AVAILABLE teams would otherwise steal
recommendations from later tests. wipe_run_everything() deletes every row
carrying the run_id across all run-touched tables.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

import app.main as app_main  # noqa: E402
from app.db.client import table  # noqa: E402

client = TestClient(app_main.app)

_RUN_TABLES = ["Incidents", "Missions", "PendingActions", "ActivityEvent",
               "SimulationEvents", "Users"]


def ensure_admin():
    from app.auth.security import hash_password
    from app.db.repos import users as users_repo
    if users_repo.find_by_username("resqra-admin") is None:
        users_repo.create_user(name="Control Room", role="coordinator",
                               username="resqra-admin",
                               password_hash=hash_password("resqra-admin-123"))


ensure_admin()


def ah():
    return resilient_login(client)


def resilient_login(test_client=None):
    """Login that survives mock-DB flakiness: ensures the admin exists,
    and on 401 re-seeds once and retries instead of failing the suite
    on a wedged mock row."""
    tc = test_client or client

    def _try():
        r = tc.post("/api/auth/admin/login",
                    json={"username": "resqra-admin", "password": "resqra-admin-123"})
        return r

    r = _try()
    if r.status_code == 401:
        ensure_admin()
        r = _try()
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def make_resident(phone, name="Run Resident"):
    r = client.post("/api/auth/otp/request", json={"phone": phone, "name": name})
    assert r.status_code == 200, r.text
    code = r.json()["dev_code"]
    r = client.post("/api/auth/otp/verify",
                    json={"phone": phone, "code": code, "name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _has_run(item: dict, run_id: str) -> bool:
    if item.get("run_id") == run_id:
        return True
    payload = item.get("payload")
    if isinstance(payload, dict) and payload.get("run_id") == run_id:
        return True
    event = item.get("event")
    if isinstance(event, dict):
        inner = event.get("payload") or {}
        if isinstance(inner, dict) and inner.get("run_id") == run_id:
            return True
    return False


def wipe_run_everything(run_id: str, extra_teams=(), extra_phones=()) -> None:
    for tname in _RUN_TABLES:
        tbl = table(tname)
        try:
            items = tbl.scan().get("Items", [])
        except Exception:
            continue
        keys = [k["AttributeName"] for k in tbl.key_schema]
        for it in items:
            if not _has_run(it, run_id):
                continue
            try:
                tbl.delete_item(Key={k: it[k] for k in keys})
            except Exception:
                pass
    for tid in extra_teams:
        try:
            table("Teams").delete_item(Key={"id": tid})
        except Exception:
            pass
    for phone in extra_phones:
        try:
            from app.db.repos import users as users_repo
            u = users_repo.find_by_phone(phone)
            if u:
                table("Users").delete_item(Key={"id": u["id"]})
        except Exception:
            pass
    try:
        table("SimulationRuns").delete_item(Key={"id": run_id})
    except Exception:
        pass
