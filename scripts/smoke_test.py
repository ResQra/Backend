"""End-to-end smoke test for the ResQra stack against a RUNNING server.

Usage:
    python scripts/smoke_test.py [base_url] [admin_user] [admin_pass]

Defaults: http://localhost:8000, resqra-admin / new-pass-789
Exercises: OTP login, admin login, role guard, chat (+Groq), incident with
GPS + landmark-geocoded + garbage-flagged, queue, assign, status, advisory,
public map-data, activity feed. Prints PASS/FAIL per step, exits non-zero on
any failure.
"""

import pathlib
import sys
import time
import urllib.request
import urllib.error
import json


BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
ADMIN_USER = sys.argv[2] if len(sys.argv) > 2 else "resqra-admin"
ADMIN_PASS = sys.argv[3] if len(sys.argv) > 3 else "new-pass-789"

results = []


def call(method, path, token=None, body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def main():
    phone = f"9{int(time.time()) % 10**9:09d}"

    s, health = call("GET", "/api/health")
    check("health", s == 200 and health.get("status") == "ok")

    s, r = call("POST", "/api/auth/otp/request", body={"phone": phone, "name": "Smoke Tester"})
    code = r.get("dev_code")
    check("otp request (dev code issued)", s == 200 and code)

    s, r = call("POST", "/api/auth/otp/verify", body={"phone": phone, "code": "000000", "name": "Smoke Tester"})
    check("otp wrong code rejected", s == 401)

    s, r = call("POST", "/api/auth/otp/verify", body={"phone": phone, "code": code, "name": "Smoke Tester"})
    check("otp verify → resident token", s == 200 and r.get("role") == "resident")
    rt = r.get("token")

    s, r = call("GET", "/api/ops/queue", token=rt)
    check("resident blocked from ops (403)", s == 403)

    s, r = call("POST", "/api/auth/admin/login", body={"username": ADMIN_USER, "password": "wrong-pass"})
    check("admin wrong password rejected", s in (401, 422))

    s, r = call("POST", "/api/auth/admin/login", body={"username": ADMIN_USER, "password": ADMIN_PASS})
    check("admin login", s == 200 and r.get("role") == "coordinator" and r.get("name"))
    at = r.get("token")

    s, r = call("POST", "/api/chat", token=rt, body={"message": "We are 4 people on a rooftop in Kankarbagh, one child, water rising"})
    check("chat (Groq reply)", s == 200 and len(r.get("reply", "")) > 20)

    s, r = call("POST", "/api/incidents", token=rt, body={
        "raw_text": "smoke: rooftop SOS", "people": 4, "urgency": "HIGH",
        "location": {"lat": 25.5812, "lng": 85.1471, "label": "GPS", "confidence": 1.0}})
    check("incident w/ GPS created", s == 200 and r.get("location_verification") == "GPS")
    inc_gps = r.get("id")

    s, r = call("POST", "/api/incidents", token=rt, body={
        "raw_text": "smoke: landmark SOS", "location_text": "Kankarbagh, Patna"})
    check("incident geocoded from landmark", s == 200 and r.get("location_verification") == "GEOCODED" and r.get("location"))

    s, r = call("POST", "/api/incidents", token=rt, body={
        "raw_text": "smoke: garbage loc", "location_text": "zzqqxx-no-such-place"})
    check("garbage location flagged for review", s == 200 and r.get("location_verification") == "NEEDS_COORDINATOR_REVIEW")

    s, r = call("GET", "/api/ops/queue", token=at)
    ids = [i["id"] for i in r.get("incidents", [])]
    check("coordinator queue lists incidents", s == 200 and inc_gps in ids)

    s, r = call("POST", f"/api/ops/incidents/{inc_gps}/assign", token=at, body={"team_id": "team_beta"})
    check("team assigned", s == 200 and r.get("status") == "ASSIGNED")

    s, r = call("PATCH", f"/api/ops/incidents/{inc_gps}/status", token=at, body={"status": "IN_PROGRESS"})
    check("status advanced", s == 200 and r.get("status") == "IN_PROGRESS")

    s, r = call("POST", "/api/ops/reports", token=at, body={
        "title": "Smoke advisory", "body": "Test advisory body", "severity": "INFO", "source": "smoke"})
    check("advisory published", s == 200)

    s, r = call("GET", "/api/public/reports", token=rt)
    check("resident sees advisory", s == 200 and any(x.get("title") == "Smoke advisory" for x in r.get("reports", [])))

    s, r = call("GET", "/api/public/map-data", token=rt)
    check("public map-data", s == 200 and len(r.get("shelters", [])) > 0)

    s, r = call("GET", "/api/ops/activity", token=at)
    check("activity feed populated", s == 200 and len(r.get("events", [])) > 0)

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f" — FAILURES: {failed}" if failed else " — ALL GREEN"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
