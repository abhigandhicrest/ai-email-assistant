# n8n workflow

n8n retrieves mail and calls the Python API. Classification, reply drafts, validation, and storage stay in Python. The workflow does not send email and does not call an external notification service.

The importable workflow is [n8n/workflows/ai_email_assistant.json](../n8n/workflows/ai_email_assistant.json). It is inactive until you attach credentials and activate it.

## Install n8n on this computer

Laragon includes Node.js 22 at `D:\laragon\bin\nodejs\node-v22.23.4-win-x64`. From the project directory:

```powershell
.\scripts\start-n8n.cmd
```

Use the `.cmd` file. Windows blocks `.ps1` files while script execution is disabled.

The script installs n8n the first time, then starts it. n8n listens on `http://localhost:5678`. Use a current self-hosted build so the Gmail credential can be limited to the read-only scope described in [Gmail setup](gmail_setup.md).

## API address

Start the API first. On this computer, n8n and the API run on the same Windows machine, so the HTTP node calls:

```text
http://127.0.0.1:8000/api/emails/process
```

`127.0.0.1` inside a Docker container is the container, not Windows. If you later run n8n in Docker, change that host to `host.docker.internal` and set `APP_HOST=0.0.0.0` in `.env`.

Create a Header Auth credential in n8n:

| Field | Value |
| --- | --- |
| Name | `X-API-Key` |
| Value | The `API_KEY` from `.env` |

Attach it to **Call Python API**. Do not paste the key into the workflow JSON.

The HTTP timeout is 300 seconds so classification and one reply retry can finish. The node does not retry the POST on its own.

## Import

1. In n8n, choose Import from File and select `n8n/workflows/ai_email_assistant.json`.
2. On **Gmail Trigger**, select the read-only Gmail credential from [Gmail setup](gmail_setup.md).
3. On **Call Python API**, select the Header Auth credential.
4. Confirm the URL is `http://127.0.0.1:8000` while n8n is running on this computer.
5. Save, then activate the workflow when the API is running.

## Nodes

| Node | Purpose |
| --- | --- |
| Gmail Trigger | Poll the inbox every minute. Simplify is off so the body is included. Spam, trash, drafts, and attachments are excluded. |
| Manual sample email | Editor-only trigger with a synthetic message. It does not poll Gmail. |
| Load sample email | Build that synthetic message. |
| Normalize email | Map the Gmail message to `email_identifier`, `sender_address`, `subject`, `body_text`, and `received_at`. |
| Email is usable | Skip drafts, sent mail, empty messages, attachment-only messages, and messages whose body was not returned. |
| Call Python API | POST the payload with `X-API-Key`. |
| API call succeeded | HTTP 201 or 200 continues. Any other status is an error. |
| Email already processed | `already_processed: true` means the API kept the original row. |
| Needs human priority review | High or Critical, using the priority returned by the API. |
| Route error type | Separate invalid credentials, model failures, database failures, and rejected output. |
| Flag for human review | Record the notification level and `delivery: not_configured`. Nothing is sent. |
| Record skipped email, Record duplicate, Record routine result, Record invalid API credentials, Record AI failure, Record database failure, Record rejected email, Record workflow failure | Save the outcome on the n8n execution. |

The Gmail message id is the email identifier. A repeated poll returns the stored row and does not call the model again.

## Try the API path without Gmail

With the API running and the Header Auth credential attached:

1. Open the workflow in the editor.
2. Select **Manual sample email**.
3. Choose Test workflow.

The sample message is synthetic. A first run should finish at **Record routine result** with HTTP 201. Running it again should finish at **Record duplicate** with HTTP 200.

The Gmail trigger was not executed here because n8n is not installed and no OAuth client is configured.

## Refresh the export

`n8n/normalize_email.js` is the normalizer. After changing it, regenerate the workflow and run the tests:

```powershell
.\.venv\Scripts\python.exe n8n\build_workflow.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_workflow.py
```

The normalizer tests use Laragon Node when `node` is not on `PATH`.
