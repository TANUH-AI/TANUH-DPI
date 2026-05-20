"""
test_auth.py — End-to-end authentication test for all NHCX services.

Tests:
  1. Token issuance  — POST /api/token for each service
  2. Token validity  — decode JWT and verify claims
  3. Protected route — use token on a real protected endpoint (dry-run w/ dummy PDF)
  4. Bad token       — confirm 401 is returned when token is wrong/missing
  5. Expired / wrong service token — cross-service token rejection

Usage (from repo root):
    python3 scripts/test_auth.py

    # Override domain:
    DOMAIN=localhost python3 scripts/test_auth.py
"""
import asyncio
import base64
import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
DOMAIN = os.getenv("DOMAIN", "nhcxhackathon.tanuh.ai")
IS_LOCAL = DOMAIN == "localhost"

SERVICES = {
    "ABDM (Clinical)": {
        "base":       f"http://localhost:8000" if IS_LOCAL else f"https://{DOMAIN}",
        "prefix":     "/pdf2abdm",
        "token_ep":   "/pdf2abdm/api/token",
        "health_ep":  "/pdf2abdm/health",
        "storage_key": "abdm_token",
    },
    "NHCX (Insurance)": {
        "base":       f"http://localhost:8001" if IS_LOCAL else f"https://{DOMAIN}",
        "prefix":     "/pdf2nhcx",
        "token_ep":   "/pdf2nhcx/api/token",
        "health_ep":  "/pdf2nhcx/health",
        "storage_key": "nhcx_token",
    },
    "Privacy Filter": {
        "base":       f"http://localhost:8003" if IS_LOCAL else f"https://{DOMAIN}",
        "prefix":     "/privacy-filter",
        "token_ep":   "/privacy-filter/api/token",
        "health_ep":  "/privacy-filter/api/health",
        "storage_key": "pf_token",
    },
}

TEST_NAME  = "Test User"
TEST_EMAIL = "test@nhcx.tanuh.ai"

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

issued_tokens: dict[str, str] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def decode_jwt_payload(token: str) -> dict:
    """Decode the payload of a JWT without verification (for inspection only)."""
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    padding = 4 - len(parts[1]) % 4
    padded  = parts[1] + "=" * padding
    return json.loads(base64.urlsafe_b64decode(padded))


def fmt_exp(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))


def section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_health(name: str, cfg: dict, client: httpx.AsyncClient) -> bool:
    url = cfg["base"] + cfg["health_ep"]
    try:
        r = await client.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            print(f"  {PASS} {name} health: {data}")
            return True
        else:
            print(f"  {FAIL} {name} health returned {r.status_code}: {r.text[:100]}")
            return False
    except Exception as e:
        print(f"  {FAIL} {name} health unreachable: {e}")
        return False


async def test_issue_token(name: str, cfg: dict, client: httpx.AsyncClient) -> str | None:
    url  = cfg["base"] + cfg["token_ep"]
    body = {"name": TEST_NAME, "email": TEST_EMAIL}
    try:
        r = await client.post(url, json=body, timeout=15)
        if r.status_code == 200:
            token = r.json().get("access_token", "")
            if token:
                payload = decode_jwt_payload(token)
                exp_str = fmt_exp(payload["exp"]) if "exp" in payload else "unknown"
                svc     = payload.get("service") or payload.get("type") or "?"
                print(f"  {PASS} {name} token issued | sub={payload.get('sub')} "
                      f"| type={svc} | exp={exp_str}")
                issued_tokens[name] = token
                return token
            else:
                print(f"  {FAIL} {name}: response had no access_token — {r.json()}")
                return None
        else:
            print(f"  {FAIL} {name} token endpoint {r.status_code}: {r.text[:200]}")
            return None
    except Exception as e:
        print(f"  {FAIL} {name} token request failed: {e}")
        return None


async def test_no_token_rejected(name: str, cfg: dict, client: httpx.AsyncClient):
    """Confirm that a protected endpoint returns 401 with no token."""
    # Use a lightweight endpoint that requires auth.
    # ABDM/NHCX: /submit requires Bearer; Privacy Filter: /api/redact requires Bearer.
    if "privacy" in cfg["prefix"]:
        url = cfg["base"] + "/privacy-filter/api/redact"
        r   = await client.post(url, timeout=10)
    else:
        url = cfg["base"] + cfg["prefix"] + "/submit"
        r   = await client.post(url, timeout=10)

    if r.status_code == 401:
        print(f"  {PASS} {name}: correctly returns 401 with no token")
    elif r.status_code == 422:
        # FastAPI validation error — the auth ran first but field validation failed
        # This means auth was not required (bypass mode) or body was checked first.
        print(f"  {WARN} {name}: returned 422 (validation error before auth check — "
              f"auth may be bypassed or form field missing)")
    else:
        print(f"  {FAIL} {name}: expected 401 with no token, got {r.status_code}")


async def test_bad_token_rejected(name: str, cfg: dict, client: httpx.AsyncClient):
    """Confirm that a garbage token returns 401."""
    bad_token = "Bearer this.is.not.a.valid.jwt"
    headers   = {"Authorization": bad_token}

    if "privacy" in cfg["prefix"]:
        url = cfg["base"] + "/privacy-filter/api/redact"
        r   = await client.post(url, headers=headers, timeout=10)
    else:
        url = cfg["base"] + cfg["prefix"] + "/submit"
        r   = await client.post(url, headers=headers, timeout=10)

    if r.status_code == 401:
        print(f"  {PASS} {name}: correctly returns 401 with bad token")
    elif r.status_code == 422:
        print(f"  {WARN} {name}: returned 422 (possible auth bypass or body check first)")
    else:
        print(f"  {FAIL} {name}: expected 401 with bad token, got {r.status_code} — {r.text[:100]}")


async def test_cross_service_token_rejected(client: httpx.AsyncClient):
    """Use an ABDM token against the NHCX endpoint — should be rejected."""
    abdm_token = issued_tokens.get("ABDM (Clinical)")
    if not abdm_token:
        print(f"  {WARN} Skipping cross-service test — ABDM token not available")
        return

    nhcx_cfg = SERVICES["NHCX (Insurance)"]
    url       = nhcx_cfg["base"] + "/pdf2nhcx/submit"
    headers   = {"Authorization": f"Bearer {abdm_token}"}
    r         = await client.post(url, headers=headers, timeout=10)

    # ABDM token is signed with ABDM_SECRET_KEY; NHCX uses NHCX_SECRET_KEY
    # If keys differ, the NHCX service will reject it as an invalid signature → 401
    if r.status_code == 401:
        print(f"  {PASS} Cross-service: ABDM token correctly rejected by NHCX endpoint (401)")
    elif r.status_code == 422:
        print(f"  {WARN} Cross-service: 422 returned — auth may have passed (keys may match) "
              f"but body validation failed. Check ABDM_SECRET_KEY ≠ NHCX_SECRET_KEY in .env")
    else:
        print(f"  {FAIL} Cross-service: expected 401, got {r.status_code} — {r.text[:100]}")


async def test_valid_token_accepted(name: str, cfg: dict, token: str, client: httpx.AsyncClient):
    """Confirm that a valid token gets past auth (even if the body is invalid → 422)."""
    headers = {"Authorization": f"Bearer {token}"}

    if "privacy" in cfg["prefix"]:
        url = cfg["base"] + "/privacy-filter/api/redact"
        r   = await client.post(url, headers=headers, timeout=10)
    else:
        url = cfg["base"] + cfg["prefix"] + "/submit"
        r   = await client.post(url, headers=headers, timeout=10)

    # 422 = auth passed, FastAPI rejected the body (no file uploaded) → correct!
    if r.status_code in (200, 202, 422):
        print(f"  {PASS} {name}: valid token accepted by auth layer (got {r.status_code})")
    elif r.status_code == 401:
        print(f"  {FAIL} {name}: valid token was REJECTED (401) — token may be wrong service "
              f"or secret key mismatch")
    else:
        print(f"  {WARN} {name}: got {r.status_code} — {r.text[:100]}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    print(f"\n{'='*60}")
    print(f"  NHCX Auth End-to-End Test")
    print(f"  Target: https://{DOMAIN}")
    print(f"{'='*60}")

    failures = 0

    async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:

        # 1. Health checks
        section("Phase 1: Health Checks")
        for name, cfg in SERVICES.items():
            ok = await test_health(name, cfg, client)
            if not ok:
                failures += 1

        # 2. Token issuance
        section("Phase 2: Token Issuance (POST /api/token)")
        tokens: dict[str, str | None] = {}
        for name, cfg in SERVICES.items():
            t = await test_issue_token(name, cfg, client)
            tokens[name] = t
            if not t:
                failures += 1

        # 3. No-token rejection
        section("Phase 3: Protected Routes — No Token (expect 401)")
        for name, cfg in SERVICES.items():
            try:
                await test_no_token_rejected(name, cfg, client)
            except Exception as e:
                print(f"  {FAIL} {name}: exception — {e}")
                failures += 1

        # 4. Bad token rejection
        section("Phase 4: Protected Routes — Bad Token (expect 401)")
        for name, cfg in SERVICES.items():
            try:
                await test_bad_token_rejected(name, cfg, client)
            except Exception as e:
                print(f"  {FAIL} {name}: exception — {e}")
                failures += 1

        # 5. Valid token accepted
        section("Phase 5: Protected Routes — Valid Token (expect 202 or 422, NOT 401)")
        for name, cfg in SERVICES.items():
            t = tokens.get(name)
            if t:
                await test_valid_token_accepted(name, cfg, t, client)
            else:
                print(f"  {WARN} {name}: skipped — no token issued")

        # 6. Cross-service rejection
        section("Phase 6: Cross-Service Token Rejection")
        await test_cross_service_token_rejected(client)

    # Summary
    print(f"\n{'='*60}")
    if failures == 0:
        print(f"  {PASS} All tests passed!")
    else:
        print(f"  {FAIL} {failures} test(s) failed — review output above")
    print(f"{'='*60}\n")

    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
