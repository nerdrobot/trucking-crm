import base64
import binascii
import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass, field

from followup.providers import ProviderConfig


@dataclass(frozen=True)
class Settings:
    tenant_id: str
    users: tuple
    mode: str = "demo"
    webhook_public_key: str = ""
    frontend_origins: tuple = ()
    voice_outcome_secret: str = ""
    enable_live_send: bool = False
    provider_config: ProviderConfig = field(default_factory=ProviderConfig)

    def __post_init__(self):
        if not self.tenant_id or not self.users or self.mode not in {"demo", "live"}:
            raise ValueError("Tenant, users and valid mode required")
        ids = set()
        for user in self.users:
            if (
                not user.get("id")
                or user["id"] in ids
                or not user.get("name")
                or user.get("role") not in {"admin", "agent"}
                or not re.fullmatch(r"[0-9a-f]{64}", user.get("token_sha256", ""))
                or not re.fullmatch(r"(\+[1-9]\d{7,14})?", user.get("phone", ""))
            ):
                raise ValueError("Invalid pilot users")
            ids.add(user["id"])

    @classmethod
    def from_env(cls, env):
        def get(key, default=""):
            return env.get(key, default) if hasattr(env, "get") else getattr(env, key, default)

        mode = get("PILOT_MODE", "demo")
        return cls(
            tenant_id=get("PILOT_TENANT_ID"),
            users=tuple(json.loads(get("PILOT_USERS_JSON", "[]"))),
            mode=mode,
            webhook_public_key=get("TELNYX_PUBLIC_KEY"),
            voice_outcome_secret=get("VOICE_OUTCOME_SECRET"),
            frontend_origins=tuple(
                x.strip() for x in get("FRONTEND_ORIGINS").split(",") if x.strip()
            ),
            enable_live_send=get("ENABLE_LIVE_SEND") == "true",
            provider_config=ProviderConfig(
                mode=mode,
                enable_live_send=get("ENABLE_LIVE_SEND") == "true",
                api_key=get("TELNYX_API_KEY"),
                from_number=get("TELNYX_FROM_NUMBER"),
                messaging_profile_id=get("TELNYX_MESSAGING_PROFILE_ID"),
                assistant_id=get("TELNYX_ASSISTANT_ID"),
                connection_id=get("TELNYX_CONNECTION_ID"),
                credential_connection_id=get("TELNYX_CREDENTIAL_CONNECTION_ID"),
                max_call_duration_seconds=int(get("TELNYX_MAX_CALL_SECONDS", "120")),
                email_from=get("TELNYX_EMAIL_FROM"),
                email_from_name=get("TELNYX_EMAIL_FROM_NAME"),
            ),
        )

    def authenticate(self, authorization):
        if not authorization.startswith("Bearer ") or len(authorization) < 39:
            return None
        digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
        return next(
            (dict(u) for u in self.users if secrets.compare_digest(digest, u["token_sha256"])), None
        )


async def webcrypto_verify(key_bytes, signature_bytes, message):
    from js import Uint8Array, crypto
    from pyodide.ffi import to_js

    key = await crypto.subtle.importKey(
        "raw", Uint8Array.new(to_js(list(key_bytes))), "Ed25519", False, to_js(["verify"])
    )
    return await crypto.subtle.verify(
        "Ed25519",
        key,
        Uint8Array.new(to_js(list(signature_bytes))),
        Uint8Array.new(to_js(list(message))),
    )


async def verify_webhook(public_key, timestamp, signature, body, verifier):
    try:
        if len(timestamp) > 12 or not timestamp.isascii() or not timestamp.isdecimal():
            return False
        if abs(time.time() - int(timestamp)) > 300:
            return False
        key = base64.b64decode(public_key, validate=True)
        decoded_signature = base64.b64decode(signature, validate=True)
        if len(decoded_signature) != 64:
            return False
        return await verifier(key, decoded_signature, timestamp.encode() + b"|" + body)
    except (ValueError, TypeError, binascii.Error):
        return False
