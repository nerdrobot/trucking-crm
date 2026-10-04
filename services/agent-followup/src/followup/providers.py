"""Telnyx outbound transport. No automatic retries after an ambiguous submission."""

import asyncio
import base64
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from urllib.parse import urlencode


class ProviderError(Exception):
    def __init__(self, message, safe_to_retry=False):
        super().__init__(message)
        self.safe_to_retry = safe_to_retry


class ProviderRejected(ProviderError):
    """Submission was rejected or never attempted."""


class ProviderAmbiguousError(ProviderError):
    """May have been accepted; reconcile webhooks/provider logs before another attempt."""


@dataclass(frozen=True)
class ProviderConfig:
    mode: str = "demo"
    enable_live_send: bool = False
    api_key: str = field(default="", repr=False)
    from_number: str = ""
    messaging_profile_id: str = ""
    assistant_id: str = ""
    connection_id: str = ""
    credential_connection_id: str = ""
    max_call_duration_seconds: int = 120
    email_from: str = ""
    email_from_name: str = ""


@dataclass(frozen=True)
class SendResult:
    provider_id: str
    status: str
    metadata: Mapping = field(default_factory=lambda: MappingProxyType({}))


# The dispatcher's leg of a click-to-call rings either their phone or their browser dialer.
AGENT_SIP = re.compile(r"sip:[A-Za-z0-9_.\-]{1,64}@sip\.telnyx\.com")


def _validate_agent(to, dispatch_id):
    if not AGENT_SIP.fullmatch(to or ""):
        _validate(to, dispatch_id)
    elif not dispatch_id or len(dispatch_id) > 128:
        raise ProviderRejected("A dispatch identifier is required")


def _validate(to, dispatch_id, text=None):
    if not re.fullmatch(r"\+[1-9]\d{7,14}", to or ""):
        raise ProviderRejected("A valid E.164 destination is required")
    if not dispatch_id or len(dispatch_id) > 128:
        raise ProviderRejected("A dispatch identifier is required")
    if text is not None and (not text.strip() or len(text) > 1600):
        raise ProviderRejected("Message must contain between 1 and 1600 characters")


EMAIL = re.compile(r"[^@\s<>\"]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def valid_email(value):
    return bool(EMAIL.fullmatch(value or "")) and len(value) <= 254


def _validate_email(to, subject, text, dispatch_id):
    if not valid_email(to):
        raise ProviderRejected("A valid email address is required")
    if not dispatch_id or len(dispatch_id) > 128:
        raise ProviderRejected("A dispatch identifier is required")
    if not subject.strip() or len(subject) > 200 or "\n" in subject or "\r" in subject:
        raise ProviderRejected("Email subject must contain between 1 and 200 characters")
    if not text.strip() or len(text) > 20000:
        raise ProviderRejected("Email body must contain between 1 and 20000 characters")


async def request_json(method, url, headers, payload):
    """Workers uses native fetch; local development uses the optional httpx extra."""
    if sys.platform == "emscripten":
        from workers import fetch

        # Workers rejects redirect="error"; "manual" surfaces a 3xx, which _post treats as ambiguous.
        response = await fetch(
            url,
            method=method,
            headers=headers,
            body=None if payload is None else json.dumps(payload),
            redirect="manual",
        )
        # Parse only successful responses: provider error pages may not contain JSON.
        text = await response.text() if 200 <= response.status < 300 else ""
        return response.status, _parse(text)
    import httpx

    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        response = await client.request(method, url, headers=headers, json=payload)
        return response.status_code, _parse(response.text) if response.is_success else {}


def _parse(text):
    """Most Telnyx responses are JSON; WebRTC login tokens come back as plain text."""
    if not text:
        return {}
    try:
        return json.loads(text)
    except ValueError:
        return {"text": text}


class DemoProvider:
    async def send_sms(self, to, text, dispatch_id):
        _validate(to, dispatch_id, text)
        return SendResult(
            f"demo-sms-{dispatch_id}",
            "delivered",
            MappingProxyType(
                {
                    "simulated": True,
                    "summary": "Simulated SMS delivered. No message was sent.",
                }
            ),
        )

    async def send_email(self, to, subject, text, dispatch_id):
        _validate_email(to, subject, text, dispatch_id)
        return SendResult(
            f"demo-email-{dispatch_id}",
            "delivered",
            MappingProxyType(
                {"simulated": True, "summary": "Simulated email delivered. No email was sent."}
            ),
        )

    async def start_call(self, to, dispatch_id, context=None):
        _validate(to, dispatch_id)
        return SendResult(
            f"demo-call-{dispatch_id}",
            "completed",
            MappingProxyType(
                {
                    "simulated": True,
                    "summary": "Simulated AI follow-up completed. No call was placed.",
                    "duration_seconds": 45,
                }
            ),
        )

    async def list_numbers(self):
        return [
            {"phone_number": "+13055550100", "status": "active", "label": "Demo number"},
            {"phone_number": "+14075550111", "status": "active", "label": "Demo number"},
        ]

    async def search_numbers(self, state, area_code=""):
        prefix = area_code or {"FL": "305"}.get(state, "555")
        return [
            {
                "phone_number": f"+1{prefix}555{index:04d}",
                "locality": "Demo city",
                "state": state,
                "upfront_cost": "1.00",
                "monthly_cost": "1.00",
                "currency": "USD",
            }
            for index in range(1, 4)
        ]

    async def channel_options(self):
        return {
            "messaging_profiles": [{"id": "demo-profile", "name": "Demo messaging profile"}],
            "voice_apps": [{"id": "demo-voice-app", "name": "Demo voice app"}],
            "assistants": [{"id": "demo-assistant", "name": "Demo AI assistant"}],
        }

    async def order_number(self, phone_number):
        return SendResult(
            "demo-order",
            "success",
            MappingProxyType(
                {"simulated": True, "summary": "Simulated order. Nothing was bought."}
            ),
        )

    async def start_bridge(self, agent_phone, dispatch_id):
        _validate_agent(agent_phone, dispatch_id)
        device = "browser" if agent_phone.startswith("sip:") else "phone"
        return SendResult(
            f"demo-bridge-{dispatch_id}",
            "completed",
            MappingProxyType(
                {
                    "simulated": True,
                    "summary": f"Simulated: your {device} rang and connected to the lead. No call was placed.",
                }
            ),
        )

    async def create_credential(self, name):
        return {"id": "demo-credential", "sip_username": "demo"}

    async def credential_token(self, credential_id):
        return ""

    async def forward_call(self, call_control_id, to, caller):
        return SendResult("", "queued", MappingProxyType({"simulated": True}))


@dataclass(frozen=True)
class TelnyxProvider:
    config: ProviderConfig
    request: object = request_json

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _get(self, path, params):
        try:
            status, response = await asyncio.wait_for(
                self.request(
                    "GET",
                    f"https://api.telnyx.com/v2/{path}?{urlencode(params, doseq=True)}",
                    self._headers(),
                    None,
                ),
                timeout=25,
            )
        except Exception:  # noqa: BLE001 - never echo transport errors; reads are safe to repeat
            raise ProviderRejected("Telnyx could not be reached", safe_to_retry=True) from None
        if status == 400:
            return []  # Telnyx reports "no numbers match" as a 400.
        if status != 200:
            raise ProviderRejected(f"Provider rejected request (HTTP {status})")
        data = response.get("data") if isinstance(response, dict) else None
        return data if isinstance(data, list) else []

    async def list_numbers(self):
        rows = await self._get("phone_numbers", {"page[size]": 100})
        return [
            {
                "phone_number": row.get("phone_number"),
                "status": row.get("status"),
                "label": row.get("connection_name") or "",
            }
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("phone_number"), str)
        ]

    async def search_numbers(self, state, area_code=""):
        params = {
            "filter[country_code]": "US",
            "filter[administrative_area]": state,
            "filter[features]": ["voice", "sms"],
            "filter[limit]": 10,
        }
        if area_code:
            params["filter[national_destination_code]"] = area_code
        results = []
        for row in await self._get("available_phone_numbers", params):
            regions = {
                r.get("region_type"): r.get("region_name")
                for r in row.get("region_information", [])
            }
            cost = row.get("cost_information") or {}
            results.append(
                {
                    "phone_number": row.get("phone_number"),
                    "locality": (regions.get("location") or "").title(),
                    "state": regions.get("state") or state,
                    "upfront_cost": cost.get("upfront_cost"),
                    "monthly_cost": cost.get("monthly_cost"),
                    "currency": cost.get("currency", "USD"),
                }
            )
        return results

    async def channel_options(self):
        def pick(rows, name_field):
            return [
                {"id": str(row["id"]), "name": row.get(name_field) or str(row["id"])}
                for row in rows
                if isinstance(row, dict) and row.get("id")
            ]

        page = {"page[size]": 100}
        return {
            "messaging_profiles": pick(await self._get("messaging_profiles", page), "name"),
            "voice_apps": pick(
                await self._get("call_control_applications", page), "application_name"
            ),
            "assistants": pick(await self._get("ai/assistants", {}), "name"),
        }

    async def order_number(self, phone_number):
        """Buy a number and route it to the Call Control app. Never retried automatically."""
        _validate(phone_number, "order")
        payload = {"phone_numbers": [{"phone_number": phone_number}]}
        if self.config.connection_id:
            payload["connection_id"] = self.config.connection_id
        if self.config.messaging_profile_id:
            payload["messaging_profile_id"] = self.config.messaging_profile_id
        result = await self._post("number_orders", payload, "id")
        return replace(result, status="pending")

    async def _post(self, path, payload, id_field, extra_headers=None):
        headers = self._headers() | (extra_headers or {})
        try:
            status, response = await asyncio.wait_for(
                self.request("POST", f"https://api.telnyx.com/v2/{path}", headers, payload),
                timeout=25,
            )
        except Exception:  # noqa: BLE001 - any transport failure is an ambiguous side effect
            # Never echo an SDK/network error: it may contain authorization or lead data.
            raise ProviderAmbiguousError("Provider submission outcome is unknown") from None
        if status == 429:
            raise ProviderRejected("Provider rate limit reached", safe_to_retry=True)
        if 400 <= status < 500 and status != 408:
            raise ProviderRejected(f"Provider rejected request (HTTP {status})")
        if not 200 <= status < 300:
            raise ProviderAmbiguousError(f"Provider outcome is unknown (HTTP {status})")
        if id_field is None:
            return SendResult("", "queued", MappingProxyType({"simulated": False}))
        data = response.get("data") if isinstance(response, dict) else None
        provider_id = data.get(id_field) if isinstance(data, dict) else None
        if not isinstance(provider_id, str) or not provider_id:
            raise ProviderAmbiguousError("Provider response omitted the tracking identifier")
        return SendResult(provider_id, "queued", MappingProxyType({"simulated": False}))

    async def send_sms(self, to, text, dispatch_id):
        _validate(to, dispatch_id, text)
        if not self.config.messaging_profile_id:
            raise ProviderRejected("Telnyx messaging profile is required")
        # SMS has no documented client_state/command_id. Persist the returned ID;
        # a timeout must never result in a blind resend.
        return await self._post(
            "messages",
            {
                "from": self.config.from_number,
                "to": to,
                "text": text,
                "type": "SMS",
                "messaging_profile_id": self.config.messaging_profile_id,
            },
            "id",
        )

    async def send_email(self, to, subject, text, dispatch_id):
        _validate_email(to, subject, text, dispatch_id)
        if not valid_email(self.config.email_from):
            raise ProviderRejected("A verified sender email address is required")
        sender = {"email": self.config.email_from}
        if self.config.email_from_name:
            sender["name"] = self.config.email_from_name
        # The idempotency key makes Telnyx replay, not resend, a repeated submission.
        return await self._post(
            "email_messages",
            {
                "from": sender,
                "to": [to],
                "subject": subject,
                "text_body": text,
                "tags": ["followup"],
                "metadata": {"dispatch_id": dispatch_id},
            },
            "id",
            {"Idempotency-Key": dispatch_id},
        )

    async def start_call(self, to, dispatch_id, context=None):
        _validate(to, dispatch_id)
        if not self.config.connection_id or not self.config.assistant_id:
            raise ProviderRejected("Telnyx voice application and assistant are required")
        if context is not None and (
            not isinstance(context, Mapping)
            or any(
                not isinstance(key, str) or not isinstance(value, (str, int, float, bool))
                for key, value in context.items()
            )
        ):
            raise ProviderRejected("Assistant context must contain scalar dynamic variables")
        client_state = base64.b64encode(json.dumps({"dispatch_id": dispatch_id}).encode()).decode()
        return await self._post(
            "calls",
            {
                "from": self.config.from_number,
                "to": to,
                "connection_id": self.config.connection_id,
                "assistant": {
                    "id": self.config.assistant_id,
                    "dynamic_variables": dict(context or {}),
                },
                "command_id": dispatch_id,
                "client_state": client_state,
                "time_limit_secs": self.config.max_call_duration_seconds,
                "timeout_secs": 30,
                "retry_on_timeout": False,
            },
            "call_control_id",
        )

    async def start_bridge(self, agent_phone, dispatch_id):
        """Ring the agent first; the call.answered webhook transfers them to the lead."""
        _validate_agent(agent_phone, dispatch_id)
        if not self.config.connection_id:
            raise ProviderRejected("Telnyx voice application is required")
        return await self._post(
            "calls",
            {
                "from": self.config.from_number,
                "to": agent_phone,
                "connection_id": self.config.connection_id,
                "command_id": dispatch_id,
                "client_state": _state(dispatch_id, "agent"),
                "time_limit_secs": BRIDGE_TIME_LIMIT_SECONDS,
                "timeout_secs": 30,
                "retry_on_timeout": False,
            },
            "call_control_id",
        )

    async def transfer(self, call_control_id, to, dispatch_id):
        _validate(to, dispatch_id)
        if not re.fullmatch(r"[A-Za-z0-9_:\-]{1,256}", call_control_id or ""):
            raise ProviderRejected("A valid call control identifier is required")
        return await self._post(
            f"calls/{call_control_id}/actions/transfer",
            {
                "to": to,
                "from": self.config.from_number,
                "client_state": _state(dispatch_id, "lead"),
                "command_id": dispatch_id + "-transfer",
                "timeout_secs": 30,
            },
            None,
        )

    async def create_credential(self, name):
        """A per-dispatcher login for the browser dialer, under the WebRTC credential connection."""
        if not self.config.credential_connection_id:
            raise ProviderRejected("Telnyx browser calling connection is required")
        data = await self._call(
            "telephony_credentials",
            {"connection_id": self.config.credential_connection_id, "name": name[:100]},
        )
        record = data.get("data") if isinstance(data.get("data"), dict) else {}
        if not record.get("id") or not AGENT_SIP.fullmatch(
            f"sip:{record.get('sip_username')}@sip.telnyx.com"
        ):
            raise ProviderAmbiguousError("Provider response omitted the credential")
        return {"id": str(record["id"]), "sip_username": record["sip_username"]}

    async def credential_token(self, credential_id):
        if not re.fullmatch(r"[A-Za-z0-9\-]{1,100}", credential_id or ""):
            raise ProviderRejected("A valid credential identifier is required")
        token = (await self._call(f"telephony_credentials/{credential_id}/token", None)).get("text")
        if not isinstance(token, str) or not token:
            raise ProviderAmbiguousError("Provider response omitted the login token")
        return token

    async def forward_call(self, call_control_id, to, caller):
        """Ring a dispatcher's browser with an incoming call, showing who is calling."""
        if not re.fullmatch(r"[A-Za-z0-9_:\-]{1,256}", call_control_id or ""):
            raise ProviderRejected("A valid call control identifier is required")
        if not AGENT_SIP.fullmatch(to or ""):
            raise ProviderRejected("A valid browser destination is required")
        payload = {"to": to, "timeout_secs": 30}
        if re.fullmatch(r"\+[1-9]\d{7,14}", caller or ""):
            payload["from"] = caller
        return await self._post(f"calls/{call_control_id}/actions/transfer", payload, None)

    async def _call(self, path, payload):
        """POST that returns the whole response; credential calls are safe to repeat."""
        try:
            status, response = await asyncio.wait_for(
                self.request("POST", f"https://api.telnyx.com/v2/{path}", self._headers(), payload),
                timeout=25,
            )
        except Exception:  # noqa: BLE001 - never echo transport errors
            raise ProviderRejected("Telnyx could not be reached", safe_to_retry=True) from None
        if not 200 <= status < 300:
            raise ProviderRejected(f"Provider rejected request (HTTP {status})")
        return response if isinstance(response, dict) else {}


# Agent-to-lead conversations are human calls, so they get a longer cap than AI calls.
BRIDGE_TIME_LIMIT_SECONDS = 1800


def _state(dispatch_id, leg):
    return base64.b64encode(json.dumps({"dispatch_id": dispatch_id, "leg": leg}).encode()).decode()


def number_client(config, request=None):
    """Account lookups and purchases work before live sending is switched on."""
    if config.mode == "demo":
        return DemoProvider()
    if config.mode != "live" or not config.api_key:
        raise ProviderRejected("Telnyx API key is required")
    return TelnyxProvider(config, request or request_json)


def build_provider(config, request=None):
    if config.mode == "demo":
        return DemoProvider()
    if config.mode != "live":
        raise ProviderRejected("Unknown provider mode")
    if not config.enable_live_send:
        raise ProviderRejected("Live sending is disabled")
    if not config.api_key or not re.fullmatch(r"\+[1-9]\d{7,14}", config.from_number):
        raise ProviderRejected("Telnyx API key and E.164 caller number are required")
    if not 30 <= config.max_call_duration_seconds <= 300:
        raise ProviderRejected("Pilot voice calls must be limited to 30–300 seconds")
    return TelnyxProvider(config, request or request_json)
