"""Parameterized persistence for processed emails."""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from app.database.models import (
    EmailCategory,
    EmailPriority,
    EmailRecord,
    ProcessingStatus,
    Sentiment,
)

logger = logging.getLogger(__name__)

MAX_IDENTIFIER_LENGTH = 255
MAX_SENDER_LENGTH = 320
MAX_SUBJECT_CHARS = 500
MAX_BODY_CHARS = 20_000
MAX_SUMMARY_CHARS = 2_000
MAX_REPLY_CHARS = 8_000
_FAILURE_DETAIL = re.compile(r"[a-z][a-z0-9_]{1,63}")
_REVIEW_STATUSES = {
    ProcessingStatus.AWAITING_REVIEW,
    ProcessingStatus.URGENT_REVIEW,
    ProcessingStatus.IMMEDIATE_REVIEW,
}


class InvalidEmailDataError(ValueError):
    """Raised when an email field cannot be stored safely."""


class InvalidFailureDetailError(ValueError):
    """Raised when a failure code is not a short machine-readable token."""


class EmailNotFoundError(LookupError):
    """Raised when a stored email identifier does not exist."""


@dataclass(frozen=True)
class IncomingEmail:
    email_identifier: str
    sender_address: str
    subject: str | None
    body_text: str
    received_at: datetime


@dataclass(frozen=True)
class ProcessingUpdate:
    category: EmailCategory
    priority: EmailPriority
    sentiment: Sentiment
    summary: str
    recommended_action: str
    priority_reason: str
    suggested_reply: str
    status: ProcessingStatus


class EmailRepository:
    """Store emails and refuse duplicate identifiers."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_if_absent(self, incoming: IncomingEmail) -> tuple[EmailRecord, bool]:
        """Insert a new processing row. An existing identifier is returned unchanged."""
        identifier = _clean_identifier(incoming.email_identifier)
        record = EmailRecord(
            email_identifier=identifier,
            sender_address=_clean_sender(incoming.sender_address),
            subject=_clean_subject(incoming.subject),
            body_text=minimize_text(incoming.body_text, MAX_BODY_CHARS),
            received_at=_as_utc_naive(incoming.received_at),
            processing_status=ProcessingStatus.PROCESSING,
            reply_locked=False,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        try:
            with self._session.begin_nested():
                self._session.add(record)
                self._session.flush()
        except IntegrityError:
            if object_session(record) is self._session:
                self._session.expunge(record)
            existing = self.get_by_identifier(identifier)
            if existing is None:
                raise
            logger.info("Duplicate email identifier was ignored")
            return existing, False
        return record, True

    def begin_processing(self, incoming: IncomingEmail) -> tuple[EmailRecord, str]:
        """Insert a new row, reopen a failed row, or return the existing row.

        The action is ``created``, ``reopened``, or ``existing``.
        """
        record, created = self.create_if_absent(incoming)
        if created:
            return record, "created"
        if record.processing_status != ProcessingStatus.FAILED or record.reply_locked:
            return record, "existing"
        locked = self._lock(record.email_identifier)
        if locked.processing_status != ProcessingStatus.FAILED or locked.reply_locked:
            return locked, "existing"
        locked.processing_status = ProcessingStatus.PROCESSING
        locked.failure_detail = None
        locked.processed_at = None
        locked.updated_at = utcnow()
        self._session.flush()
        return locked, "reopened"

    def list_emails(
        self,
        *,
        category: EmailCategory | None,
        priority: EmailPriority | None,
        status: ProcessingStatus | None,
        page: int,
        page_size: int,
    ) -> tuple[list[EmailRecord], int]:
        filters = []
        if category is not None:
            filters.append(EmailRecord.category == category)
        if priority is not None:
            filters.append(EmailRecord.priority == priority)
        if status is not None:
            filters.append(EmailRecord.processing_status == status)
        total = self._session.scalar(
            select(func.count()).select_from(EmailRecord).where(*filters)
        )
        rows = self._session.scalars(
            select(EmailRecord)
            .where(*filters)
            .order_by(EmailRecord.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return list(rows), int(total or 0)

    def processing_stats(self) -> dict[str, object]:
        total = int(
            self._session.scalar(select(func.count()).select_from(EmailRecord)) or 0
        )
        return {
            "total": total,
            "by_category": _grouped_counts(self._session, EmailRecord.category),
            "by_priority": _grouped_counts(self._session, EmailRecord.priority),
            "by_status": _grouped_counts(self._session, EmailRecord.processing_status),
        }

    def save_success(
        self,
        email_identifier: str,
        update: ProcessingUpdate,
    ) -> EmailRecord:
        """Complete a row that is still processing. Finished rows are not rewritten."""
        if update.status not in _REVIEW_STATUSES:
            raise InvalidEmailDataError("processing status must be a review status")
        record = self._lock(email_identifier)
        if record.processing_status != ProcessingStatus.PROCESSING:
            logger.info("Skipped update for an email that is no longer processing")
            return record
        record.category = update.category
        record.priority = update.priority
        record.sentiment = update.sentiment
        record.summary = minimize_text(update.summary, MAX_SUMMARY_CHARS)
        record.recommended_action = minimize_text(
            update.recommended_action,
            MAX_SUMMARY_CHARS,
        )
        record.priority_reason = minimize_text(update.priority_reason, MAX_SUMMARY_CHARS)
        if not record.reply_locked:
            record.suggested_reply = minimize_text(update.suggested_reply, MAX_REPLY_CHARS)
        record.processing_status = update.status
        record.failure_detail = None
        record.processed_at = utcnow()
        record.updated_at = utcnow()
        self._session.flush()
        return record

    def mark_failed(self, email_identifier: str, failure_detail: str) -> EmailRecord:
        """Record a stable failure code while the row is still processing."""
        if _FAILURE_DETAIL.fullmatch(failure_detail) is None:
            raise InvalidFailureDetailError(
                "failure detail must be a short lowercase code"
            )
        record = self._lock(email_identifier)
        if record.processing_status != ProcessingStatus.PROCESSING or record.reply_locked:
            logger.info("Skipped failure update for an email that is no longer processing")
            return record
        record.processing_status = ProcessingStatus.FAILED
        record.failure_detail = failure_detail
        record.processed_at = utcnow()
        record.updated_at = utcnow()
        self._session.flush()
        return record

    def lock_reply(
        self,
        email_identifier: str,
        reply_text: str | None = None,
    ) -> EmailRecord:
        """Keep the current suggested reply from being replaced."""
        record = self._lock(email_identifier)
        if reply_text is not None:
            record.suggested_reply = minimize_text(reply_text, MAX_REPLY_CHARS)
        record.reply_locked = True
        record.updated_at = utcnow()
        self._session.flush()
        return record

    def get_by_identifier(self, email_identifier: str) -> EmailRecord | None:
        identifier = _clean_identifier(email_identifier)
        return self._session.scalar(
            select(EmailRecord).where(EmailRecord.email_identifier == identifier)
        )

    def get_by_id(self, email_id: int) -> EmailRecord | None:
        return self._session.get(EmailRecord, email_id)

    def delete_by_id(self, email_id: int) -> bool:
        record = self.get_by_id(email_id)
        if record is None:
            return False
        self._session.delete(record)
        self._session.flush()
        return True

    def delete_received_before(self, cutoff: datetime) -> int:
        """Delete stored mail received before the cutoff. The cutoff is a bound parameter."""
        result = self._session.execute(
            delete(EmailRecord).where(EmailRecord.received_at < _as_utc_naive(cutoff))
        )
        self._session.flush()
        return int(result.rowcount or 0)

    def _lock(self, email_identifier: str) -> EmailRecord:
        identifier = _clean_identifier(email_identifier)
        record = self._session.scalar(
            select(EmailRecord)
            .where(EmailRecord.email_identifier == identifier)
            .with_for_update()
        )
        if record is None:
            raise EmailNotFoundError("email was not found")
        return record


def _grouped_counts(session: Session, column: object) -> dict[str, int]:
    rows = session.execute(select(column, func.count()).group_by(column))
    counts: dict[str, int] = {}
    for key, count in rows:
        if key is None:
            label = "unclassified"
        elif hasattr(key, "value"):
            label = str(key.value)
        else:
            label = str(key)
        counts[label] = int(count)
    return counts


def minimize_text(value: str, limit: int) -> str:
    """Drop null bytes and keep stored text within a fixed character limit."""
    cleaned = value.replace("\x00", "")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(cleaned) <= limit:
        return cleaned
    suffix = "\n[truncated]"
    return cleaned[: limit - len(suffix)].rstrip() + suffix


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _clean_identifier(value: str) -> str:
    identifier = value.strip()
    if not identifier:
        raise InvalidEmailDataError("email identifier is required")
    if len(identifier) > MAX_IDENTIFIER_LENGTH or _has_control_character(identifier):
        raise InvalidEmailDataError("email identifier is not storable")
    return identifier


def _clean_sender(value: str) -> str:
    sender = value.strip()
    if (
        not sender
        or len(sender) > MAX_SENDER_LENGTH
        or "@" not in sender
        or _has_control_character(sender)
        or any(character.isspace() for character in sender)
    ):
        raise InvalidEmailDataError("sender address is not storable")
    return sender


def _clean_subject(value: str | None) -> str | None:
    if value is None:
        return None
    minimized = minimize_text(value, MAX_SUBJECT_CHARS)
    return minimized or None


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 32 for character in value)
