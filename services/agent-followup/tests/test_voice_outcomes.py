import pytest
from pydantic import ValidationError

from followup.voice_outcomes import AssistantOutcome, issue_outcome_token, verify_outcome_token

SECRET = "s" * 32


def test_token_is_deterministic_and_binds_tenant_and_job():
    token = issue_outcome_token(SECRET, "tenant-a", "job-a")
    assert token == issue_outcome_token(SECRET, "tenant-a", "job-a")
    assert verify_outcome_token(token, SECRET, "tenant-a", "job-a")
    assert not verify_outcome_token(token, SECRET, "tenant-b", "job-a")
    assert not verify_outcome_token(token, SECRET, "tenant-a", "job-b")
    assert not verify_outcome_token(token, "z" * 32, "tenant-a", "job-a")


def test_domain_separation_prevents_identifier_delimiter_collisions():
    assert issue_outcome_token(SECRET, "a:b", "c") != issue_outcome_token(SECRET, "a", "b:c")


@pytest.mark.parametrize("token", [None, "", "bad", "f" * 64, "é" * 64, 123])
def test_bad_tokens_fail_closed(token):
    assert not verify_outcome_token(token, SECRET, "tenant", "dispatch")


@pytest.mark.parametrize(
    "secret,tenant,dispatch", [("short", "tenant", "d"), (SECRET, "", "d"), (SECRET, "tenant", "")]
)
def test_invalid_issuance_configuration_rejected(secret, tenant, dispatch):
    with pytest.raises(ValueError):
        issue_outcome_token(secret, tenant, dispatch)
    assert not verify_outcome_token("f" * 64, secret, tenant, dispatch)


def payload(**overrides):
    return {
        "dispatch_id": "job",
        "outcome_token": "a" * 64,
        "outcome": "opt_out",
        "summary": "Asked not to receive further calls.",
        **overrides,
    }


def test_outcome_schema_is_immutable_and_secret_redacted():
    outcome = AssistantOutcome(**payload())
    assert outcome.outcome == "opt_out"
    assert "a" * 64 not in repr(outcome)
    with pytest.raises(ValidationError):
        outcome.summary = "changed"


@pytest.mark.parametrize(
    "overrides",
    [
        {"outcome": "appointment_confirmed"},
        {"outcome_token": "bad"},
        {"summary": ""},
        {"summary": "x" * 2001},
        {"tenant_id": "attacker-tenant"},
        {"dispatch_id": ""},
    ],
)
def test_payload_rejects_unknown_outcomes_and_untrusted_tenant(overrides):
    with pytest.raises(ValidationError):
        AssistantOutcome(**payload(**overrides))


def test_assistant_template_keeps_scoped_auth_outside_model_arguments():
    import json
    from pathlib import Path

    path = Path(__file__).parents[3] / "docs" / "telnyx-assistant.template.json"
    template = json.loads(path.read_text())
    webhook = template["tools"][0]["webhook"]
    assert webhook["method"] == "POST"
    assert webhook["url"].endswith("/webhooks/assistant-outcome")
    assert webhook["preset_body_fields"] == {
        "dispatch_id": "{{dispatch_id}}",
        "outcome_token": "{{outcome_token}}",
    }
    assert set(webhook["body_parameters"]["properties"]) == {"outcome", "summary"}
    assert template["tools"][1]["type"] == "hangup"
    assert "opt_out" in template["instructions"]
