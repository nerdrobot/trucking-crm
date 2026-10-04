import asyncio
import base64
import json
from dataclasses import replace

import pytest

from followup.providers import (
    ProviderAmbiguousError,
    ProviderConfig,
    ProviderRejected,
    build_provider,
)

LIVE = ProviderConfig(
    mode="live",
    enable_live_send=True,
    api_key="test-key",
    from_number="+13125550100",
    messaging_profile_id="profile",
    connection_id="connection",
    assistant_id="assistant",
)


def run(awaitable):
    return asyncio.run(awaitable)


def test_demo_is_deterministic_and_never_calls_transport():
    async def forbidden(*args):
        raise AssertionError("network forbidden")

    provider = build_provider(ProviderConfig(), request=forbidden)
    first = run(provider.send_sms("+13125550101", "Hello", "dispatch"))
    assert first == run(provider.send_sms("+13125550101", "Hello", "dispatch"))
    assert first.status == "delivered"
    call = run(provider.start_call("+13125550101", "voice"))
    assert call.status == "completed"
    assert call.metadata["simulated"] is True
    assert "simulated" in call.metadata["summary"].lower()


def test_sms_payload_and_response_do_not_invent_idempotency():
    async def request(method, url, headers, payload):
        assert method == "POST" and url == "https://api.telnyx.com/v2/messages"
        assert headers["Authorization"] == "Bearer test-key"
        assert payload == {
            "from": "+13125550100",
            "to": "+13125550101",
            "text": "Hello",
            "type": "SMS",
            "messaging_profile_id": "profile",
        }
        return 202, {"data": {"id": "message-id"}}

    result = run(build_provider(LIVE, request).send_sms("+13125550101", "Hello", "dispatch"))
    assert result.provider_id == "message-id" and result.status == "queued"


def test_voice_attaches_assistant_and_provider_duration_limit():
    async def request(method, url, headers, payload):
        assert url == "https://api.telnyx.com/v2/calls"
        assert payload["assistant"] == {"id": "assistant", "dynamic_variables": {"name": "Sam"}}
        assert payload["time_limit_secs"] == 120
        assert payload["timeout_secs"] == 30
        assert payload["command_id"] == "dispatch"
        assert json.loads(base64.b64decode(payload["client_state"])) == {"dispatch_id": "dispatch"}
        assert "record" not in payload
        return 200, {"data": {"call_control_id": "call-id"}}

    result = run(
        build_provider(LIVE, request).start_call("+13125550101", "dispatch", {"name": "Sam"})
    )
    assert result.provider_id == "call-id" and result.status == "queued"


@pytest.mark.parametrize(
    "config",
    [
        replace(LIVE, enable_live_send=False),
        replace(LIVE, api_key=""),
        replace(LIVE, from_number="invalid"),
        replace(LIVE, max_call_duration_seconds=0),
        replace(LIVE, mode="typo"),
    ],
)
def test_bad_config_fails_closed(config):
    with pytest.raises(ProviderRejected):
        build_provider(config)


@pytest.mark.parametrize(
    "status,error,retry",
    [
        (400, ProviderRejected, False),
        (429, ProviderRejected, True),
        (408, ProviderAmbiguousError, False),
        (500, ProviderAmbiguousError, False),
        (302, ProviderAmbiguousError, False),
    ],
)
def test_provider_errors_do_not_leak_body(status, error, retry):
    async def request(*args):
        return status, {"errors": [{"detail": "private provider detail"}]}

    with pytest.raises(error) as exc:
        run(build_provider(LIVE, request).send_sms("+13125550101", "Hello", "dispatch"))
    assert exc.value.safe_to_retry is retry
    assert "private" not in str(exc.value)


def test_timeout_is_ambiguous_not_retryable():
    async def request(*args):
        raise TimeoutError("credentials should never escape")

    with pytest.raises(ProviderAmbiguousError) as exc:
        run(build_provider(LIVE, request).send_sms("+13125550101", "Hello", "dispatch"))
    assert not exc.value.safe_to_retry


def test_missing_provider_id_is_ambiguous():
    async def request(*args):
        return 200, {"data": {}}

    with pytest.raises(ProviderAmbiguousError):
        run(build_provider(LIVE, request).start_call("+13125550101", "dispatch"))


def test_missing_channel_configuration_rejects_before_request():
    async def request(*args):
        raise AssertionError("network forbidden")

    with pytest.raises(ProviderRejected):
        run(build_provider(replace(LIVE, assistant_id=""), request).start_call("+13125550101", "d"))
    with pytest.raises(ProviderRejected):
        run(
            build_provider(replace(LIVE, messaging_profile_id=""), request).send_sms(
                "+13125550101", "x", "d"
            )
        )


@pytest.mark.parametrize(
    "to,text,dispatch",
    [("bad", "hello", "id"), ("+13125550101", "", "id"), ("+13125550101", "hello", "")],
)
def test_bad_send_inputs_rejected(to, text, dispatch):
    with pytest.raises(ProviderRejected):
        run(build_provider(LIVE).send_sms(to, text, dispatch))


def test_invalid_voice_context_is_rejected_before_submission():
    with pytest.raises(ProviderRejected):
        run(build_provider(LIVE).start_call("+13125550101", "d", {"nested": {"x": 1}}))


def test_http_transport_uses_json_without_redirects(monkeypatch):
    import httpx

    from followup.providers import request_json

    original = httpx.AsyncClient

    def handle(request):
        assert json.loads(request.content) == {"text": "hello"}
        return httpx.Response(202, json={"data": {"id": "provider-id"}})

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    assert run(
        request_json("POST", "https://api.telnyx.com/v2/messages", {}, {"text": "hello"})
    ) == (202, {"data": {"id": "provider-id"}})


@pytest.mark.parametrize("status", [202, 429])
def test_worker_transport_uses_native_fetch(monkeypatch, status):
    import sys
    from types import SimpleNamespace

    from followup.providers import request_json

    async def text():
        return '{"data":{"id":"provider-id"}}'

    async def fetch(url, **kwargs):
        assert url == "https://api.telnyx.com/v2/messages"
        assert kwargs["redirect"] == "manual"
        assert json.loads(kwargs["body"]) == {"text": "hello"}
        return SimpleNamespace(status=status, text=text)

    monkeypatch.setattr(sys, "platform", "emscripten")
    monkeypatch.setitem(sys.modules, "workers", SimpleNamespace(fetch=fetch))
    result = run(request_json("POST", "https://api.telnyx.com/v2/messages", {}, {"text": "hello"}))
    assert result == (status, {"data": {"id": "provider-id"}} if status == 202 else {})
