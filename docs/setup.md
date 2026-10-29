# Environment setup

Phase 1 prepared the Windows environment. Phase 2 added the FastAPI process. Phase 3 adds the MySQL database, SQLAlchemy models, and Alembic migrations. Phase 5 adds the email processing API. Phase 6 adds the n8n workflow export. Phase 7 recorded the final test run. n8n is not installed yet.

## What was already installed

These were present and suitable, so nothing new was installed at the system level:

| Software | Location / version | Use |
| --- | --- | --- |
| Python | 3.14.8 at `C:\Users\AbhishekGandhi\AppData\Local\Python\pythoncore-3.14-64\python.exe` | Backend |
| pip | 26.2.1, upgraded to 26.2.2 inside `.venv` | Package install |
| Laragon MySQL | 8.0.30 at `D:\laragon\bin\mysql\mysql-8.0.30-winx64` | Persistent storage |
| Ollama | 0.40.11, API at `http://127.0.0.1:11434` | Local LLM |

Laragon also contains Python 3.10 under `D:\laragon\bin\python\python-3.10`. That interpreter is too old for `pydantic-settings` 2.16.1, which requires Python 3.11 or newer. The project virtual environment uses Python 3.14.

Python 3.14.8 on this machine is the standard GIL build (`sys._is_gil_enabled()` is true). Installed wheels match that build: SQLAlchemy and `pydantic-core` used `cp314` Windows wheels. `cryptography` 50.0.2 installed from the `cp311-abi3` Windows wheel, which is the stable ABI build and imported successfully on Python 3.14.

## MySQL

The server is already running and listening on `127.0.0.1:3306`.

```powershell
& "D:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysql.exe" --version
& "D:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysqladmin.exe" -u root --protocol=TCP -h 127.0.0.1 ping
& "D:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysql.exe" -u root -h 127.0.0.1 --protocol=TCP -e "SELECT VERSION();"
```

Verified on this machine:

- `mysql --version` printed `Ver 8.0.30 for Win64`.
- `mysqladmin ping` printed `mysqld is alive`.
- `SELECT VERSION()` returned `8.0.30` for user `root` with an empty password.

The application database `ai_email_assistant` and the test database `ai_email_assistant_test` were created with `utf8mb4`. For this Laragon server, the application URL is:

```text
mysql+pymysql://root:@127.0.0.1:3306/ai_email_assistant
```

Put that URL in `.env` only. `.env.example` keeps a placeholder password. The engine also sets the connection character set to `utf8mb4`.

Apply migrations after `DATABASE_URL` is set:

```powershell
$env:DATABASE_URL = "mysql+pymysql://root:@127.0.0.1:3306/ai_email_assistant"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

The initial revision is `e2f9b934f244`. It was applied to `ai_email_assistant`. `alembic current` printed `e2f9b934f244 (head)`, and the `emails` table was empty. Migration output can include the database URL when a connection fails, so do not share those tracebacks.

`mysql.exe` is not on `PATH`. Use the full Laragon path above, or start a Laragon terminal that adds it.

The SQLAlchemy URL form for this driver is:

```text
mysql+pymysql://USER:PASSWORD@127.0.0.1:3306/ai_email_assistant
```

For the current empty local root password, the password segment is empty:

```text
mysql+pymysql://root:@127.0.0.1:3306/ai_email_assistant
```

Keep that URL in `.env` only. `.env.example` keeps a placeholder password.

MySQL 8 uses `caching_sha2_password`. `cryptography` is installed so PyMySQL can authenticate with that plugin.

## Python virtual environment

From `D:\laragon\www\ai-email-assistant`:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

This has already been done. Re-run the install command after `requirements.txt` changes.

Direct packages:

| Package | Version | Role |
| --- | --- | --- |
| fastapi | 0.162.0 | API |
| uvicorn | 0.54.0 | ASGI server |
| pydantic | 2.14.1 | Validation |
| pydantic-settings | 2.16.1 | Environment configuration |
| SQLAlchemy | 2.1.6 | Database access |
| alembic | 1.20.1 | Migrations |
| PyMySQL | 1.2.3 | MySQL driver |
| cryptography | 50.0.2 | MySQL 8 authentication |
| httpx | 0.28.1 | Ollama HTTP client |
| httpx2 | 2.16.0 | Client used by FastAPI's test client |
| pytest | 9.1.1 | Tests |
| python-dotenv | 1.2.4 | `.env` loading |

Versions were checked on PyPI before installation. Each selected release allows Python 3.14 and publishes a Windows wheel or a pure-Python wheel. Transitive packages, including Starlette and `pydantic-core`, were installed by pip and are not pinned in `requirements.txt`.

Import check that succeeded:

```powershell
.\.venv\Scripts\python.exe -c "import fastapi, pydantic, sqlalchemy, alembic, pymysql, cryptography, httpx, pytest; print('imports_ok')"
```

## Configuration

```powershell
Copy-Item .env.example .env
```

Edit `.env` locally. Do not put Gmail credentials, OAuth secrets, or the live API key in source files.

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | Runtime environment name, such as `local` |
| `APP_HOST` | Bind address for the API |
| `APP_PORT` | Bind port for the API |
| `API_KEY` | Credential for non-public API routes |
| `DATABASE_URL` | SQLAlchemy URL for the MySQL database |
| `OLLAMA_BASE_URL` | Ollama API origin |
| `OLLAMA_MODEL` | Model name passed to Ollama |
| `OLLAMA_TIMEOUT_SECONDS` | Model response timeout, default 90 seconds |
| `OLLAMA_CONNECT_TIMEOUT_SECONDS` | Connection timeout, default 5 seconds |

When n8n is added, a container must call the Windows host by a host address such as `host.docker.internal`, not by the container's own `localhost`. n8n is not installed yet, and Docker is not on `PATH`, so that address will be chosen in the workflow phase.

## Run the API

```powershell
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m app.main
```

Edit `.env` before starting. `API_KEY` must be at least 16 characters, and the placeholder `replace-with-a-long-random-string` is rejected. Startup logs the names of invalid settings and does not print the key or database URL.

`GET /health` and `GET /health/ollama` are public. Every path under `/api` requires the header `X-API-Key`. Interactive docs are at `http://127.0.0.1:8000/docs`.

Keep `APP_HOST` at `127.0.0.1` while the API is used only from this computer. Set it to `0.0.0.0` when n8n runs on another machine or in Docker, and call the Windows host by an address such as `host.docker.internal` rather than the container's own localhost.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

With neither `TEST_DATABASE_URL` nor `OLLAMA_INTEGRATION` set, pytest result: 52 passed, 24 skipped. Twenty-two skips are MySQL tests. Two skips are live Ollama calls. The workflow checks do not call Gmail and do not need n8n to be installed. The normalizer tests use Laragon Node. One test asserts the API has no send route.

MySQL integration tests use a separate database:

```powershell
$env:TEST_DATABASE_URL = "mysql+pymysql://root:@127.0.0.1:3306/ai_email_assistant_test"
.\.venv\Scripts\python.exe -m pytest -q
```

That run result: 74 passed, 2 skipped. It creates the schema with Alembic, then stores and deletes synthetic rows in `ai_email_assistant_test` only. The API tests mock Ollama. Duplicate inserts and a repeated process call are included. The two remaining skips are the live model calls:

```powershell
$env:OLLAMA_INTEGRATION = "1"
.\.venv\Scripts\python.exe -m pytest -q tests/test_classification.py tests/test_reply_generation.py -k live
```

That run result: 2 passed in 62 seconds.

A separate live check with Ollama already running returned:

- `GET /health` -> `200 {"status":"ok"}`
- `GET /health/ollama` -> `200 {"status":"ok","ollama":"reachable"}`
- `GET /api/emails` without a valid key -> `401 {"detail":"Invalid or missing API key"}`

The smoke-test server was stopped after those requests.

## Not set up yet

- Git repository (this directory is not currently a Git repo; `.gitignore` is ready)
- Gmail OAuth client. n8n is installed. Start it with `scripts/start-n8n.cmd`, then import the workflow. See [Gmail setup](gmail_setup.md) and [n8n workflow](workflow.md).
