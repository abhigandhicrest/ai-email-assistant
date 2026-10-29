"""Validated model output and email API payloads."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database.models import (
    EmailCategory,
    EmailPriority,
    ProcessingStatus,
    Sentiment,
)

_SUMMARY_MAX = 2_000
_REPLY_MAX = 8_000


class ClassificationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: EmailCategory
    priority: EmailPriority
    sentiment: Sentiment
    summary: str = Field(min_length=1, max_length=_SUMMARY_MAX)
    recommended_action: str = Field(min_length=1, max_length=_SUMMARY_MAX)
    priority_reason: str = Field(min_length=1, max_length=_SUMMARY_MAX)

    @field_validator("summary", "recommended_action", "priority_reason")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text must not be blank")
        return cleaned


class ReplyResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    suggested_reply: str = Field(min_length=1, max_length=_REPLY_MAX)

    @field_validator("suggested_reply")
    @classmethod
    def reply_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reply must not be blank")
        return cleaned


class EmailProcessRequest(BaseModel):
    email_identifier: str = Field(min_length=1, max_length=255)
    sender_address: str = Field(min_length=3, max_length=320)
    subject: str | None = Field(default=None, max_length=500)
    body_text: str = Field(max_length=100_000)
    received_at: datetime

    @field_validator("email_identifier", "sender_address")
    @classmethod
    def required_text_must_be_storable(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(ord(character) < 32 for character in cleaned):
            raise ValueError("value is not storable")
        return cleaned

    @field_validator("sender_address")
    @classmethod
    def sender_must_look_like_an_address(cls, value: str) -> str:
        if "@" not in value or any(character.isspace() for character in value):
            raise ValueError("sender address is not valid")
        return value

    @field_validator("subject")
    @classmethod
    def subject_must_be_storable(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(ord(character) < 32 and character not in "\t" for character in value):
            raise ValueError("subject is not storable")
        return value


class NotificationPayload(BaseModel):
    required: bool
    level: str
    email_id: int
    priority: EmailPriority
    summary: str | None
    delivery: str


class EmailProcessResponse(BaseModel):
    id: int
    email_identifier: str
    sender_address: str
    subject: str | None
    category: EmailCategory | None
    priority: EmailPriority | None
    sentiment: Sentiment | None
    summary: str | None
    recommended_action: str | None
    priority_reason: str | None
    suggested_reply: str | None
    processing_status: ProcessingStatus
    failure_detail: str | None
    already_processed: bool
    received_at: datetime
    processed_at: datetime | None
    notification: NotificationPayload | None


class EmailListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email_identifier: str
    sender_address: str
    subject: str | None
    category: EmailCategory | None
    priority: EmailPriority | None
    sentiment: Sentiment | None
    summary: str | None
    processing_status: ProcessingStatus
    received_at: datetime
    processed_at: datetime | None


class EmailListResponse(BaseModel):
    items: list[EmailListItem]
    page: int
    page_size: int
    total: int


class EmailDetail(EmailListItem):
    body_text: str
    recommended_action: str | None
    priority_reason: str | None
    suggested_reply: str | None
    failure_detail: str | None
    reply_locked: bool


class StatsResponse(BaseModel):
    total: int
    by_category: dict[str, int]
    by_priority: dict[str, int]
    by_status: dict[str, int]
