"""Stored email records and the values the database accepts."""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProcessingStatus(enum.StrEnum):
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    URGENT_REVIEW = "urgent_review"
    IMMEDIATE_REVIEW = "immediate_review"
    FAILED = "failed"


class EmailCategory(enum.StrEnum):
    TECHNICAL_SUPPORT = "Technical Support"
    BILLING = "Billing"
    SALES = "Sales"
    ORDER_INQUIRY = "Order Inquiry"
    COMPLAINT = "Complaint"
    GENERAL_INQUIRY = "General Inquiry"
    SPAM_OR_AUTOMATED = "Spam or Automated Notification"
    OTHER = "Other"


class EmailPriority(enum.StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class Sentiment(enum.StrEnum):
    POSITIVE = "Positive"
    NEUTRAL = "Neutral"
    NEGATIVE = "Negative"


def _enum_column(enum_class: type[enum.Enum], length: int) -> SqlEnum:
    return SqlEnum(
        enum_class,
        native_enum=False,
        length=length,
        values_callable=lambda cls: [item.value for item in cls],
    )


def _allowed(column: str, enum_class: type[enum.Enum], *, nullable: bool) -> str:
    literals = ", ".join(f"'{item.value}'" for item in enum_class)
    expression = f"{column} IN ({literals})"
    if nullable:
        return f"{column} IS NULL OR {expression}"
    return expression


class EmailRecord(Base):
    """One stored email. The original identifier cannot be inserted twice."""

    __tablename__ = "emails"
    __table_args__ = (
        CheckConstraint(
            _allowed("processing_status", ProcessingStatus, nullable=False),
            name="ck_emails_processing_status",
        ),
        CheckConstraint(
            _allowed("category", EmailCategory, nullable=True),
            name="ck_emails_category",
        ),
        CheckConstraint(
            _allowed("priority", EmailPriority, nullable=True),
            name="ck_emails_priority",
        ),
        CheckConstraint(
            _allowed("sentiment", Sentiment, nullable=True),
            name="ck_emails_sentiment",
        ),
        Index("ix_emails_processing_status", "processing_status"),
        Index("ix_emails_category", "category"),
        Index("ix_emails_priority", "priority"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email_identifier: Mapped[str] = mapped_column(String(255), unique=True)
    sender_address: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(500))
    body_text: Mapped[str] = mapped_column(Text)
    category: Mapped[EmailCategory | None] = mapped_column(
        _enum_column(EmailCategory, 40)
    )
    priority: Mapped[EmailPriority | None] = mapped_column(
        _enum_column(EmailPriority, 16)
    )
    sentiment: Mapped[Sentiment | None] = mapped_column(_enum_column(Sentiment, 16))
    summary: Mapped[str | None] = mapped_column(Text)
    recommended_action: Mapped[str | None] = mapped_column(Text)
    priority_reason: Mapped[str | None] = mapped_column(Text)
    suggested_reply: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        _enum_column(ProcessingStatus, 32)
    )
    failure_detail: Mapped[str | None] = mapped_column(String(64))
    reply_locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    received_at: Mapped[datetime] = mapped_column(DateTime)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        server_onupdate=func.now(),
    )
