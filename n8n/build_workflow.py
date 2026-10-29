"""Write the importable n8n workflow. Run once after editing the normalizer."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "n8n" / "normalize_email.js").read_text(encoding="utf-8").rstrip() + "\n"
WRAPPER = """
const normalized = normalizeGmailMessage($json);
if (!normalized.ok) {
  return {
    json: {
      skip: true,
      reason: normalized.reason,
      email_identifier: normalized.email_identifier,
    },
  };
}
return {
  json: {
    skip: false,
    email_identifier: normalized.email_identifier,
    api_payload: normalized.payload,
  },
};
"""

SAMPLE = """
return {
  json: {
    id: "sample-message-001",
    labelIds: ["INBOX"],
    subject: "Services",
    date: "2026-10-28T04:15:00.000Z",
    text: "Hello, I would like information about your services.",
    html: false,
    from: {
      text: "Person <person@example.com>",
      value: [{ address: "person@example.com", name: "Person" }],
    },
  },
};
"""


def condition(identifier, left, right, operator_type, operation, single=False):
    operator = {"type": operator_type, "operation": operation}
    if single:
        operator["singleValue"] = True
    return {
        "id": identifier,
        "leftValue": left,
        "rightValue": right,
        "operator": operator,
    }


def conditions(items, combinator="and"):
    return {
        "options": {
            "caseSensitive": True,
            "leftValue": "",
            "typeValidation": "loose",
            "version": 2,
        },
        "conditions": items,
        "combinator": combinator,
    }


def if_parameters(items, combinator="and"):
    return {"conditions": conditions(items, combinator), "options": {}}


def assignment(identifier, name, value, value_type):
    return {"id": identifier, "name": name, "value": value, "type": value_type}


def set_parameters(assignments):
    return {
        "mode": "manual",
        "duplicateItem": False,
        "assignments": {"assignments": assignments},
        "options": {},
    }


def node(identifier, name, node_type, version, x, y, parameters, notes):
    return {
        "id": identifier,
        "name": name,
        "type": node_type,
        "typeVersion": version,
        "position": [x, y],
        "parameters": parameters,
        "notes": notes,
        "notesInFlow": True,
    }


nodes = [
    node(
        "gmail-trigger",
        "Gmail Trigger",
        "n8n-nodes-base.gmailTrigger",
        1.4,
        0,
        280,
        {
            "authentication": "oAuth2",
            "event": "messageReceived",
            "simple": False,
            "maxResults": 10,
            "pollTimes": {"item": [{"mode": "everyMinute"}]},
            "filters": {
                "includeSpamTrash": False,
                "includeDrafts": False,
                "q": "in:inbox",
                "readStatus": "both",
            },
            "options": {"downloadAttachments": False},
        },
        "Poll the test inbox once a minute. Simplify is off so the body is included. "
        "Use a Gmail credential whose only scope is https://www.googleapis.com/auth/gmail.readonly. "
        "Do not grant compose, modify, or send scopes, and do not add a Gmail send node.",
    ),
    node(
        "manual-sample",
        "Manual sample email",
        "n8n-nodes-base.manualTrigger",
        1,
        0,
        40,
        {},
        "Editor-only sample. It does not poll Gmail and it does not send mail.",
    ),
    node(
        "load-sample",
        "Load sample email",
        "n8n-nodes-base.code",
        2,
        260,
        40,
        {"mode": "runOnceForEachItem", "language": "javaScript", "jsCode": SAMPLE.strip()},
        "Provide one synthetic message in the same shape the Gmail trigger emits.",
    ),
    node(
        "normalize-email",
        "Normalize email",
        "n8n-nodes-base.code",
        2,
        520,
        160,
        {
            "mode": "runOnceForEachItem",
            "language": "javaScript",
            "jsCode": SOURCE + WRAPPER,
        },
        "Turn the Gmail message into the API fields. Skip drafts, sent mail, empty messages, and messages without a body.",
    ),
    node(
        "email-usable",
        "Email is usable",
        "n8n-nodes-base.if",
        2.2,
        780,
        160,
        if_parameters(
            [
                condition(
                    "not-skipped",
                    "={{ $json.skip }}",
                    "",
                    "boolean",
                    "false",
                    single=True,
                )
            ]
        ),
        "True when the normalizer produced an API payload.",
    ),
    node(
        "call-api",
        "Call Python API",
        "n8n-nodes-base.httpRequest",
        4.2,
        1040,
        80,
        {
            "method": "POST",
            "url": "http://127.0.0.1:8000/api/emails/process",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($json.api_payload) }}",
            "options": {
                "timeout": 300000,
                "response": {
                    "response": {
                        "fullResponse": True,
                        "neverError": True,
                        "responseFormat": "json",
                    }
                },
            },
        },
        "POST the normalized email. On this computer the API is http://127.0.0.1:8000. "
        "If n8n runs in Docker, change the host to host.docker.internal and set APP_HOST=0.0.0.0. "
        "Attach a Header Auth credential named X-API-Key. Do not type the key into this node. "
        "The timeout covers classification and one reply retry. This node does not send email.",
    ),
    node(
        "api-succeeded",
        "API call succeeded",
        "n8n-nodes-base.if",
        2.2,
        1300,
        80,
        if_parameters(
            [
                condition("created", "={{ $json.statusCode }}", 201, "number", "equals"),
                condition("existing", "={{ $json.statusCode }}", 200, "number", "equals"),
            ],
            combinator="or",
        ),
        "HTTP 201 is a new result. HTTP 200 is an existing result.",
    ),
    node(
        "already-processed",
        "Email already processed",
        "n8n-nodes-base.if",
        2.2,
        1560,
        0,
        if_parameters(
            [
                condition(
                    "duplicate",
                    "={{ $json.body.already_processed }}",
                    "",
                    "boolean",
                    "true",
                    single=True,
                )
            ]
        ),
        "The API kept the original row and did not call the model again.",
    ),
    node(
        "needs-review",
        "Needs human priority review",
        "n8n-nodes-base.if",
        2.2,
        1820,
        80,
        if_parameters(
            [
                condition("high", "={{ $json.body.priority }}", "High", "string", "equals"),
                condition(
                    "critical",
                    "={{ $json.body.priority }}",
                    "Critical",
                    "string",
                    "equals",
                ),
            ],
            combinator="or",
        ),
        "Route only the priority returned by the API. Do not classify the email again.",
    ),
    node(
        "route-error",
        "Route error type",
        "n8n-nodes-base.switch",
        3.2,
        1560,
        280,
        {
            "rules": {
                "values": [
                    {
                        "conditions": conditions(
                            [condition("unauthorized", "={{ $json.statusCode }}", 401, "number", "equals")]
                        ),
                        "renameOutput": True,
                        "outputKey": "credentials",
                    },
                    {
                        "conditions": conditions(
                            [
                                condition(
                                    "unavailable",
                                    "={{ $json.body.failure_code }}",
                                    "ollama_unavailable",
                                    "string",
                                    "equals",
                                ),
                                condition(
                                    "timeout",
                                    "={{ $json.body.failure_code }}",
                                    "ollama_timeout",
                                    "string",
                                    "equals",
                                ),
                                condition(
                                    "model",
                                    "={{ $json.body.failure_code }}",
                                    "ollama_model_error",
                                    "string",
                                    "equals",
                                ),
                            ],
                            combinator="or",
                        ),
                        "renameOutput": True,
                        "outputKey": "ai",
                    },
                    {
                        "conditions": conditions(
                            [
                                condition(
                                    "persistence",
                                    "={{ $json.body.failure_code }}",
                                    "persistence_error",
                                    "string",
                                    "equals",
                                ),
                                condition(
                                    "processing",
                                    "={{ $json.body.failure_code }}",
                                    "processing_error",
                                    "string",
                                    "equals",
                                ),
                            ],
                            combinator="or",
                        ),
                        "renameOutput": True,
                        "outputKey": "database",
                    },
                    {
                        "conditions": conditions(
                            [
                                condition("rejected-status", "={{ $json.statusCode }}", 422, "number", "equals"),
                                condition(
                                    "invalid-output",
                                    "={{ $json.body.failure_code }}",
                                    "invalid_model_output",
                                    "string",
                                    "equals",
                                ),
                                condition(
                                    "unsafe",
                                    "={{ $json.body.failure_code }}",
                                    "unsafe_reply",
                                    "string",
                                    "equals",
                                ),
                                condition(
                                    "invalid-email",
                                    "={{ $json.body.failure_code }}",
                                    "invalid_email",
                                    "string",
                                    "equals",
                                ),
                            ],
                            combinator="or",
                        ),
                        "renameOutput": True,
                        "outputKey": "rejected",
                    },
                ]
            },
            "options": {"fallbackOutput": "extra"},
        },
        "Separate credential, model, database, and validation failures. The fallback is any other workflow error.",
    ),
]

record_notes = "Store the outcome in the n8n execution. This does not send email or an external notification."


def record(identifier, name, x, y, assignments):
    return node(
        identifier,
        name,
        "n8n-nodes-base.set",
        3.4,
        x,
        y,
        set_parameters(assignments),
        record_notes,
    )


nodes.extend(
    [
        record(
            "record-skipped",
            "Record skipped email",
            1040,
            280,
            [
                assignment("outcome", "outcome", "skipped", "string"),
                assignment("reason", "reason", "={{ $json.reason }}", "string"),
                assignment(
                    "identifier",
                    "email_identifier",
                    "={{ $json.email_identifier }}",
                    "string",
                ),
            ],
        ),
        record(
            "record-duplicate",
            "Record duplicate",
            1820,
            -80,
            [
                assignment("outcome", "outcome", "duplicate", "string"),
                assignment("already", "already_processed", True, "boolean"),
                assignment("email-id", "email_id", "={{ $json.body.id }}", "number"),
                assignment(
                    "identifier",
                    "email_identifier",
                    "={{ $json.body.email_identifier }}",
                    "string",
                ),
                assignment("priority", "priority", "={{ $json.body.priority }}", "string"),
                assignment(
                    "status",
                    "processing_status",
                    "={{ $json.body.processing_status }}",
                    "string",
                ),
            ],
        ),
        record(
            "flag-review",
            "Flag for human review",
            2080,
            0,
            [
                assignment("outcome", "outcome", "review_required", "string"),
                assignment("email-id", "email_id", "={{ $json.body.id }}", "number"),
                assignment(
                    "identifier",
                    "email_identifier",
                    "={{ $json.body.email_identifier }}",
                    "string",
                ),
                assignment("priority", "priority", "={{ $json.body.priority }}", "string"),
                assignment(
                    "status",
                    "processing_status",
                    "={{ $json.body.processing_status }}",
                    "string",
                ),
                assignment(
                    "level",
                    "notification_level",
                    "={{ $json.body.notification.level }}",
                    "string",
                ),
                assignment(
                    "delivery",
                    "notification_delivery",
                    "={{ $json.body.notification.delivery }}",
                    "string",
                ),
                assignment(
                    "action",
                    "action",
                    "stored for human review; nothing was sent",
                    "string",
                ),
            ],
        ),
        record(
            "record-routine",
            "Record routine result",
            2080,
            180,
            [
                assignment("outcome", "outcome", "routine_review", "string"),
                assignment("email-id", "email_id", "={{ $json.body.id }}", "number"),
                assignment(
                    "identifier",
                    "email_identifier",
                    "={{ $json.body.email_identifier }}",
                    "string",
                ),
                assignment("priority", "priority", "={{ $json.body.priority }}", "string"),
                assignment(
                    "status",
                    "processing_status",
                    "={{ $json.body.processing_status }}",
                    "string",
                ),
            ],
        ),
        record(
            "record-credentials",
            "Record invalid API credentials",
            1820,
            220,
            [
                assignment("outcome", "outcome", "failed", "string"),
                assignment("failure", "failure_code", "invalid_api_credentials", "string"),
                assignment("status", "status_code", "={{ $json.statusCode }}", "number"),
            ],
        ),
        record(
            "record-ai",
            "Record AI failure",
            1820,
            340,
            [
                assignment("outcome", "outcome", "failed", "string"),
                assignment(
                    "failure",
                    "failure_code",
                    "={{ $json.body.failure_code }}",
                    "string",
                ),
                assignment("status", "status_code", "={{ $json.statusCode }}", "number"),
            ],
        ),
        record(
            "record-database",
            "Record database failure",
            1820,
            460,
            [
                assignment("outcome", "outcome", "failed", "string"),
                assignment(
                    "failure",
                    "failure_code",
                    "={{ $json.body.failure_code }}",
                    "string",
                ),
                assignment("status", "status_code", "={{ $json.statusCode }}", "number"),
            ],
        ),
        record(
            "record-rejected",
            "Record rejected email",
            1820,
            580,
            [
                assignment("outcome", "outcome", "failed", "string"),
                assignment(
                    "failure",
                    "failure_code",
                    "={{ $json.body.failure_code || 'validation_error' }}",
                    "string",
                ),
                assignment("status", "status_code", "={{ $json.statusCode }}", "number"),
            ],
        ),
        record(
            "record-workflow",
            "Record workflow failure",
            1820,
            700,
            [
                assignment("outcome", "outcome", "failed", "string"),
                assignment("failure", "failure_code", "workflow_error", "string"),
                assignment("status", "status_code", "={{ $json.statusCode || 0 }}", "number"),
            ],
        ),
    ]
)

connections = {
    "Gmail Trigger": {"main": [[{"node": "Normalize email", "type": "main", "index": 0}]]},
    "Manual sample email": {
        "main": [[{"node": "Load sample email", "type": "main", "index": 0}]]
    },
    "Load sample email": {"main": [[{"node": "Normalize email", "type": "main", "index": 0}]]},
    "Normalize email": {"main": [[{"node": "Email is usable", "type": "main", "index": 0}]]},
    "Email is usable": {
        "main": [
            [{"node": "Call Python API", "type": "main", "index": 0}],
            [{"node": "Record skipped email", "type": "main", "index": 0}],
        ]
    },
    "Call Python API": {"main": [[{"node": "API call succeeded", "type": "main", "index": 0}]]},
    "API call succeeded": {
        "main": [
            [{"node": "Email already processed", "type": "main", "index": 0}],
            [{"node": "Route error type", "type": "main", "index": 0}],
        ]
    },
    "Email already processed": {
        "main": [
            [{"node": "Record duplicate", "type": "main", "index": 0}],
            [{"node": "Needs human priority review", "type": "main", "index": 0}],
        ]
    },
    "Needs human priority review": {
        "main": [
            [{"node": "Flag for human review", "type": "main", "index": 0}],
            [{"node": "Record routine result", "type": "main", "index": 0}],
        ]
    },
    "Route error type": {
        "main": [
            [{"node": "Record invalid API credentials", "type": "main", "index": 0}],
            [{"node": "Record AI failure", "type": "main", "index": 0}],
            [{"node": "Record database failure", "type": "main", "index": 0}],
            [{"node": "Record rejected email", "type": "main", "index": 0}],
            [{"node": "Record workflow failure", "type": "main", "index": 0}],
        ]
    },
}

workflow = {
    "name": "AI Email Assistant",
    "active": False,
    "nodes": nodes,
    "connections": connections,
    "pinData": {},
    "settings": {"executionOrder": "v1"},
    "meta": {"templateCredsSetupCompleted": False},
    "tags": [],
}

destination = ROOT / "n8n" / "workflows" / "ai_email_assistant.json"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")
print(destination)
