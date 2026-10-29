# Architecture

The assistant stores a suggested reply for a person to review. It does not send email.

```text
Gmail inbox
    |
    | read-only poll (n8n, not installed on this computer yet)
    v
n8n workflow
    | normalize id, sender, subject, body, received time
    | POST /api/emails/process with X-API-Key
    v
FastAPI
    | validate the request
    | insert or reopen one MySQL row, then close that transaction
    | Ollama classifies and drafts a reply
    | application rules raise priority and reject unsafe drafts
    | save the result in a second short transaction
    v
MySQL emails table
```

n8n is only the retrieval and routing layer. The same classification rules are not implemented again in the workflow. High and Critical responses include a notification object with `delivery` set to `not_configured`. No notification service is called.

## Modules

| Path | Responsibility |
| --- | --- |
| `app/main.py` | Process entry, public health routes, and the generic 500 handler |
| `app/config.py` | Environment settings. The API key is a secret and the placeholder value is rejected |
| `app/api/dependencies.py` | `X-API-Key` check for every `/api` path |
| `app/api/email_routes.py` | Process, list, detail, and stats |
| `app/services/ollama_service.py` | Local chat calls, timeouts, and JSON parsing |
| `app/services/email_classifier.py` | Schema validation and deterministic escalation |
| `app/services/reply_generator.py` | Reply draft, one retry, and the grounding checks |
| `app/database/` | MySQL engine, `emails` model, repository, and Alembic migration |
| `n8n/workflows/ai_email_assistant.json` | Importable workflow without credentials |
| `prompts/` | Instructions sent to the local model |

## Processing rules

A new identifier is stored as `processing`, then updated to a review status. The same identifier does not create a second row. A finished or locked row is not overwritten. A failed, unlocked row can be submitted again.

Review status follows priority: Low and Medium are `awaiting_review`, High is `urgent_review`, and Critical is `immediate_review`. Escalation can raise the model’s priority. It does not lower it.

The model call is not held inside a database transaction. Ollama and MySQL failures are returned as a fixed message plus a short `failure_code`.

## What is left for the operator

n8n and the Gmail OAuth client are not configured on this computer. Until they are, mail can still be processed by posting JSON to the API. See [n8n workflow](workflow.md) and [Gmail setup](gmail_setup.md).
