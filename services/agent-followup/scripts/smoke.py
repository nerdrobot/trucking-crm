"""Exercise the actual Python Worker/D1 runtime with synthetic contacts only."""

import argparse
import base64
import hashlib
import json
import secrets
import time
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

parser = argparse.ArgumentParser()
parser.add_argument("action", choices=["prepare", "run"])
parser.add_argument("--force", action="store_true")
args = parser.parse_args()
state_path = Path(".local-smoke.json")
if args.action == "prepare":
    if (state_path.exists() or Path(".dev.vars").exists()) and not args.force:
        parser.error("Local credentials exist; use --force to back up and regenerate.")
    if Path(".dev.vars").exists():
        backup = Path(".dev.vars.backup-" + secrets.token_hex(4))
        backup.write_bytes(Path(".dev.vars").read_bytes())
        backup.chmod(0o600)
    key = Ed25519PrivateKey.generate()
    token = secrets.token_urlsafe(36)
    state_path.write_text(json.dumps({"token": token, "key": key.private_bytes_raw().hex()}))
    state_path.chmod(0o600)
    users = [
        {
            "id": "smoke-admin",
            "name": "Smoke Admin",
            "role": "admin",
            "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        }
    ]
    Path(".dev.vars").write_text(
        "PILOT_MODE=demo\nPILOT_TENANT_ID=smoke-pilot\nENABLE_LIVE_SEND=false\nPILOT_USERS_JSON="
        + "'"
        + json.dumps(users)
        + "'"
        + "\nTELNYX_PUBLIC_KEY="
        + base64.b64encode(key.public_key().public_bytes_raw()).decode()
        + "\n"
    )
    Path(".dev.vars").chmod(0o600)
    print("Prepared local synthetic-only smoke configuration.")
else:
    state = json.loads(state_path.read_text())
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(state["key"]))
    with httpx.Client(
        base_url="http://127.0.0.1:8787",
        timeout=60,
        headers={"Authorization": "Bearer " + state["token"]},
    ) as client:
        assert client.get("/api/me").json()["data"]["mode"] == "demo"
        response = client.post(
            "/api/leads",
            json={
                "name": "Synthetic smoke lead",
                "phone": "+1555" + str(secrets.randbelow(9000000) + 1000000),
                "consent_sms": True,
                "consent_voice": True,
                "consent_note": "Synthetic fixture",
            },
        )
        response.raise_for_status()
        lead = response.json()["data"]
        sequence = client.post(
            "/api/sequences",
            json={
                "name": "Smoke cadence",
                "steps": [
                    {"channel": "sms", "delay_minutes": 0, "message": "Hello {name}"},
                    {"channel": "voice", "delay_minutes": 0, "message": "Ask about buying plans"},
                ],
            },
        )
        sequence.raise_for_status()
        client.post(
            "/api/leads/" + lead["id"] + "/enroll",
            json={"sequence_id": sequence.json()["data"]["id"]},
        ).raise_for_status()
        response = client.get("/cdn-cgi/handler/scheduled?cron=%2A+%2A+%2A+%2A+%2A")
        response.raise_for_status()
        time.sleep(2)
        detail = client.get("/api/leads/" + lead["id"]).json()["data"]
        assert len(detail["jobs"]) == 2 and {j["status"] for j in detail["jobs"]} == {
            "delivered",
            "completed",
        }, detail
        payload = {
            "data": {
                "id": secrets.token_hex(16),
                "event_type": "message.received",
                "payload": {
                    "from": {"phone_number": lead["phone"]},
                    "to": [{"phone_number": "+15550000000"}],
                    "text": "STOP",
                },
            }
        }
        raw = json.dumps(payload).encode()
        stamp = str(int(time.time()))
        headers = {
            "telnyx-timestamp": stamp,
            "telnyx-signature-ed25519": base64.b64encode(
                key.sign(stamp.encode() + b"|" + raw)
            ).decode(),
        }
        response = client.post("/api/webhooks/telnyx", content=raw, headers=headers)
        response.raise_for_status()
        assert client.post("/api/webhooks/telnyx", content=raw, headers=headers).json()["data"][
            "duplicate"
        ]
        assert (
            client.get("/api/leads/" + lead["id"]).json()["data"]["lead"]["status"] == "opted_out"
        )
        assert (
            client.post(
                "/api/leads/" + lead["id"] + "/message", json={"text": "Must not send"}
            ).status_code
            == 409
        )
        print(
            "PASS: actual Worker auth, D1, sequence, scheduled SMS + voice, WebCrypto signature, deduplication, permanent opt-out."
        )
