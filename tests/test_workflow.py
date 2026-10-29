"""Checks for the exported n8n workflow. Gmail itself is not called."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / "n8n" / "workflows" / "ai_email_assistant.json"
NORMALIZER_PATH = ROOT / "n8n" / "normalize_email.js"

REQUIRED_NODES = {
    "Gmail Trigger",
    "Manual sample email",
    "Load sample email",
    "Normalize email",
    "Email is usable",
    "Call Python API",
    "API call succeeded",
    "Email already processed",
    "Needs human priority review",
    "Route error type",
    "Record skipped email",
    "Record duplicate",
    "Flag for human review",
    "Record routine result",
    "Record invalid API credentials",
    "Record AI failure",
    "Record database failure",
    "Record rejected email",
    "Record workflow failure",
}

FORBIDDEN_TYPES = {
    "n8n-nodes-base.gmail",
    "n8n-nodes-base.emailSend",
    "n8n-nodes-base.slack",
    "n8n-nodes-base.telegram",
    "n8n-nodes-base.twilio",
    "n8n-nodes-base.sendGrid",
}


def test_workflow_routes_mail_without_credentials_or_sending() -> None:
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["name"] == "AI Email Assistant"
    assert workflow["active"] is False
    assert set(nodes) == REQUIRED_NODES
    assert all(node["type"] not in FORBIDDEN_TYPES for node in nodes.values())
    assert all("credentials" not in node for node in nodes.values())

    exported = WORKFLOW_PATH.read_text(encoding="utf-8").lower()
    for secret_marker in ("client_secret", "refresh_token", "private_key", "ya29.", "aiza"):
        assert secret_marker not in exported

    gmail = nodes["Gmail Trigger"]["parameters"]
    assert gmail["authentication"] == "oAuth2"
    assert gmail["event"] == "messageReceived"
    assert gmail["simple"] is False
    assert gmail["filters"]["includeSpamTrash"] is False
    assert gmail["filters"]["includeDrafts"] is False
    assert gmail["filters"]["q"] == "in:inbox"
    assert gmail["options"]["downloadAttachments"] is False
    assert "gmail.readonly" in nodes["Gmail Trigger"]["notes"]

    api = nodes["Call Python API"]
    assert api["type"] == "n8n-nodes-base.httpRequest"
    assert api["parameters"]["method"] == "POST"
    assert api["parameters"]["url"] == "http://127.0.0.1:8000/api/emails/process"
    assert api["parameters"]["genericAuthType"] == "httpHeaderAuth"
    assert api["parameters"]["options"]["timeout"] == 300000
    assert api["parameters"]["options"]["response"]["response"]["neverError"] is True
    assert api.get("retryOnFail") is not True
    assert "host.docker.internal" in api["notes"]
    assert (
        NORMALIZER_PATH.read_text(encoding="utf-8").strip()
        in nodes["Normalize email"]["parameters"]["jsCode"]
    )

    for name in REQUIRED_NODES:
        if not name.startswith("Record") and name != "Flag for human review":
            continue
        values = json.dumps(nodes[name]["parameters"])
        assert "body_text" not in values
        assert "api_payload" not in values

    assert _reachable("Gmail Trigger", workflow["connections"]) == REQUIRED_NODES - {
        "Manual sample email",
        "Load sample email",
    }
    assert "Call Python API" in _reachable("Manual sample email", workflow["connections"])
    assert _targets(workflow["connections"], "Flag for human review") == []
    assert _targets(workflow["connections"], "Record duplicate") == []


def test_normalizer_matches_the_node_runtime() -> None:
    node = _node_executable()
    if node is None:
        pytest.skip("Node.js was not found; normalizer tests were skipped")

    completed = subprocess.run(
        [node, "--test", str(ROOT / "n8n" / "normalize_email.test.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _reachable(start: str, connections: dict) -> set[str]:
    seen = set()
    pending = [start]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        pending.extend(_targets(connections, name))
    return seen


def _targets(connections: dict, name: str) -> list[str]:
    targets = []
    for port in connections.get(name, {}).get("main", []):
        targets.extend(link["node"] for link in port)
    return targets


def _node_executable() -> str | None:
    override = shutil.which("node")
    if override:
        return override
    root = Path(r"D:\laragon\bin\nodejs")
    candidates = list(root.glob("node-v*/node.exe")) if root.is_dir() else []

    def version(path: Path) -> tuple[int, int, int]:
        match = re.search(r"node-v(\d+)\.(\d+)\.(\d+)", str(path))
        if match is None:
            return (0, 0, 0)
        return tuple(int(part) for part in match.groups())

    if not candidates:
        return None
    return str(max(candidates, key=version))
