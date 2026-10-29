"""Email processing, retrieval, and statistics."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.database.connection import session_scope
from app.database.models import EmailCategory, EmailPriority, EmailRecord, ProcessingStatus
from app.database.repository import (
    EmailRepository,
    IncomingEmail,
    InvalidEmailDataError,
    ProcessingUpdate,
)
from app.schemas.email_schema import (
    EmailDetail,
    EmailListItem,
    EmailListResponse,
    EmailProcessRequest,
    EmailProcessResponse,
    NotificationPayload,
    StatsResponse,
)
from app.services.email_classifier import EmailClassifier, review_status_for
from app.services.ollama_service import OllamaService, OllamaServiceError
from app.services.reply_generator import ReplyGenerator

logger = logging.getLogger(__name__)

email_router = APIRouter()

_ERROR_STATUS = {
    "ollama_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "ollama_timeout": status.HTTP_504_GATEWAY_TIMEOUT,
    "ollama_model_error": status.HTTP_502_BAD_GATEWAY,
    "invalid_model_output": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "unsafe_reply": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "persistence_error": status.HTTP_503_SERVICE_UNAVAILABLE,
}


def get_ollama_service() -> OllamaService:
    return OllamaService()


@email_router.post("/emails/process", response_model=EmailProcessResponse)
async def process_email(
    payload: EmailProcessRequest,
    response: Response,
    ollama: Annotated[OllamaService, Depends(get_ollama_service)],
) -> EmailProcessResponse | JSONResponse:
    """Classify one normalized email and store the suggested reply."""
    incoming = IncomingEmail(
        email_identifier=payload.email_identifier,
        sender_address=payload.sender_address,
        subject=payload.subject,
        body_text=payload.body_text,
        received_at=payload.received_at,
    )
    try:
        with session_scope() as session:
            record, action = EmailRepository(session).begin_processing(incoming)
            if action == "existing":
                response.status_code = status.HTTP_200_OK
                return _process_response(record, already_processed=True)
            email_id = record.id
    except InvalidEmailDataError:
        return _failure_response("invalid_email", status.HTTP_422_UNPROCESSABLE_CONTENT)
    except SQLAlchemyError as exc:
        logger.error("Database request failed: %s", exc.__class__.__name__)
        return _failure_response(
            "persistence_error",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        classifier = EmailClassifier(ollama)
        generator = ReplyGenerator(ollama)
        classification = await classifier.classify(
            subject=payload.subject,
            sender=payload.sender_address,
            body=payload.body_text,
        )
        reply = await generator.generate(
            subject=payload.subject,
            sender=payload.sender_address,
            body=payload.body_text,
            classification=classification,
        )
        review_status = review_status_for(classification.priority)
        with session_scope() as session:
            stored = EmailRepository(session).save_success(
                payload.email_identifier,
                ProcessingUpdate(
                    category=classification.category,
                    priority=classification.priority,
                    sentiment=classification.sentiment,
                    summary=classification.summary,
                    recommended_action=classification.recommended_action,
                    priority_reason=classification.priority_reason,
                    suggested_reply=reply.suggested_reply,
                    status=review_status,
                ),
            )
            applied = stored.processing_status == review_status
            result = _process_response(stored, already_processed=not applied)
    except OllamaServiceError as exc:
        _record_failure(payload.email_identifier, exc.failure_code)
        return _failure_response(
            exc.failure_code,
            _ERROR_STATUS.get(exc.failure_code, status.HTTP_502_BAD_GATEWAY),
        )
    except SQLAlchemyError as exc:
        logger.error("Database request failed: %s", exc.__class__.__name__)
        _record_failure(payload.email_identifier, "persistence_error")
        return _failure_response(
            "persistence_error",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except Exception as exc:
        logger.error("Email processing failed: %s", exc.__class__.__name__)
        _record_failure(payload.email_identifier, "processing_error")
        return _failure_response(
            "processing_error",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    response.status_code = (
        status.HTTP_200_OK if result.already_processed else status.HTTP_201_CREATED
    )
    if (
        not result.already_processed
        and result.notification is not None
        and result.notification.required
    ):
        logger.info(
            "Review notification prepared email_id=%s level=%s delivery=not_configured",
            email_id,
            result.notification.level,
        )
    return result


@email_router.get("/emails", response_model=EmailListResponse)
def list_emails(
    category: EmailCategory | None = None,
    priority: EmailPriority | None = None,
    status_filter: Annotated[ProcessingStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> EmailListResponse | JSONResponse:
    """Return a page of processed emails. Filters are optional."""
    try:
        with session_scope() as session:
            rows, total = EmailRepository(session).list_emails(
                category=category,
                priority=priority,
                status=status_filter,
                page=page,
                page_size=page_size,
            )
            return EmailListResponse(
                items=[EmailListItem.model_validate(row) for row in rows],
                page=page,
                page_size=page_size,
                total=total,
            )
    except SQLAlchemyError as exc:
        logger.error("Database request failed: %s", exc.__class__.__name__)
        return _failure_response(
            "persistence_error",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The request could not be completed",
        )


@email_router.get("/emails/{email_id}", response_model=EmailDetail)
def get_email(email_id: int) -> EmailDetail | JSONResponse:
    """Return one stored email, including its suggested reply."""
    try:
        with session_scope() as session:
            record = EmailRepository(session).get_by_id(email_id)
            detail = None if record is None else EmailDetail.model_validate(record)
    except SQLAlchemyError as exc:
        logger.error("Database request failed: %s", exc.__class__.__name__)
        return _failure_response(
            "persistence_error",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The request could not be completed",
        )
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email was not found",
        )
    return detail


@email_router.get("/stats", response_model=StatsResponse)
def email_stats() -> StatsResponse | JSONResponse:
    """Return totals grouped by category, priority, and status."""
    try:
        with session_scope() as session:
            return StatsResponse.model_validate(
                EmailRepository(session).processing_stats()
            )
    except SQLAlchemyError as exc:
        logger.error("Database request failed: %s", exc.__class__.__name__)
        return _failure_response(
            "persistence_error",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The request could not be completed",
        )


def _process_response(record: EmailRecord, *, already_processed: bool) -> EmailProcessResponse:
    return EmailProcessResponse(
        id=record.id,
        email_identifier=record.email_identifier,
        sender_address=record.sender_address,
        subject=record.subject,
        category=record.category,
        priority=record.priority,
        sentiment=record.sentiment,
        summary=record.summary,
        recommended_action=record.recommended_action,
        priority_reason=record.priority_reason,
        suggested_reply=record.suggested_reply,
        processing_status=record.processing_status,
        failure_detail=record.failure_detail,
        already_processed=already_processed,
        received_at=record.received_at,
        processed_at=record.processed_at,
        notification=_notification(record),
    )


def _notification(record: EmailRecord) -> NotificationPayload | None:
    if record.priority == EmailPriority.HIGH:
        level = "urgent_review"
    elif record.priority == EmailPriority.CRITICAL:
        level = "immediate_review"
    else:
        return None
    return NotificationPayload(
        required=True,
        level=level,
        email_id=record.id,
        priority=record.priority,
        summary=record.summary,
        delivery="not_configured",
    )


def _record_failure(email_identifier: str, failure_code: str) -> None:
    try:
        with session_scope() as session:
            EmailRepository(session).mark_failed(email_identifier, failure_code)
    except Exception:
        logger.error("Could not record processing failure code=%s", failure_code)


def _failure_response(
    failure_code: str,
    status_code: int,
    detail: str = "The email could not be processed",
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "failure_code": failure_code},
    )
