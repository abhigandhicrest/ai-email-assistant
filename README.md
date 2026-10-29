# AI Email Assistant

A local email assistant that will classify incoming mail, assign a priority, draft a suggested reply, and store the result for human review.

The local API, MySQL storage, Ollama classification, and the n8n workflow export are in place. n8n is installed. Gmail has not been connected. No email is sent.

## Stack

- Python 3.14 and FastAPI
- MySQL 8 from the local Laragon installation, accessed with SQLAlchemy and PyMySQL
- Ollama for local model inference
- n8n for Gmail retrieval and workflow orchestration
- pytest for automated tests

No emails are sent by this project. Gmail access is read-only.

## Current status

| Check | Result |
| --- | --- |
| Python | 3.14.8, virtual environment in `.venv` |
| Dependencies | Installed from `requirements.txt` |
| MySQL | Laragon MySQL 8.0.30 listening on port 3306 |
| Ollama | 0.40.11, model `llama3.2:latest` |
| FastAPI | Health checks, API key authentication, and email routes |
| Ollama | Classifies mail and drafts a suggested reply when an email is processed |
| Database `ai_email_assistant` | Created and migrated |
| n8n | Installed. Start it with `scripts/start-n8n.cmd`, then import the workflow |

## Set up the environment on Windows

From PowerShell, in this directory:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

The virtual environment and packages are already installed in this workspace. Copy `.env.example` to `.env` before the application starts reading configuration. Put real values only in `.env`. That file is gitignored.

Activation is optional because the commands below call the virtual environment interpreter directly:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Documentation

- [Environment setup](docs/setup.md)
- [Architecture](docs/architecture.md)
- [Ollama setup](docs/ollama_setup.md)
- [Gmail setup](docs/gmail_setup.md)
- [n8n workflow](docs/workflow.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Data retention and security](docs/security.md)

## Run the API

Copy the example environment file and replace `API_KEY` with your own value of at least 16 characters. The placeholder in `.env.example` is rejected at startup.

```powershell
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m app.main
```

The server binds to `APP_HOST` and `APP_PORT` from `.env`. The defaults are `127.0.0.1` and `8000`.

| Method and path | Auth | Result |
| --- | --- | --- |
| `GET /health` | Public | `{"status":"ok"}` |
| `GET /health/ollama` | Public | Ollama reachability, without the response body from Ollama |
| `POST /api/emails/process` | Header `X-API-Key` | Classify one email, store a suggested reply, and return it for review |
| `GET /api/emails` | Header `X-API-Key` | Paginated list. Optional `category`, `priority`, `status`, `page`, and `page_size` |
| `GET /api/emails/{id}` | Header `X-API-Key` | One stored email, including the body and suggested reply |
| `GET /api/stats` | Header `X-API-Key` | Totals by category, priority, and status |
| Other `/api/...` | Header `X-API-Key` | Missing or wrong keys return HTTP 401 |

`POST /api/emails/process` does not send mail. A new email returns HTTP 201. The same identifier returns HTTP 200 with `already_processed: true` and does not call the model again. A failed, unlocked row can be submitted again. High and Critical results include a notification object with `delivery: "not_configured"`; nothing is sent. The process response and the list omit the email body. The detail route includes it.

Start n8n with `.\scripts\start-n8n.cmd`, then import [n8n/workflows/ai_email_assistant.json](n8n/workflows/ai_email_assistant.json). On this computer the workflow calls `http://127.0.0.1:8000` and sends `X-API-Key` from an n8n credential. Copy `API_KEY` from `.env` into that credential. A Dockerized n8n process must use a host address such as `host.docker.internal` and `APP_HOST=0.0.0.0`. See [n8n workflow](docs/workflow.md) and [Gmail setup](docs/gmail_setup.md).

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest -q
curl.exe -s http://127.0.0.1:8000/health
curl.exe -s http://127.0.0.1:8000/health/ollama
```

Phase 2 live API check: `GET /health` returned `{"status":"ok"}`, `GET /health/ollama` returned `{"status":"ok","ollama":"reachable"}`, and `GET /api/emails` without a valid key returned HTTP 401.

Phase 7 tests: 52 passed and 24 skipped with MySQL and live Ollama disabled. With `TEST_DATABASE_URL` set, 74 passed and 2 skipped. Those 2 live model tests then passed with `OLLAMA_INTEGRATION=1` (62 seconds). Duplicate handling and the absence of a send route are covered by that run. See [Environment setup](docs/setup.md) and [Troubleshooting](docs/troubleshooting.md).
