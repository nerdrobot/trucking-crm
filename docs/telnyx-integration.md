# Telnyx pilot integration

The default provider is a deterministic simulation: no messages, calls, or charges.
The live adapter uses Telnyx's HTTPS API directly, with no Telnyx SDK or native Python
extension required in the Worker. Credentials remain backend secrets.

## Configure before enabling live dispatch

1. Provision a Telnyx number capable of outbound SMS and voice. Assign its messaging
   profile and complete the registration/verification required for the number's use.
2. Configure the messaging profile's webhook URL to the deployed backend's
   `/webhooks/telnyx` endpoint. Use the account's public webhook signing key in the backend.
3. Create a **Call Control / Voice API application** and attach an outbound voice
   profile with the intended destinations enabled. Configure its event webhook to
   the same backend endpoint. `connection_id` is that application's ID, not a TeXML ID.
4. Create a hosted AI assistant with an enabled voice, transcription provider,
   model, and Hangup tool. Prefer a Telnyx-hosted model initially to avoid needing
   another provider's credentials. Configure its instructions and greeting below.
5. Supply the backend's secret API key, caller number, messaging profile ID,
   voice application ID, assistant ID, webhook public key, and `VOICE_OUTCOME_SECRET`. Set live mode and
   the separate live-send enable switch only after testing an authorized recipient.
   The adapter limits answered call duration to 120 seconds by default (allowed
   pilot range 30–300), and ringing to 30 seconds.

The caller number, profiles, assistant, and production webhook must actually exist
in the account. This implementation does not provision them or spend the credit.
The API's status/settings surface should be checked for missing configuration.

## Assistant configuration

Use [telnyx-assistant.template.json](telnyx-assistant.template.json) as the
`instructions`, `greeting`, and `tools` portion of an existing assistant's update
payload. Replace `REPLACE_WITH_BACKEND_HOST` with the deployed HTTPS backend host.
These are actual Telnyx assistant fields; preserve your existing model, voice,
transcription settings, and other desired assistant configuration. The template's
`tools` array replaces the configured tools, so inspect it before applying.
No external update is performed by this repository.

The backend supplies five dynamic variables: `lead_name`, `agent_name`,
`followup_message`, `dispatch_id`, and `outcome_token`. The last two are passed by
the webhook tool's **preset_body_fields**, not chosen by the language model.
The outcome tool posts to `/webhooks/assistant-outcome`:

```json
{
  "dispatch_id": "<current-job-id>",
  "outcome_token": "<64-character-per-job-HMAC>",
  "outcome": "opt_out",
  "summary": "The person asked not to receive further calls or messages."
}
```

The assistant must invoke `record_followup_outcome` before its Hangup tool. Allowed
outcomes are `interested`, `not_now`, `opt_out`, `human_requested`, and
`appointment_requested`. Instructions prioritize verbal opt-outs, human requests,
and factual summaries. An appointment outcome records a request; it does not book
anything. Human requests surface for the agent's manual follow-up; no live transfer
is promised. Configure and verify a separate transfer tool if that is later needed.

Generate a random `VOICE_OUTCOME_SECRET` of at least 32 characters and store it as
a backend secret; never use the frontend API key. Only a job-scoped HMAC token is
sent to Telnyx. Tokens bind the tenant and immutable dispatch ID. The endpoint must
resolve the tenant from the stored voice job, verify the token in constant time,
and apply idempotent outcome processing. Tokens do not expire so delayed opt-outs
remain actionable; rotating the secret revokes outstanding tokens. Do not log
outcome request bodies or include tokens in frontend responses.

This tool endpoint uses the scoped token; the ordinary `/webhooks/telnyx` endpoint
continues using Telnyx's Ed25519 signatures. Do not substitute one authentication
mechanism for the other. Keep the tool URL outside interactive Cloudflare Access
login, and enforce its scoped token at the application boundary.

If the assistant misses the tool, its request fails, or the call ends unexpectedly,
a live answered call must remain paused for agent review. Do not infer an outcome
from a hangup or automatically continue contacting an unreviewed person. Before
a real cohort, make one authorized test call for each of opt-out, callback request,
and human request, and verify the CRM state as well as the spoken behavior.

Telnyx documents [preset webhook parameters](https://developers.telnyx.com/docs/inference/ai-assistants/preset-webhook-parameters)
and [dynamic variables in tools](https://developers.telnyx.com/docs/inference/ai-assistants/dynamic-variables).
The preset fields are templated by Telnyx, hidden from the model's tool parameters,
and override conflicting generated arguments.

## Actual outbound requests

SMS uses `POST https://api.telnyx.com/v2/messages` with `from`, `to`, `text`,
`type: SMS`, and `messaging_profile_id`. The successful response's `data.id`
is persisted for delivery correlation. The send API has **no documented
`client_state` or `command_id`**, so the adapter does not invent SMS idempotency.

Voice uses `POST https://api.telnyx.com/v2/calls` with:

```json
{
  "connection_id": "<voice-application-id>",
  "from": "+13125550100",
  "to": "+13125550101",
  "assistant": {
    "id": "<assistant-id>",
    "dynamic_variables": {
      "lead_name": "Example Lead",
      "agent_name": "Example Agent",
      "followup_message": "Check whether they want to arrange a viewing."
    }
  },
  "command_id": "<stable-dispatch-id>",
  "client_state": "<base64-encoded dispatch_id JSON>",
  "time_limit_secs": 120,
  "timeout_secs": 30,
  "retry_on_timeout": false
}
```

Passing the assistant in Dial attaches the hosted assistant directly. No later
`call.answered` command is required to start the conversation. The response's
`data.call_control_id` is persisted. The adapter does not enable recordings.

## Events and uncertain submissions

- Validate Telnyx's signature against the exact request bytes before processing.
- SMS delivery events include `message.sent` and `message.finalized`; the message
  identifier is `data.payload.id` and recipient statuses are under `payload.to`.
- Inbound `message.received` includes `payload.from.phone_number`,
  `payload.to[].phone_number`, and `payload.text`. Match both sender and our receiving
  number before applying a reply to a lead. Replies pause automation; STOP-family
  replies suppress it. Retain Telnyx messaging-profile opt-out enforcement too.
- Voice events use `payload.call_control_id`; `payload.client_state` contains
  base64 JSON with `dispatch_id`. A hangup is an end-of-call event, not evidence
  that the caller was interested. Call summaries require actual transcript/insight
  events or human review; never fabricate a summary for live calls.
- Network errors, timeouts, malformed success responses, and HTTP 5xx leave the
  outcome uncertain. **Do not automatically resend.** Reconcile the event history
  and Telnyx logs first. A 429 rejection is explicitly retryable; other 4xx errors
  generally require correcting configuration or inputs. Transport redirects are
  not followed, preventing accidental forwarding of the authorization header.

## Verified contracts

The official OpenAPI-generated SDK documents the exact supported fields:

- [Dial request and duration/command correlation](https://github.com/team-telnyx/telnyx-python/blob/master/src/telnyx/types/call_dial_params.py).
- [Embedded assistant and dynamic variables](https://github.com/team-telnyx/telnyx-python/blob/master/src/telnyx/types/call_assistant_request_param.py).
- [SMS send request](https://github.com/team-telnyx/telnyx-python/blob/master/src/telnyx/types/message_send_params.py).
- [Telnyx receiving messages](https://developers.telnyx.com/docs/messaging/messages/receive-message).

Provider tests cover payloads, simulation, configuration failures, native Worker
fetch and local HTTP transport, duration limits, error redaction, and ambiguous
submission handling. No paid requests are made by tests.
