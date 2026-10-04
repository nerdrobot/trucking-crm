import hashlib
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from followup.app import create_app
from followup.local import SQLiteDatabase
from followup.security import Settings

TOKEN = "a" * 48


def client():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    for migration in sorted(Path("migrations").glob("*.sql")):
        connection.executescript(migration.read_text())
    config = Settings(
        tenant_id="pilot",
        users=(
            {
                "id": "admin",
                "name": "Admin",
                "role": "admin",
                "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
            },
        ),
    )
    return TestClient(
        create_app(SQLiteDatabase(connection), config), headers={"Authorization": f"Bearer {TOKEN}"}
    )


def test_full_demo_flow():
    with client() as api:
        assert api.get("/api/me").json()["data"]["mode"] == "demo"
        lead = api.post(
            "/api/leads",
            json={
                "name": "Buyer",
                "phone": "+15551234567",
                "consent_sms": True,
                "consent_note": "Test opt in",
            },
        ).json()["data"]
        sequence = api.post(
            "/api/sequences",
            json={
                "name": "Welcome",
                "steps": [{"channel": "sms", "delay_minutes": 0, "message": "Hi {name}"}],
            },
        ).json()["data"]
        assert (
            api.post(
                f"/api/leads/{lead['id']}/enroll", json={"sequence_id": sequence["id"]}
            ).status_code
            == 200
        )
        assert (
            api.post(
                f"/api/leads/{lead['id']}/enroll", json={"sequence_id": sequence["id"]}
            ).status_code
            == 409
        )
        assert (
            api.post(f"/api/leads/{lead['id']}/demo-reply", json={"text": "STOP"}).status_code
            == 200
        )
        assert api.get(f"/api/leads/{lead['id']}").json()["data"]["lead"]["status"] == "opted_out"
        assert (
            api.post(f"/api/leads/{lead['id']}/message", json={"text": "hello"}).status_code == 409
        )
