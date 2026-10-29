# Troubleshooting

Run the API from `D:\laragon\www\ai-email-assistant`:

```powershell
.\.venv\Scripts\python.exe -m app.main
```

Health checks:

```powershell
curl.exe -s http://127.0.0.1:8000/health
curl.exe -s http://127.0.0.1:8000/health/ollama
```

`/health` should return `{"status":"ok"}`. `/health/ollama` should return `{"status":"ok","ollama":"reachable"}` when Ollama is running. Neither endpoint requires `X-API-Key`.

## The process exits at startup

`Invalid configuration` means a setting was rejected. The log names the field, not the value.

| Cause | What to change |
| --- | --- |
| `API_KEY` is missing, shorter than 16 characters, or still `replace-with-a-long-random-string` | Put a unique value in `.env` only |
| `DATABASE_URL` is not a `mysql+pymysql` URL with a host and database name | Use the URL shape in `.env.example` |
| `OLLAMA_BASE_URL` contains a username or password | Use `http://127.0.0.1:11434` with no credentials |
| `APP_PORT` is outside 1–65535, or an Ollama timeout is outside its allowed range | Keep the defaults unless you have a reason to change them |

If port 8000 is already taken, stop the older process or choose another `APP_PORT`.

## HTTP 401

Every `/api` path requires the header `X-API-Key`. A missing key and a wrong key return the same body: `{"detail":"Invalid or missing API key"}`. The key is not written to the log.

In n8n, attach a Header Auth credential whose name is `X-API-Key` and whose value is the same `API_KEY` as `.env`. Do not put the key in the workflow JSON.

## The email is rejected before processing

FastAPI returns HTTP 422 when the JSON is missing a field, the sender has no `@`, or the sender contains spaces. That response is a validation error and does not include `failure_code`.

These `failure_code` values mean the row was accepted and then processing failed:

| Status | `failure_code` | Meaning |
| --- | --- | --- |
| 422 | `invalid_email` | A field could not be stored |
| 422 | `invalid_model_output` | The model JSON did not match the schema |
| 422 | `unsafe_reply` | The draft promised a completed action or invented an identifier or account mechanism |
| 502 | `ollama_model_error` | Ollama returned an error response |
| 503 | `ollama_unavailable` | Ollama is not running or the connection failed |
| 503 | `persistence_error` | MySQL could not be reached. The response does not include the driver message |
| 504 | `ollama_timeout` | The model exceeded `OLLAMA_TIMEOUT_SECONDS` (default 90) |
| 500 | `processing_error` | An unexpected failure. The row is marked failed so the same identifier can be submitted again |

The public message stays `The email could not be processed`. Logs record the exception class or the failure code, not the email body and not the database URL.

A failed, unlocked row can be posted again with the same `email_identifier`. A finished row returns HTTP 200 with `already_processed: true`.

## Ollama

```powershell
ollama list
Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags"
```

If `ollama` is not recognized, the program may still be installed but missing from `PATH`. The API uses `OLLAMA_BASE_URL`, which defaults to `http://127.0.0.1:11434`.

`llama3.2` must appear in `ollama list`. Download it with `ollama pull llama3.2` when it is missing. The first call after a restart can take longer because the model is loading. A timeout on that first call is recorded as `ollama_timeout`; submit the same identifier again after Ollama answers `/health/ollama`.

`llama3.2` is a small model. It sometimes asks for an order number on a login email, and the first reply draft can mention a temporary password. The application rejects that draft and retries once. The stored reply is the one that passed the check.

## MySQL

Laragon’s client is not on `PATH`. Use the full path:

```powershell
& "D:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysql.exe" -u root -h 127.0.0.1 --protocol=TCP -e "SELECT VERSION();"
```

`persistence_error` usually means MySQL is stopped, the database does not exist, or the password in `DATABASE_URL` is wrong. This Laragon install accepts an empty root password. The application database is `ai_email_assistant`. Tests use `ai_email_assistant_test` and do not delete rows from the application database.

Apply migrations from the project directory:

```powershell
$env:DATABASE_URL = "mysql+pymysql://root:@127.0.0.1:3306/ai_email_assistant"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

Put the real URL in `.env` only. Alembic can print the URL when a connection fails, so do not share that traceback. The expected revision is `e2f9b934f244`.

## Duplicates

The Gmail message id is the `email_identifier`. Posting it twice returns the original row and does not call the model again. A unique index in MySQL blocks a second insert. A reply with `reply_locked` set is not replaced.

n8n can see the same message on a later poll because the workflow does not mark mail as read. That is intentional: marking read would require a broader Gmail scope. The API treats the repeat as a duplicate.

## n8n cannot reach the API

On this computer, n8n and the API both run on Windows, so the URL is `http://127.0.0.1:8000/api/emails/process`.

Inside Docker, `127.0.0.1` is the container. Change the host in **Call Python API** to `host.docker.internal` and set `APP_HOST=0.0.0.0` in `.env`. Keep the API key in the n8n credential.

The HTTP node waits up to 300 seconds and does not retry the POST. A retry during a slow model call can observe the row while it is still `processing`.

Gmail credential errors are separate from the Python API. Use only `https://www.googleapis.com/auth/gmail.readonly`, and confirm the OAuth redirect URL matches the n8n credential screen. See [Gmail setup](gmail_setup.md).

## Tests were skipped

`pytest` skips MySQL tests when `TEST_DATABASE_URL` is unset, and it skips the two live model tests unless `OLLAMA_INTEGRATION=1`. A skip is not a pass. Commands and the latest counts are in [Environment setup](setup.md).

The normalizer test uses Node.js. If `node` is not on `PATH`, the test uses `D:\laragon\bin\nodejs\node-v*\node.exe`.
