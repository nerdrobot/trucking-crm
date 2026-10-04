"""Scoped capabilities for assistant tools; never expose the shared signing secret.

A token authorizes one dispatch's outcome only. The route must resolve its tenant
from the stored voice job and retain idempotency/final-state checks. Tokens do not
expire because delayed provider delivery must still record an opt-out. Rotate the
secret to revoke outstanding capabilities; never log payloads containing tokens.
"""

import hashlib
import hmac
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssistantOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    dispatch_id: str = Field(min_length=1, max_length=128)
    outcome_token: str = Field(pattern=r"^[a-f0-9]{64}$", repr=False)
    outcome: Literal["interested", "not_now", "opt_out", "human_requested", "appointment_requested"]
    summary: str = Field(min_length=1, max_length=2000)


def issue_outcome_token(secret: str, tenant_id: str, dispatch_id: str) -> str:
    if len(secret) < 32 or not tenant_id or not dispatch_id:
        raise ValueError("Voice outcome signing needs a strong secret and stored dispatch identity")
    # JSON array avoids delimiter ambiguity and includes a versioned purpose tag.
    message = json.dumps(
        ["voice-outcome-v1", tenant_id, dispatch_id], separators=(",", ":")
    ).encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_outcome_token(token: str, secret: str, tenant_id: str, dispatch_id: str) -> bool:
    if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token):
        return False
    try:
        expected = issue_outcome_token(secret, tenant_id, dispatch_id)
    except ValueError:
        return False
    return hmac.compare_digest(token, expected)
