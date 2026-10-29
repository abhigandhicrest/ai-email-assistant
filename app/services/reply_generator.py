"""Draft a suggested reply and reject unsupported promises."""

import logging
import re
from typing import Any

from pydantic import ValidationError

from app.schemas.email_schema import ClassificationResult, ReplyResult
from app.services.email_classifier import format_email
from app.services.ollama_service import (
    InvalidModelOutputError,
    OllamaService,
    OllamaServiceError,
    load_prompt,
)

logger = logging.getLogger(__name__)

_INVENTED_MECHANISMS = re.compile(
    r"temporary password|default password|backup code|one-time password",
    re.IGNORECASE,
)
_PROMISES = re.compile(
    r"\bhave refunded\b|"
    r"\bhas been refunded\b|"
    r"\brefund has been (?:processed|issued|completed)\b|"
    r"\bi (?:have|'ve) issued a refund\b|"
    r"\bpassword has been reset\b|"
    r"\bi (?:have|'ve) reset your password\b|"
    r"\baccount has been unlocked\b|"
    r"\bi (?:have|'ve) credited\b|"
    r"\bwe have credited\b|"
    r"\bpayment has been processed\b",
    re.IGNORECASE,
)
_LONG_NUMBER = re.compile(r"\d{6,}")
_LABELED_ID = re.compile(
    r"\b(?:order|invoice|account|ticket|transaction|card)"
    r"\s*(?:number|id|#)?"
    r"\s*[:#-]?\s*([A-Za-z]*\d[A-Za-z0-9-]*)",
    re.IGNORECASE,
)


class UnsafeReplyError(OllamaServiceError):
    failure_code = "unsafe_reply"


class ReplyGenerator:
    def __init__(self, ollama: OllamaService | None = None) -> None:
        self._ollama = ollama or OllamaService()

    async def generate(
        self,
        *,
        subject: str | None,
        sender: str,
        body: str,
        classification: ClassificationResult,
    ) -> ReplyResult:
        source = _source_text(subject, body)
        user = _reply_request(
            subject=subject,
            sender=sender,
            body=body,
            classification=classification,
        )
        error: InvalidModelOutputError | UnsafeReplyError | None = None
        for attempt in (1, 2):
            raw = await self._ollama.chat_json(
                system=load_prompt("email_reply.md"),
                user=user,
                schema=reply_schema(),
                operation="reply",
                num_predict=400,
            )
            try:
                parsed = ReplyResult.model_validate(raw)
            except ValidationError:
                logger.warning("Reply output failed validation")
                error = InvalidModelOutputError(
                    "model output did not match the reply schema"
                )
                user = _retry_request(user)
                continue
            try:
                ensure_reply_is_grounded(parsed.suggested_reply, source=source)
            except UnsafeReplyError as exc:
                logger.warning("Reply attempt %s was rejected", attempt)
                error = exc
                user = _retry_request(user)
                continue
            return parsed
        assert error is not None
        raise error


def reply_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"suggested_reply": {"type": "string"}},
        "required": ["suggested_reply"],
    }


def ensure_reply_is_grounded(reply: str, source: str) -> None:
    """Reject replies that promise completed actions or invent identifiers."""
    if _PROMISES.search(reply):
        logger.warning("Rejected reply that promises a completed action")
        raise UnsafeReplyError("suggested reply is not safe to store")
    if _INVENTED_MECHANISMS.search(reply) and not _INVENTED_MECHANISMS.search(source):
        logger.warning("Rejected reply that invented an account mechanism")
        raise UnsafeReplyError("suggested reply is not safe to store")
    source_lower = source.lower()
    for number in _LONG_NUMBER.findall(reply):
        if number not in source:
            logger.warning("Rejected reply that introduced a long number")
            raise UnsafeReplyError("suggested reply is not safe to store")
    for token in _LABELED_ID.findall(reply):
        if token.lower() not in source_lower:
            logger.warning("Rejected reply that introduced an identifier")
            raise UnsafeReplyError("suggested reply is not safe to store")


def _reply_request(
    *,
    subject: str | None,
    sender: str,
    body: str,
    classification: ClassificationResult,
) -> str:
    return (
        f"Category: {classification.category.value}\n"
        f"Priority: {classification.priority.value}\n"
        f"Summary: {classification.summary}\n\n"
        f"{format_email(subject=subject, sender=sender, body=body)}"
    )


def _retry_request(previous_user: str) -> str:
    return (
        "The previous draft was rejected because it added a promise, "
        "identifier, or account mechanism that was not in the email. "
        "Draft again using only the email text.\n\n"
        f"{previous_user}"
    )


def _source_text(subject: str | None, body: str) -> str:
    return f"{subject or ''}\n{body}"
