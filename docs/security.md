# Data retention and deletion

The application stores one row per email identifier in the `emails` table. It stores the sender address, subject, a minimized body, classification fields, the suggested reply, processing status, and timestamps. It does not store Gmail passwords, OAuth tokens, or the API key.

## What is minimized

Before a row is inserted, the repository:

- Removes null bytes from text.
- Limits the subject to 500 characters and the body to 20,000 characters.
- Limits summaries, actions, and replies to fixed lengths.
- Stores a failure as a short lowercase code such as `ollama_unavailable`, not as an exception message or the email body.

A duplicate submission returns the existing row and does not replace its subject, body, or a locked reply.

SQL is sent through SQLAlchemy parameters. Email text is not concatenated into queries. The SQLAlchemy engine log is kept at warning level so statement parameters are not written during normal operation.

## How long to keep rows

This local learning application does not delete rows on a schedule. Review stored mail and delete rows that are no longer needed. A practical starting point is to delete rows whose received time is older than 90 days.

## Delete stored rows

Use the repository so the cutoff or id stays a bound parameter.

Delete one row by its internal id:

```python
from app.database.connection import get_session_factory
from app.database.repository import EmailRepository

session = get_session_factory()()
try:
    EmailRepository(session).delete_by_id(123)
    session.commit()
finally:
    session.close()
```

Delete rows received before a cutoff:

```python
from datetime import datetime, timedelta, timezone

from app.database.connection import get_session_factory
from app.database.repository import EmailRepository

cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=90)
session = get_session_factory()()
try:
    removed = EmailRepository(session).delete_received_before(cutoff)
    session.commit()
    print(removed)
finally:
    session.close()
```

`DATABASE_URL` must be available in the environment or `.env` before running that code. The printout is only the number of deleted rows.

The same cutoff can be applied in a MySQL client with a date literal:

```sql
DELETE FROM emails WHERE received_at < '2026-01-01 00:00:00';
```

Do not build that statement by pasting email subjects or bodies into the SQL text.

Automated tests write only to the database named by `TEST_DATABASE_URL`, normally `ai_email_assistant_test`. They do not delete rows from `ai_email_assistant`.

## Review

The Phase 7 review checked the application and the exported workflow:

- There is no route or workflow node that sends email. `POST /api/emails/process` stores a suggestion.
- `/api` routes reject a missing key and a wrong key with the same 401 response. The comparison uses a SHA-256 digest and `secrets.compare_digest`. The key is not logged.
- Database and Ollama failures return a fixed message and a short `failure_code`. Logs record the exception class, not the exception text, the database URL, or the email body.
- Email text is stored through SQLAlchemy parameters. The engine hides bound parameters and keeps the SQLAlchemy engine logger at warning.
- Model output is validated. Priority can be raised by application rules. Unsafe reply drafts are discarded after one retry.
- The workflow JSON has no client secret, refresh token, or API key. Gmail is documented as `gmail.readonly` only.

Remaining limits: the API listens on `127.0.0.1` by default, so it is not exposed on the network. Setting `APP_HOST` to `0.0.0.0` makes the API key the only access control, and local HTTP does not encrypt that header. Anyone with the key can read stored bodies from the detail route. n8n execution history, once n8n is running, can also contain message text. Rows are not deleted on a schedule.

## n8n

The exported workflow has no Gmail client secret, refresh token, or API key. Put those in n8n credentials after import. The Gmail credential should request only `https://www.googleapis.com/auth/gmail.readonly`.

n8n execution history on this computer can contain the email text and the suggested reply. Restrict access to the n8n process and delete old executions when they are no longer needed. The workflow does not send mail.
