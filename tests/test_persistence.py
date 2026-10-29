"""Persistence tests.

Text minimization and URL checks always run. Tests that request `mysql_engine`
use the MySQL database named by TEST_DATABASE_URL and are skipped when that
variable is unset.
"""

import os
import threading
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.database.connection import DatabaseConfigurationError, build_engine
from app.database.models import (
    EmailCategory,
    EmailPriority,
    EmailRecord,
    ProcessingStatus,
    Sentiment,
)
from app.database.repository import (
    MAX_BODY_CHARS,
    EmailNotFoundError,
    EmailRepository,
    IncomingEmail,
    InvalidEmailDataError,
    InvalidFailureDetailError,
    ProcessingUpdate,
    minimize_text,
)


def test_minimize_text_strips_nulls_and_limits_length() -> None:
    assert minimize_text("a\x00b\r\n", 10) == "ab"
    minimized = minimize_text("x" * 50, 20)

    assert minimized.endswith("[truncated]")
    assert len(minimized) <= 20
    assert "\x00" not in minimized


def test_empty_database_url_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()

    assert get_settings().database_url == ""


def test_sqlite_database_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///secret.db")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="Invalid configuration") as raised:
        get_settings()

    assert "secret.db" not in str(raised.value)


def test_engine_builder_rejects_non_mysql_url_without_echoing_it() -> None:
    with pytest.raises(DatabaseConfigurationError) as raised:
        build_engine("sqlite:///secret-file.db")

    assert "secret-file" not in str(raised.value)


@pytest.fixture(scope="session")
def mysql_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "TEST_DATABASE_URL is not set; MySQL integration tests were skipped"
        )
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
    engine = build_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(mysql_engine):
    with mysql_engine.begin() as connection:
        connection.execute(text("DELETE FROM emails"))
    factory = sessionmaker(bind=mysql_engine, autoflush=False, expire_on_commit=False)
    db_session = factory()
    try:
        yield db_session
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise
    finally:
        db_session.close()


def test_migration_creates_email_storage(mysql_engine) -> None:
    inspector = inspect(mysql_engine)
    columns = {column["name"] for column in inspector.get_columns("emails")}

    assert columns == set(EmailRecord.__table__.columns.keys())
    unique_columns = [
        constraint["column_names"]
        for constraint in inspector.get_unique_constraints("emails")
    ]
    unique_indexes = [
        index["column_names"]
        for index in inspector.get_indexes("emails")
        if index["unique"]
    ]
    assert ["email_identifier"] in unique_columns + unique_indexes


def test_email_round_trip_preserves_fields(session) -> None:
    repository = EmailRepository(session)
    incoming = _incoming(body_text="Customer cannot log in.\nPlease help.")

    record, created = repository.create_if_absent(incoming)
    saved = repository.save_success(record.email_identifier, _update())
    session.flush()

    loaded = repository.get_by_id(saved.id)

    assert created is True
    assert loaded is not None
    assert loaded.sender_address == incoming.sender_address
    assert loaded.subject == "Login problem"
    assert loaded.body_text == incoming.body_text
    assert loaded.category == EmailCategory.TECHNICAL_SUPPORT
    assert loaded.priority == EmailPriority.MEDIUM
    assert loaded.sentiment == Sentiment.NEGATIVE
    assert loaded.summary == "The customer cannot log in."
    assert loaded.processing_status == ProcessingStatus.AWAITING_REVIEW
    assert loaded.processed_at is not None
    assert loaded.received_at == datetime(2026, 10, 28, 4, 15)


def test_duplicate_identifier_does_not_create_or_overwrite(session) -> None:
    repository = EmailRepository(session)
    original = _incoming(subject="Original subject", body_text="Original body")
    first, created = repository.create_if_absent(original)
    duplicate, created_again = repository.create_if_absent(
        _incoming(
            subject="'; DROP TABLE emails; --",
            body_text="replacement body",
        )
    )

    assert created is True
    assert created_again is False
    assert duplicate.id == first.id
    assert duplicate.subject == "Original subject"
    assert duplicate.body_text == "Original body"
    assert session.scalar(select(func.count()).select_from(EmailRecord)) == 1
    assert "emails" in inspect(session.get_bind()).get_table_names()


def test_sql_text_is_stored_as_data(session) -> None:
    repository = EmailRepository(session)
    hostile = "'; DROP TABLE emails; --"
    record, created = repository.create_if_absent(
        _incoming(email_identifier="hostile-message", subject=hostile, body_text=hostile)
    )

    assert created is True
    assert record.subject == hostile
    assert record.body_text == hostile
    assert repository.get_by_identifier("hostile-message") is not None


def test_long_body_is_minimized_before_storage(session) -> None:
    repository = EmailRepository(session)
    record, _ = repository.create_if_absent(_incoming(body_text="y" * (MAX_BODY_CHARS + 100)))

    assert record.body_text.endswith("[truncated]")
    assert len(record.body_text) <= MAX_BODY_CHARS


def test_invalid_identifier_is_not_stored(session) -> None:
    repository = EmailRepository(session)

    with pytest.raises(InvalidEmailDataError):
        repository.create_if_absent(_incoming(email_identifier="bad\nidentifier"))

    assert session.scalar(select(func.count()).select_from(EmailRecord)) == 0


def test_completed_record_is_not_overwritten(session) -> None:
    repository = EmailRepository(session)
    record, _ = repository.create_if_absent(_incoming())
    repository.save_success(record.email_identifier, _update())
    repository.save_success(
        record.email_identifier,
        _update(summary="A different summary", suggested_reply="A different reply"),
    )

    loaded = repository.get_by_identifier(record.email_identifier)

    assert loaded is not None
    assert loaded.summary == "The customer cannot log in."
    assert loaded.suggested_reply == "Thanks for your message. A person will review it."


def test_locked_reply_survives_processing_update(session) -> None:
    repository = EmailRepository(session)
    record, _ = repository.create_if_absent(_incoming())
    repository.lock_reply(record.email_identifier, "Reviewed by a person.")
    repository.save_success(
        record.email_identifier,
        _update(suggested_reply="Automated replacement"),
    )

    loaded = repository.get_by_identifier(record.email_identifier)

    assert loaded is not None
    assert loaded.suggested_reply == "Reviewed by a person."
    assert loaded.reply_locked is True
    assert loaded.summary == "The customer cannot log in."
    assert loaded.processing_status == ProcessingStatus.AWAITING_REVIEW


def test_failure_code_is_stored_and_free_text_is_rejected(session) -> None:
    repository = EmailRepository(session)
    record, _ = repository.create_if_absent(_incoming())

    with pytest.raises(InvalidFailureDetailError):
        repository.mark_failed(record.email_identifier, "password=super-secret body")

    unchanged = repository.get_by_identifier(record.email_identifier)
    assert unchanged is not None
    assert unchanged.processing_status == ProcessingStatus.PROCESSING
    assert unchanged.failure_detail is None

    failed = repository.mark_failed(record.email_identifier, "ollama_unavailable")

    assert failed.processing_status == ProcessingStatus.FAILED
    assert failed.failure_detail == "ollama_unavailable"


def test_failure_does_not_replace_a_finished_record(session) -> None:
    repository = EmailRepository(session)
    record, _ = repository.create_if_absent(_incoming())
    repository.save_success(record.email_identifier, _update())
    repository.mark_failed(record.email_identifier, "ollama_unavailable")

    loaded = repository.get_by_identifier(record.email_identifier)

    assert loaded is not None
    assert loaded.processing_status == ProcessingStatus.AWAITING_REVIEW
    assert loaded.failure_detail is None


def test_delete_one_record_and_records_older_than_cutoff(session) -> None:
    repository = EmailRepository(session)
    older, _ = repository.create_if_absent(
        _incoming(
            email_identifier="older-message",
            received_at=datetime(2026, 1, 1, 0, 0),
        )
    )
    newer, _ = repository.create_if_absent(
        _incoming(
            email_identifier="newer-message",
            received_at=datetime(2026, 10, 1, 0, 0),
        )
    )

    assert repository.delete_by_id(older.id) is True
    assert repository.get_by_id(older.id) is None
    removed = repository.delete_received_before(datetime(2026, 8, 1, 0, 0))

    assert removed == 0
    assert repository.get_by_identifier(newer.email_identifier) is not None

    removed_again = repository.delete_received_before(datetime(2026, 11, 1, 0, 0))

    assert removed_again == 1
    assert repository.get_by_identifier(newer.email_identifier) is None


def test_missing_email_cannot_be_updated(session) -> None:
    repository = EmailRepository(session)

    with pytest.raises(EmailNotFoundError):
        repository.save_success("missing-message", _update())


def test_concurrent_inserts_store_one_row(mysql_engine) -> None:
    with mysql_engine.begin() as connection:
        connection.execute(text("DELETE FROM emails"))
    incoming = _incoming(email_identifier="concurrent-message")
    factory = sessionmaker(bind=mysql_engine, autoflush=False, expire_on_commit=False)
    barrier = threading.Barrier(2)
    created_flags: list[bool] = []
    errors: list[BaseException] = []

    def worker() -> None:
        db_session = factory()
        try:
            barrier.wait(5)
            _, created = EmailRepository(db_session).create_if_absent(incoming)
            db_session.commit()
            created_flags.append(created)
        except Exception as exc:
            db_session.rollback()
            errors.append(exc)
        finally:
            db_session.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)

    assert errors == []
    assert sorted(created_flags) == [False, True]
    check_session = factory()
    try:
        count = check_session.scalar(select(func.count()).select_from(EmailRecord))
    finally:
        check_session.close()
    assert count == 1


def _incoming(
    *,
    email_identifier: str = "message-1001",
    subject: str | None = "Login problem",
    body_text: str = "I cannot log in.",
    received_at: datetime | None = None,
) -> IncomingEmail:
    return IncomingEmail(
        email_identifier=email_identifier,
        sender_address="person@example.com",
        subject=subject,
        body_text=body_text,
        received_at=received_at or datetime(2026, 10, 28, 4, 15, tzinfo=timezone.utc),
    )


def _update(
    *,
    summary: str = "The customer cannot log in.",
    suggested_reply: str = "Thanks for your message. A person will review it.",
) -> ProcessingUpdate:
    return ProcessingUpdate(
        category=EmailCategory.TECHNICAL_SUPPORT,
        priority=EmailPriority.MEDIUM,
        sentiment=Sentiment.NEGATIVE,
        summary=summary,
        recommended_action="Review the login issue.",
        priority_reason="The customer cannot access the account.",
        suggested_reply=suggested_reply,
        status=ProcessingStatus.AWAITING_REVIEW,
    )
