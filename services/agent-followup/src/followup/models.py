"""Validated public contracts; internal tenant identity never comes from callers."""

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from followup.providers import valid_email


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Kind = Literal["owner_operator", "fleet"]


class LeadInput(Input):
    name: str = Field(min_length=1, max_length=100)
    phone: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    email: str = Field(default="", max_length=254)
    kind: Kind = "owner_operator"
    company: str = Field(default="", max_length=150)
    mc_number: str = Field(default="", pattern=r"^\d{0,8}$")
    dot_number: str = Field(default="", pattern=r"^\d{0,8}$")
    fleet_size: int = Field(default=1, ge=0, le=10000)
    niche: str = Field(default="", max_length=60)
    city: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=40)
    agent_id: str | None = None
    timezone: str = "UTC"
    consent_sms: bool = False
    consent_voice: bool = False
    consent_email: bool = False
    consent_note: str = Field(default="", max_length=1000)

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown timezone") from None
        return value

    @model_validator(mode="after")
    def consent_evidence(self):
        if (self.consent_sms or self.consent_voice or self.consent_email) and not self.consent_note:
            raise ValueError("Consent evidence required")
        if self.email and not valid_email(self.email):
            raise ValueError("Invalid email address")
        if self.consent_email and not self.email:
            raise ValueError("Email consent requires an email address")
        return self


Stage = Literal[
    "new", "contacted", "interested", "qualified", "agreement_sent", "onboarded", "lost"
]


class LeadPatch(Input):
    stage: Stage | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=254)
    kind: Kind | None = None
    company: str | None = Field(default=None, max_length=150)
    mc_number: str | None = Field(default=None, pattern=r"^\d{0,8}$")
    dot_number: str | None = Field(default=None, pattern=r"^\d{0,8}$")
    fleet_size: int | None = Field(default=None, ge=0, le=10000)
    niche: str | None = Field(default=None, max_length=60)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=40)
    agent_id: str | None = None
    timezone: str | None = None
    consent_sms: bool | None = None
    consent_voice: bool | None = None
    consent_email: bool | None = None
    consent_note: str | None = Field(default=None, max_length=1000)


Channel = Literal["sms", "voice", "email"]
Subject = Field(default="", max_length=200, pattern=r"^[^\r\n]*$")


class Step(Input):
    channel: Channel
    delay_minutes: int = Field(ge=0, le=525600)
    message: str = Field(default="", max_length=5000)
    subject: str = Subject

    @model_validator(mode="after")
    def content(self):
        if self.channel != "email":
            self.subject = ""
            if len(self.message) > 1200:
                raise ValueError("Text and call steps are limited to 1200 characters")
        elif not (self.subject and self.message):
            raise ValueError("Email steps require a subject and message")
        if self.channel == "sms" and not self.message:
            raise ValueError("SMS steps require a message")
        return self


class SequenceInput(Input):
    name: str = Field(min_length=1, max_length=100)
    steps: list[Step] = Field(min_length=1, max_length=8)


class EnrollmentInput(Input):
    sequence_id: str


class MessageInput(Input):
    text: str = Field(min_length=1, max_length=1200)


class EmailInput(Input):
    subject: str = Field(min_length=1, max_length=200, pattern=r"^[^\r\n]*$")
    text: str = Field(min_length=1, max_length=5000)


class TemplateInput(Input):
    name: str = Field(min_length=1, max_length=100)
    channel: Channel
    subject: str = Subject
    body: str = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def content(self):
        if self.channel == "email" and not self.subject:
            raise ValueError("Email templates require a subject")
        if self.channel != "email":
            self.subject = ""
            if len(self.body) > 1200:
                raise ValueError("Text and call templates are limited to 1200 characters")
        return self


class TaskInput(Input):
    title: str = Field(min_length=1, max_length=300)
    due_at: datetime | None = None


class CallLog(Input):
    outcome: Literal[
        "connected",
        "no_answer",
        "voicemail",
        "interested",
        "not_interested",
        "wrong_number",
        "call_back",
        "appointment_set",
    ]
    note: str = Field(default="", max_length=1000)
    follow_up_at: datetime | None = None


class TaskPatch(Input):
    status: Literal["open", "done"]


class NumberChoice(Input):
    phone_number: str = Field(pattern=r"^\+[1-9]\d{7,14}$")


ProviderId = Field(default="", pattern=r"^[A-Za-z0-9_\-]{0,100}$")


class ChannelSettings(Input):
    sms_enabled: bool
    voice_enabled: bool
    messaging_profile_id: str = ProviderId
    connection_id: str = ProviderId
    assistant_id: str = ProviderId
    email_enabled: bool = False
    email_from: str = Field(default="", max_length=254)
    email_from_name: str = Field(default="", max_length=100, pattern=r"^[^\r\n<>\"]*$")

    @field_validator("email_from")
    @classmethod
    def sender(cls, value):
        if value and not valid_email(value):
            raise ValueError("Invalid sender email address")
        return value


class ImportInput(Input):
    csv: str = Field(min_length=1, max_length=200000)


class Preferences(Input):
    automation_enabled: bool
    daily_sms_limit: int = Field(ge=0, le=1000)
    daily_call_limit: int = Field(ge=0, le=100)
    daily_email_limit: int = Field(default=200, ge=0, le=5000)
    contact_start_hour: int = Field(ge=0, le=23)
    contact_end_hour: int = Field(ge=1, le=24)

    @model_validator(mode="after")
    def interval(self):
        if self.contact_start_hour >= self.contact_end_hour:
            raise ValueError("Invalid contact hours")
        return self
