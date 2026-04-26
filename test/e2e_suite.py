#!/usr/bin/env python3
"""Local end-to-end scenario suite for Krill.

The suite starts a fresh local Uvicorn instance with an isolated SQLite
braindump, bootstraps auth, configures provider credentials from .env_test,
executes live scenarios, and asks a dedicated judge model to grade results.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Callable
from urllib import error, request
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, build_opener
from uuid import uuid4


DEFAULT_ENV_FILE = ".env_test"
DEFAULT_TIMEOUT_SECONDS = 180
BOOTSTRAP_USERNAME = "krill_e2e_admin"
BOOTSTRAP_PASSWORD = "krill-e2e-password"
APP_SYSTEM_PROMPT = (
    "You are KrillE2E. Follow the user's test instructions exactly. "
    "Keep responses concise and include requested marker strings verbatim."
)
JUDGE_SYSTEM_PROMPT = (
    "You are a strict end-to-end test judge. Return only JSON with this shape: "
    '{"passed": boolean, "reason": string, "confidence": number}. '
    "Pass only when the actual output and observations satisfy the expected behavior."
)
SECRET_KEY_MARKERS = ("api_key", "token", "secret", "password", "private")


class E2EFailure(RuntimeError):
    """Raised when an E2E operation or assertion fails."""


class ScenarioFailure(E2EFailure):
    """Raised when a scenario fails."""


@dataclass
class E2EConfig:
    repo_root: Path
    env_file: Path
    provider_id: str
    model: str
    api_key: str
    judge_provider_id: str
    judge_model: str
    judge_api_key: str
    port: int
    timeout_seconds: int
    keep_artifacts: bool


@dataclass
class ChatStreamResult:
    assistant_text: str
    saw_done: bool
    errors: list[str]
    events: list[dict[str, object]]
    meta: dict[str, object] = field(default_factory=dict)
    used_mcp_tools: list[dict[str, object]] = field(default_factory=list)
    execution_events: list[dict[str, object]] = field(default_factory=list)


@dataclass
class Scenario:
    id: str
    title: str
    prompt: str
    expected_output_prompt: str
    run: Callable[["SuiteContext", "Scenario"], dict[str, object]]
    expected_tool_calls: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ScenarioResult:
    id: str
    title: str
    status: str
    duration_seconds: float
    reason: str = ""
    output_preview: str = ""
    judge_result: dict[str, object] = field(default_factory=dict)
    artifact_path: str = ""


class ApiClient:
    """Small JSON/SSE client that keeps Krill auth cookies."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookie_jar = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookie_jar))

    def json_request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        *,
        timeout: float = 30,
    ) -> dict[str, object] | list[object]:
        body: bytes | None = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(
            url=f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(req, timeout=timeout) as response:
                response_body = response.read().decode("utf-8")
                if not response_body.strip():
                    return {}
                parsed = json.loads(response_body)
                if isinstance(parsed, (dict, list)):
                    return parsed
                raise E2EFailure(f"Unexpected JSON payload at {path}")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise E2EFailure(f"HTTP {exc.code} {method} {path}: {detail}") from exc
        except error.URLError as exc:
            raise E2EFailure(f"Network error {method} {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise E2EFailure(f"Invalid JSON response from {method} {path}") from exc

    def stream_chat(self, payload: dict[str, object], *, timeout: float) -> ChatStreamResult:
        req = request.Request(
            url=f"{self.base_url}/api/chat/stream",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST",
        )
        try:
            with self.opener.open(req, timeout=timeout) as response:
                stream_text = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise E2EFailure(f"Chat stream failed with HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise E2EFailure(f"Network error while calling chat stream: {exc}") from exc
        return parse_sse_payload(stream_text)


class SuiteContext:
    def __init__(self, config: E2EConfig, temp_dir: Path, artifacts_dir: Path) -> None:
        self.config = config
        self.temp_dir = temp_dir
        self.artifacts_dir = artifacts_dir
        self.db_path = temp_dir / "braindump.db"
        self.stdout_path = temp_dir / "uvicorn.stdout.log"
        self.stderr_path = temp_dir / "uvicorn.stderr.log"
        self.base_url = f"http://127.0.0.1:{config.port}"
        self.client = ApiClient(self.base_url)
        self.process: subprocess.Popen[str] | None = None
        self._stdout_handle: Any = None
        self._stderr_handle: Any = None

    def start_server(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "KRILL_BRAINDUMP_PATH": str(self.db_path),
                "KRILL_AUTH_SESSION_SECRET": f"e2e-{uuid4()}",
                "KRILL_AUTH_HASH_ITERATIONS": "100000",
                "PYTHONUNBUFFERED": "1",
            }
        )
        self._stdout_handle = self.stdout_path.open("w", encoding="utf-8")
        self._stderr_handle = self.stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.config.port),
            ],
            cwd=str(self.config.repo_root),
            env=env,
            stdout=self._stdout_handle,
            stderr=self._stderr_handle,
            text=True,
        )
        self.wait_for_ready()

    def stop_server(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=12)
        if self._stdout_handle is not None:
            self._stdout_handle.close()
        if self._stderr_handle is not None:
            self._stderr_handle.close()

    def wait_for_ready(self) -> None:
        deadline = time.time() + self.config.timeout_seconds
        last_error = ""
        while time.time() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise E2EFailure(
                    "Uvicorn exited before readiness. "
                    f"stderr tail: {tail_file(self.stderr_path)}"
                )
            try:
                payload = self.client.json_request("GET", "/api/auth/status", timeout=5)
                if isinstance(payload, dict) and payload.get("bootstrap_required") is True:
                    return
                last_error = f"Unexpected auth status payload: {payload}"
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
            time.sleep(0.5)
        raise E2EFailure(f"Timed out waiting for Uvicorn readiness. Last error: {last_error}")

    def bootstrap_and_configure(self) -> None:
        _phase("SETUP", "Bootstrapping authentication")
        response = self.client.json_request(
            "POST",
            "/api/auth/bootstrap",
            {"username": BOOTSTRAP_USERNAME, "password": BOOTSTRAP_PASSWORD},
            timeout=15,
        )
        if not isinstance(response, dict) or not response.get("ok"):
            raise E2EFailure("Auth bootstrap did not return ok=true")

        _phase("SETUP", "Configuring provider, model, and MCP defaults")
        settings = self.client.json_request("GET", "/api/settings", timeout=15)
        if not isinstance(settings, dict):
            raise E2EFailure("/api/settings returned an invalid payload")

        settings["bot_name"] = "KrillE2E"
        settings["system_prompt"] = APP_SYSTEM_PROMPT
        settings["user_full_name"] = "Krill E2E Tester"
        settings["user_call_name"] = "Tester"
        settings["setup_completed"] = True
        settings["active_provider_id"] = self.config.provider_id
        settings["active_model_id"] = self.config.model
        settings["provider_configs"] = {
            self.config.provider_id: {
                "api_key": self.config.api_key,
                "model": self.config.model,
            }
        }
        settings["mcp_configs"] = {
            "brain_access": {"enabled": True, "params": {}},
            "timed_jobs": {"enabled": True, "params": {}},
        }
        settings["chats"] = []
        settings["active_chat_id"] = ""
        settings["daily_token_usage"] = []

        saved = self.client.json_request("POST", "/api/settings", settings, timeout=20)
        if not isinstance(saved, dict) or not saved.get("setup_completed"):
            raise E2EFailure("Failed to persist setup-complete settings")

    def chat_payload(self, prompt: str) -> dict[str, object]:
        return {
            "message": prompt,
            "history": [],
            "memory_block": "",
            "provider_id": self.config.provider_id,
            "model": self.config.model,
            "api_key": self.config.api_key,
            "bot_name": "KrillE2E",
            "system_prompt": APP_SYSTEM_PROMPT,
            "source_channel": "gateway",
            "source_chat_id": f"e2e-{uuid4()}",
            "source_request_id": f"req-{uuid4()}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local Krill E2E scenario suite.")
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE, help="Path to .env_test.")
    parser.add_argument("--port", type=int, default=0, help="Port override. Defaults to env or a free port.")
    parser.add_argument("--keep-artifacts", action="store_true", help="Keep temp DB/log artifacts after success.")
    parser.add_argument("--scenario", action="append", default=[], help="Run only a scenario id. Repeatable.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    env_file = Path(args.env_file)
    if not env_file.is_absolute():
        env_file = (repo_root / env_file).resolve()

    try:
        env_values = parse_env_file(env_file)
        config = build_config(repo_root, env_file, env_values, cli_port=args.port, cli_keep=args.keep_artifacts)
    except E2EFailure as exc:
        _fail(str(exc))
        return 2

    workspace_tmp = repo_root / ".tmp"
    workspace_tmp.mkdir(parents=True, exist_ok=True)
    temp_dir = workspace_tmp / f"krill-e2e-suite-{uuid4().hex[:12]}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    artifacts_dir = temp_dir / "run-artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    context = SuiteContext(config, temp_dir, artifacts_dir)

    started_at = time.monotonic()
    results: list[ScenarioResult] = []

    try:
        _phase("SETUP", f"Starting local Krill at {context.base_url}")
        _info(f"App provider: {config.provider_id}/{config.model}")
        _info(f"Judge provider: {config.judge_provider_id}/{config.judge_model}")
        context.start_server()
        context.bootstrap_and_configure()

        selected = set(args.scenario)
        scenarios = build_scenarios()
        if selected:
            scenarios = [scenario for scenario in scenarios if scenario.id in selected]
            missing = selected.difference({scenario.id for scenario in scenarios})
            if missing:
                raise E2EFailure(f"Unknown scenario id(s): {', '.join(sorted(missing))}")
        if not scenarios:
            raise E2EFailure("No scenarios selected.")

        for scenario in scenarios:
            results.append(run_scenario(context, scenario))

        total_failed = sum(1 for result in results if result.status != "PASS")
        print_summary(results, time.monotonic() - started_at)
        return 1 if total_failed else 0
    except E2EFailure as exc:
        _fail(str(exc))
        return 1
    finally:
        _phase("SETUP", "Stopping local Krill")
        context.stop_server()
        if config.keep_artifacts or any(result.status != "PASS" for result in results):
            _info(f"Artifacts kept at {temp_dir}")
        else:
            cleanup_temp_dir(temp_dir)


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise E2EFailure(f"Environment file not found: {path}")
    data: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            data[key] = value
    for key, value in os.environ.items():
        if key.startswith("E2E_") or key in {"MINIMAX_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"}:
            data[key] = value
    return data


def build_config(
    repo_root: Path,
    env_file: Path,
    values: dict[str, str],
    *,
    cli_port: int,
    cli_keep: bool,
) -> E2EConfig:
    provider_id = value_from(values, "E2E_PROVIDER_ID", default="gemini").strip().lower()
    model = value_from(values, "E2E_MODEL", default="gemini-2.5-flash").strip()
    api_key = resolve_secret_reference(
        value_from(values, "E2E_API_KEY", "MINIMAX_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY").strip(),
        repo_root=repo_root,
    )
    judge_provider_id = value_from(values, "E2E_JUDGE_PROVIDER_ID").strip().lower()
    judge_model = value_from(values, "E2E_JUDGE_MODEL").strip()
    judge_api_key = resolve_secret_reference(
        value_from(values, "E2E_JUDGE_API_KEY").strip(),
        repo_root=repo_root,
    )
    if judge_provider_id == "openai_codex_oauth" and not judge_api_key:
        judge_api_key = load_codex_auth_bundle()
    if not provider_id or not model or not api_key:
        raise E2EFailure(
            "Missing app provider config. Required: E2E_PROVIDER_ID, E2E_MODEL, E2E_API_KEY "
            "(Gemini aliases are accepted for the API key)."
        )
    if not judge_provider_id or not judge_model or not judge_api_key:
        raise E2EFailure(
            "Missing dedicated judge config. Required: "
            "E2E_JUDGE_PROVIDER_ID, E2E_JUDGE_MODEL, E2E_JUDGE_API_KEY."
        )

    port = cli_port or parse_int(value_from(values, "E2E_PORT"), default=0)
    if port <= 0:
        port = find_free_port()
    timeout_seconds = parse_int(value_from(values, "E2E_TIMEOUT_SECONDS"), default=DEFAULT_TIMEOUT_SECONDS)
    keep_artifacts = cli_keep or parse_bool(value_from(values, "E2E_KEEP_ARTIFACTS"), default=False)
    return E2EConfig(
        repo_root=repo_root,
        env_file=env_file,
        provider_id=provider_id,
        model=model,
        api_key=api_key,
        judge_provider_id=judge_provider_id,
        judge_model=judge_model,
        judge_api_key=judge_api_key,
        port=port,
        timeout_seconds=max(30, timeout_seconds),
        keep_artifacts=keep_artifacts,
    )


def resolve_secret_reference(value: str, *, repo_root: Path) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw == "@codex_auth":
        return load_codex_auth_bundle()
    if raw.startswith("@krill_provider:"):
        provider_id = raw.split(":", 1)[1].strip().lower()
        if not provider_id:
            raise E2EFailure("Secret reference @krill_provider requires a provider id.")
        return load_provider_api_key_from_braindump(repo_root, provider_id)
    return raw


def load_codex_auth_bundle() -> str:
    home = Path.home()
    auth_path = Path(os.getenv("CODEX_AUTH_FILE", "")).expanduser()
    if not str(auth_path).strip() or str(auth_path) == ".":
        auth_path = home / ".codex" / "auth.json"
    if not auth_path.exists():
        raise E2EFailure(f"Codex auth file not found: {auth_path}")
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise E2EFailure(f"Codex auth file is not valid JSON: {auth_path}") from exc
    tokens = payload.get("tokens") if isinstance(payload, dict) else None
    if not isinstance(tokens, dict):
        raise E2EFailure("Codex auth file does not contain a tokens object.")
    access_token = str(tokens.get("access_token", "")).strip()
    refresh_token = str(tokens.get("refresh_token", "")).strip()
    account_id = str(tokens.get("account_id", "")).strip()
    if not access_token or not refresh_token or not account_id:
        raise E2EFailure("Codex auth file is missing access_token, refresh_token, or account_id.")
    return json.dumps(
        {
            "provider": "openai_codex_oauth",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at_unix": 0,
            "account_id": account_id,
        },
        separators=(",", ":"),
    )


def load_provider_api_key_from_braindump(repo_root: Path, provider_id: str) -> str:
    db_path = repo_root / "data" / "braindump.db"
    if not db_path.exists():
        raise E2EFailure(f"Krill braindump not found for @krill_provider:{provider_id}.")
    temp_copy: Path | None = None
    try:
        conn: sqlite3.Connection | None = None
        last_error: Exception | None = None
        for candidate_path in (db_path.resolve(),):
            try:
                conn = sqlite3.connect(str(candidate_path))
                conn.execute("SELECT 1").fetchone()
                break
            except sqlite3.OperationalError as exc:
                last_error = exc
                if conn is not None:
                    conn.close()
                conn = None
        if conn is None:
            fd, temp_name = tempfile.mkstemp(prefix="krill-provider-source-", suffix=".db")
            os.close(fd)
            temp_copy = Path(temp_name)
            temp_copy.write_bytes(db_path.read_bytes())
            conn = sqlite3.connect(str(temp_copy))
            conn.execute("SELECT 1").fetchone()
        try:
            row = conn.execute(
                "SELECT api_key FROM provider_configs WHERE provider_id = ?",
                (provider_id,),
            ).fetchone()
        finally:
            conn.close()
    except Exception as exc:
        raise E2EFailure(f"Could not read provider config for {provider_id} from braindump: {exc}") from exc
    finally:
        if temp_copy is not None:
            temp_copy.unlink(missing_ok=True)
    api_key = str(row[0]).strip() if row is not None else ""
    if not api_key:
        raise E2EFailure(f"No API key found for provider '{provider_id}' in data/braindump.db.")
    return api_key


def value_from(values: dict[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        value = str(values.get(key, "")).strip()
        if value:
            return value
    return default


def parse_int(value: str, *, default: int) -> int:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return default


def parse_bool(value: str, *, default: bool) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def parse_sse_payload(stream_text: str) -> ChatStreamResult:
    assistant_text = ""
    saw_done = False
    errors: list[str] = []
    events: list[dict[str, object]] = []
    meta: dict[str, object] = {}
    used_mcp_tools: list[dict[str, object]] = []
    execution_events: list[dict[str, object]] = []

    for block in stream_text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = "message"
        data_parts: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_parts.append(line[5:].strip())
        if not data_parts:
            continue
        raw_data = "".join(data_parts)
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError:
            errors.append(f"Invalid SSE JSON payload: {raw_data[:160]}")
            continue
        event_entry = {"event": event_name, "data": payload}
        events.append(event_entry)
        if event_name == "token":
            token = payload.get("text") if isinstance(payload, dict) else ""
            if isinstance(token, str):
                assistant_text += token
        elif event_name == "done":
            saw_done = True
        elif event_name == "error":
            detail = payload.get("detail") if isinstance(payload, dict) else ""
            errors.append(str(detail) if detail else "Unknown SSE error.")
        elif event_name == "meta" and isinstance(payload, dict):
            meta = payload
            raw_tools = payload.get("used_mcp_tools", [])
            if isinstance(raw_tools, list):
                used_mcp_tools = [entry for entry in raw_tools if isinstance(entry, dict)]
            raw_execution_events = payload.get("execution_events", [])
            if isinstance(raw_execution_events, list):
                execution_events = [entry for entry in raw_execution_events if isinstance(entry, dict)]
    return ChatStreamResult(
        assistant_text=assistant_text.strip(),
        saw_done=saw_done,
        errors=errors,
        events=events,
        meta=meta,
        used_mcp_tools=used_mcp_tools,
        execution_events=execution_events,
    )


def build_scenarios() -> list[Scenario]:
    llm_marker = f"KRILL_E2E_LLM_{uuid4().hex[:10]}"
    memory_marker = f"KRILL_E2E_MEMORY_{uuid4().hex[:10]}"
    timed_marker = f"KRILL_E2E_TIMED_{uuid4().hex[:10]}"
    return [
        Scenario(
            id="fresh_setup",
            title="Persistence / Fresh Assistant Setup",
            prompt="Verify that the freshly bootstrapped assistant configuration is persisted.",
            expected_output_prompt=(
                "Settings must be setup-complete, have the configured active provider/model, "
                "have brain_access and timed_jobs MCPs enabled, and have no gateway chats yet."
            ),
            run=run_fresh_setup_scenario,
        ),
        Scenario(
            id="general_llm",
            title="General LLM Model Usage",
            prompt=(
                f"Reply in one short sentence and include this exact marker verbatim: {llm_marker}. "
                "Do not call tools."
            ),
            expected_output_prompt=f"The assistant output contains the exact marker {llm_marker}.",
            run=run_chat_scenario,
        ),
        Scenario(
            id="brain_access_memory",
            title="Tool Usage / Brain Access Memory Save",
            prompt=(
                f"Remember this as a normal memory: The E2E memory marker is {memory_marker}. "
                "Use your memory tool to save it, then briefly confirm."
            ),
            expected_output_prompt=(
                f"The assistant should confirm saving a memory containing {memory_marker}; "
                "observations must show brain_access/save_memory was used and the memory is persisted."
            ),
            run=run_brain_access_scenario,
            expected_tool_calls=[("brain_access", "save_memory")],
        ),
        Scenario(
            id="timed_job",
            title="Timed Jobs Trigger",
            prompt=(
                f"Create and trigger a timed job that responds with this exact marker: {timed_marker}."
            ),
            expected_output_prompt=(
                f"The triggered timed job should create a Gateway chat whose assistant output contains {timed_marker}."
            ),
            run=run_timed_job_scenario,
        ),
    ]


def run_scenario(context: SuiteContext, scenario: Scenario) -> ScenarioResult:
    _phase("SCENARIO", f"{scenario.id}: {scenario.title}")
    started_at = time.monotonic()
    artifact_payload: dict[str, object] = {
        "scenario": {
            "id": scenario.id,
            "title": scenario.title,
            "prompt": scenario.prompt,
            "expected_output_prompt": scenario.expected_output_prompt,
        }
    }
    try:
        observations = scenario.run(context, scenario)
        artifact_payload["observations"] = observations
        for mcp_id, tool_id in scenario.expected_tool_calls:
            assert_tool_used(observations, mcp_id, tool_id)
        _phase("JUDGE", f"Evaluating {scenario.id}")
        judge_result = run_judge(context.config, scenario, observations)
        artifact_payload["judge_result"] = judge_result
        if not bool(judge_result.get("passed")):
            raise ScenarioFailure(f"Judge failed scenario: {judge_result.get('reason', 'No reason')}")
        duration = time.monotonic() - started_at
        _ok(f"{scenario.id} passed in {duration:.1f}s")
        return ScenarioResult(
            id=scenario.id,
            title=scenario.title,
            status="PASS",
            duration_seconds=duration,
            reason=str(judge_result.get("reason", "")),
            output_preview=preview(str(observations.get("assistant_output", ""))),
            judge_result=judge_result,
        )
    except Exception as exc:  # noqa: BLE001
        duration = time.monotonic() - started_at
        artifact_payload["error"] = str(exc)
        artifact_payload["app_stdout_tail"] = tail_file(context.stdout_path)
        artifact_payload["app_stderr_tail"] = tail_file(context.stderr_path)
        artifact_path = write_artifact(context, scenario.id, artifact_payload)
        _fail(f"{scenario.id} failed: {exc}")
        _info(f"Scenario artifact: {artifact_path}")
        return ScenarioResult(
            id=scenario.id,
            title=scenario.title,
            status="FAIL",
            duration_seconds=duration,
            reason=str(exc),
            output_preview=preview(str(artifact_payload.get("observations", {}))),
            artifact_path=str(artifact_path),
        )


def run_fresh_setup_scenario(context: SuiteContext, scenario: Scenario) -> dict[str, object]:
    del scenario
    settings = context.client.json_request("GET", "/api/settings", timeout=20)
    chat_state = context.client.json_request("GET", "/api/chat/state", timeout=20)
    if not isinstance(settings, dict) or not isinstance(chat_state, dict):
        raise ScenarioFailure("Settings or chat state returned invalid payloads.")
    assertions: list[str] = []
    assert_condition(bool(settings.get("setup_completed")), "Setup is complete", assertions)
    assert_condition(
        settings.get("active_provider_id") == context.config.provider_id,
        "Active provider matches env",
        assertions,
    )
    assert_condition(
        settings.get("active_model_id") == context.config.model,
        "Active model matches env",
        assertions,
    )
    provider_configs = settings.get("provider_configs")
    assert_condition(
        isinstance(provider_configs, dict) and context.config.provider_id in provider_configs,
        "Provider config is persisted",
        assertions,
    )
    mcp_configs = settings.get("mcp_configs")
    for mcp_id in ("brain_access", "timed_jobs"):
        config = mcp_configs.get(mcp_id) if isinstance(mcp_configs, dict) else None
        assert_condition(
            isinstance(config, dict) and config.get("enabled") is True,
            f"{mcp_id} is enabled",
            assertions,
        )
    chats = chat_state.get("chats")
    assert_condition(isinstance(chats, list) and len(chats) == 0, "Chat state starts empty", assertions)
    return {
        "assistant_output": "Fresh setup persisted correctly.",
        "assertions": assertions,
        "settings_summary": {
            "setup_completed": settings.get("setup_completed"),
            "active_provider_id": settings.get("active_provider_id"),
            "active_model_id": settings.get("active_model_id"),
            "enabled_mcps": sorted(
                key
                for key, value in (mcp_configs.items() if isinstance(mcp_configs, dict) else [])
                if isinstance(value, dict) and value.get("enabled") is True
            ),
            "chat_count": len(chats) if isinstance(chats, list) else None,
        },
    }


def run_chat_scenario(context: SuiteContext, scenario: Scenario) -> dict[str, object]:
    stream = context.client.stream_chat(
        context.chat_payload(scenario.prompt),
        timeout=context.config.timeout_seconds,
    )
    assert_basic_stream(stream)
    observations = stream_observations(stream)
    observations["assistant_output"] = stream.assistant_text
    return observations


def run_brain_access_scenario(context: SuiteContext, scenario: Scenario) -> dict[str, object]:
    stream = context.client.stream_chat(
        context.chat_payload(scenario.prompt),
        timeout=context.config.timeout_seconds,
    )
    assert_basic_stream(stream)
    settings = context.client.json_request("GET", "/api/settings", timeout=20)
    if not isinstance(settings, dict):
        raise ScenarioFailure("/api/settings returned invalid payload after memory scenario.")
    all_memories: list[str] = []
    for key in ("core_memories", "normal_memories"):
        entries = settings.get(key, [])
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    all_memories.append(str(entry.get("content", "")))
    memory_marker = extract_marker(scenario.prompt, "KRILL_E2E_MEMORY_")
    assert_condition(
        any(memory_marker in content for content in all_memories),
        f"Persisted memory contains {memory_marker}",
        [],
    )
    observations = stream_observations(stream)
    observations.update(
        {
            "assistant_output": stream.assistant_text,
            "persisted_memory_found": True,
            "persisted_memory_marker": memory_marker,
            "memory_count": len(all_memories),
        }
    )
    return observations


def run_timed_job_scenario(context: SuiteContext, scenario: Scenario) -> dict[str, object]:
    marker = extract_marker(scenario.prompt, "KRILL_E2E_TIMED_")
    today = date.today().isoformat()
    before_state = context.client.json_request("GET", "/api/chat/state", timeout=20)
    before_count = count_chats(before_state)
    job_payload = {
        "title": f"E2E Timed Job {marker}",
        "prompt": (
            f"Reply in one short sentence and include this exact marker verbatim: {marker}. "
            "Do not call tools."
        ),
        "interval": "once",
        "start_date": today,
        "time_of_day": "00:00",
        "enabled": False,
        "output_decision_enabled": False,
        "channels": ["gateway"],
        "provider_id": context.config.provider_id,
        "model": context.config.model,
    }
    created = context.client.json_request("POST", "/api/timed-jobs", job_payload, timeout=20)
    if not isinstance(created, dict):
        raise ScenarioFailure("Timed job create returned invalid payload.")
    job_id = str(created.get("id", "")).strip()
    if not job_id:
        raise ScenarioFailure("Timed job create did not return an id.")
    trigger = context.client.json_request(
        "POST",
        f"/api/timed-jobs/{quote(job_id)}/trigger",
        timeout=context.config.timeout_seconds,
    )
    if not isinstance(trigger, dict) or trigger.get("ok") is not True:
        raise ScenarioFailure("Timed job trigger did not return ok=true.")
    after_state = context.client.json_request("GET", "/api/chat/state", timeout=20)
    chats = after_state.get("chats") if isinstance(after_state, dict) else []
    if not isinstance(chats, list):
        raise ScenarioFailure("Chat state after timed job is invalid.")
    matching_chat = find_chat_with_assistant_marker(chats, marker)
    if matching_chat is None:
        raise ScenarioFailure(f"No Gateway chat contains timed job marker {marker}.")
    after_count = len(chats)
    assert_condition(after_count > before_count, "Timed job created a new Gateway chat", [])
    jobs_payload = context.client.json_request("GET", "/api/timed-jobs", timeout=20)
    job_still_exists = False
    if isinstance(jobs_payload, dict) and isinstance(jobs_payload.get("jobs"), list):
        job_still_exists = any(isinstance(job, dict) and job.get("id") == job_id for job in jobs_payload["jobs"])
    if not job_still_exists:
        raise ScenarioFailure("Created timed job is not returned by /api/timed-jobs.")
    assistant_output = latest_assistant_content(matching_chat)
    return {
        "assistant_output": assistant_output,
        "timed_job_id": job_id,
        "timed_job_marker": marker,
        "chat_count_before": before_count,
        "chat_count_after": after_count,
        "job_still_exists": job_still_exists,
        "matching_chat_title": matching_chat.get("title", ""),
        "matching_chat_hidden_from_history": matching_chat.get("hidden_from_history", False),
    }


def assert_basic_stream(stream: ChatStreamResult) -> None:
    if stream.errors:
        raise ScenarioFailure(f"Chat stream emitted error event(s): {' | '.join(stream.errors)}")
    if not stream.saw_done:
        raise ScenarioFailure("Chat stream did not emit a done event.")
    if not stream.assistant_text.strip():
        raise ScenarioFailure("Chat stream returned empty assistant output.")


def assert_tool_used(observations: dict[str, object], mcp_id: str, tool_id: str) -> None:
    tools = observations.get("used_mcp_tools", [])
    if not isinstance(tools, list):
        raise ScenarioFailure("Scenario observations do not include used_mcp_tools.")
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("mcp_id") == mcp_id and tool.get("tool_id") == tool_id:
            _ok(f"Tool assertion passed: {mcp_id}/{tool_id}")
            return
    raise ScenarioFailure(f"Expected tool call not observed: {mcp_id}/{tool_id}")


def assert_condition(condition: bool, message: str, assertions: list[str]) -> None:
    if not condition:
        raise ScenarioFailure(message)
    assertions.append(message)
    _ok(message)


def stream_observations(stream: ChatStreamResult) -> dict[str, object]:
    return {
        "saw_done": stream.saw_done,
        "errors": stream.errors,
        "used_mcp_tools": stream.used_mcp_tools,
        "execution_events": stream.execution_events,
        "event_counts": count_events(stream.events),
        "meta": sanitize_for_artifact(stream.meta),
    }


def count_events(events: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event_entry in events:
        event_name = str(event_entry.get("event", "message"))
        counts[event_name] = counts.get(event_name, 0) + 1
    return counts


def count_chats(payload: dict[str, object] | list[object]) -> int:
    if isinstance(payload, dict) and isinstance(payload.get("chats"), list):
        return len(payload["chats"])
    return 0


def find_chat_with_assistant_marker(chats: list[object], marker: str) -> dict[str, object] | None:
    for chat in chats:
        if not isinstance(chat, dict):
            continue
        if marker in latest_assistant_content(chat):
            return chat
    return None


def latest_assistant_content(chat: dict[str, object]) -> str:
    messages = chat.get("messages", [])
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            return str(message.get("content", ""))
    return ""


def extract_marker(text: str, prefix: str) -> str:
    for raw_part in text.replace(".", " ").replace(":", " ").split():
        part = raw_part.strip()
        if part.startswith(prefix):
            return part
    raise ScenarioFailure(f"Unable to extract marker with prefix {prefix}")


def run_judge(config: E2EConfig, scenario: Scenario, observations: dict[str, object]) -> dict[str, object]:
    repo_root = config.repo_root
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from app.providers.registry import get_provider  # pylint: disable=import-outside-toplevel

    provider = get_provider(config.judge_provider_id)
    if provider is None:
        raise ScenarioFailure(f"Judge provider is unsupported: {config.judge_provider_id}")
    prompt = json.dumps(
        {
            "scenario_id": scenario.id,
            "test_prompt": scenario.prompt,
            "expected_output_prompt": scenario.expected_output_prompt,
            "actual_output": observations.get("assistant_output", ""),
            "observations": sanitize_for_artifact(observations),
        },
        ensure_ascii=True,
        indent=2,
    )
    try:
        raw_text, _ = asyncio.run(
            provider.generate(
                prompt=prompt,
                system_prompt=JUDGE_SYSTEM_PROMPT,
                model=config.judge_model,
                api_key=config.judge_api_key,
                history=[],
            )
        )
    except Exception as exc:
        raise ScenarioFailure(f"Judge model call failed: {exc}") from exc
    parsed = parse_judge_json(raw_text)
    _info(
        "Judge: "
        f"passed={bool(parsed.get('passed'))} "
        f"confidence={parsed.get('confidence')} "
        f"reason={parsed.get('reason')}"
    )
    return parsed


def parse_judge_json(raw_text: str) -> dict[str, object]:
    text = str(raw_text or "").strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScenarioFailure(f"Judge returned invalid JSON: {text[:300]}") from exc
    if not isinstance(parsed, dict):
        raise ScenarioFailure("Judge response was not a JSON object.")
    if not isinstance(parsed.get("passed"), bool):
        raise ScenarioFailure("Judge JSON missing boolean 'passed'.")
    parsed["reason"] = str(parsed.get("reason", "")).strip() or "No reason provided."
    confidence = parsed.get("confidence", 0)
    if not isinstance(confidence, (int, float)):
        confidence = 0
    parsed["confidence"] = max(0, min(1, float(confidence)))
    return parsed


def write_artifact(context: SuiteContext, scenario_id: str, payload: dict[str, object]) -> Path:
    path = context.artifacts_dir / f"{scenario_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(sanitize_for_artifact(payload), ensure_ascii=True, indent=2), encoding="utf-8")
    return path


def sanitize_for_artifact(value: object) -> object:
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(marker in key_text.lower() for marker in SECRET_KEY_MARKERS):
                sanitized[key_text] = "***REDACTED***"
            else:
                sanitized[key_text] = sanitize_for_artifact(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_artifact(item) for item in value]
    return value


def tail_file(path: Path, *, max_chars: int = 6000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-max_chars:]


def cleanup_temp_dir(path: Path) -> None:
    try:
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        path.rmdir()
    except OSError:
        _info(f"Could not remove temporary directory: {path}")


def preview(text: str, *, max_len: int = 180) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_len:
        return normalized
    return f"{normalized[:max_len].rstrip()}..."


def print_summary(results: list[ScenarioResult], duration_seconds: float) -> None:
    _phase("SUMMARY", f"Completed in {duration_seconds:.1f}s")
    print("")
    print("RESULT  DURATION  SCENARIO")
    print("------  --------  --------")
    for result in results:
        print(f"{result.status:<6}  {result.duration_seconds:>7.1f}s  {result.id} - {result.title}")
        if result.reason:
            print(f"        reason: {result.reason}")
        if result.output_preview:
            print(f"        output: {result.output_preview}")
        if result.artifact_path:
            print(f"        artifact: {result.artifact_path}")
    failed = sum(1 for result in results if result.status != "PASS")
    if failed:
        _fail(f"{failed} scenario(s) failed")
    else:
        _ok("All scenarios passed")


def _phase(label: str, message: str) -> None:
    print(f"\n[{label}] {message}", flush=True)


def _ok(message: str) -> None:
    print(f"[OK] {message}", flush=True)


def _info(message: str) -> None:
    print(f"[INFO] {message}", flush=True)


def _fail(message: str) -> None:
    print(f"[FAIL] {message}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
