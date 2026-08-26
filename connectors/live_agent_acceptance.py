"""Launch real Pi and Prime Agent CLIs and require each to call Metering.

This is an explicit live acceptance path, not a deterministic CI test. It uses
one caller-selected model through each installed harness and verifies both the
agent tool event and the exact Metering receipt written by that tool call.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "connectors" / "tools" / "metering" / "SKILL.md"
INVOKER = SKILL.parent / "invoke.py"
REQUEST = {"measure": "entropy", "probabilities": [0.125] * 8}
EXPECTED = {
    "base": 2.0,
    "infinite": False,
    "measure": "entropy",
    "value": 3.0,
}


class AcceptanceError(RuntimeError):
    """Raised when one real harness does not use the Metering tool correctly."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _command_prefix(
    environment_name: str, binary_environment: str, binary_name: str
) -> list[str]:
    source = os.environ.get(environment_name)
    if not source:
        binary = os.environ.get(binary_environment, binary_name)
        if not binary or "\x00" in binary:
            raise AcceptanceError(f"{binary_environment} must name one executable")
        return [binary]
    try:
        value = json.loads(source)
    except json.JSONDecodeError as exc:
        raise AcceptanceError(f"{environment_name} is invalid JSON: {exc}") from exc
    if type(value) is not list or not value or any(
        type(item) is not str or not item or "\x00" in item for item in value
    ):
        raise AcceptanceError(
            f"{environment_name} must contain a non-empty JSON string array"
        )
    return value


def _stop_process(process: subprocess.Popen[str]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            if process.poll() is None:
                process.kill()
    elif process.poll() is None:
        process.kill()
    process.wait()


def _run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: int,
    name: str,
) -> subprocess.CompletedProcess[str]:
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=os.name == "posix",
            env=environment,
        )
    except OSError as exc:
        raise AcceptanceError(f"cannot start {name}: {exc}") from exc
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _stop_process(process)
        raise AcceptanceError(f"{name} exceeded {timeout_seconds} seconds") from exc
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _events(source: str, name: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for index, line in enumerate(source.splitlines(), start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AcceptanceError(f"{name} event line {index} is invalid JSON") from exc
        if type(event) is not dict:
            raise AcceptanceError(f"{name} event line {index} is not an object")
        events.append(event)
    if not events:
        raise AcceptanceError(f"{name} returned no JSON events")
    return events


def _assistant_text(events: list[dict[str, object]]) -> str:
    texts: list[str] = []
    for event in events:
        if event.get("type") != "message_end":
            continue
        message = event.get("message")
        if type(message) is not dict or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if type(content) is not list:
            continue
        current = "".join(
            str(item.get("text", ""))
            for item in content
            if type(item) is dict and item.get("type") == "text"
        )
        if current:
            texts.append(current)
    return texts[-1] if texts else ""


def _verify_tool_event(
    events: list[dict[str, object]], tool_name: str, name: str
) -> None:
    starts = [
        event
        for event in events
        if event.get("type") == "tool_execution_start"
        and event.get("toolName") == tool_name
        and str(event.get("args", "")).find(str(INVOKER)) >= 0
    ]
    if not starts:
        raise AcceptanceError(
            f"{name} did not emit a {tool_name} call containing the Metering invoker"
        )
    call_ids = {event.get("toolCallId") for event in starts}
    completed = any(
        event.get("type") == "tool_execution_end"
        and event.get("toolCallId") in call_ids
        and event.get("isError") is False
        for event in events
    )
    if not completed:
        raise AcceptanceError(
            f"{name} Metering tool call did not complete successfully"
        )


def _pi_prompt(receipt: Path) -> str:
    request = _canonical_json(REQUEST)
    return (
        "Use the explicitly loaded Metering skill. You must use the bash tool to "
        "execute the command below exactly once; do not calculate the answer or "
        "write the receipt by another method. After it succeeds, answer with "
        "METERING_TOOL_OK.\n\n"
        f"python3 {str(INVOKER)!r} > {str(receipt)!r} <<'JSON'\n"
        f"{request}\n"
        "JSON"
    )


def _prime_prompt(receipt: Path) -> str:
    request = _canonical_json(REQUEST) + "\n"
    code = (
        "import pathlib, subprocess, sys\n"
        f"p = subprocess.run([sys.executable, {str(INVOKER)!r}], "
        f"input={request!r}, capture_output=True, text=True, check=True)\n"
        "assert p.stderr == ''\n"
        f"pathlib.Path({str(receipt)!r}).write_text(p.stdout, encoding='utf-8')\n"
        "print(p.stdout, end='')"
    )
    return (
        "Use the explicitly loaded Metering skill. You must use the ipython tool "
        "to execute the Python code below exactly once; do not calculate the "
        "answer or write the receipt by another method. After it succeeds, answer "
        "with METERING_TOOL_OK.\n\n"
        f"```python\n{code}\n```"
    )


def _version(
    prefix: list[str], environment: dict[str, str], cwd: Path, name: str
) -> str:
    result = _run(
        [*prefix, "--version"],
        cwd=cwd,
        environment=environment,
        timeout_seconds=30,
        name=name,
    )
    if result.returncode != 0:
        raise AcceptanceError(result.stderr.strip() or f"{name} --version failed")
    version = result.stdout.strip() or result.stderr.strip()
    if not version:
        raise AcceptanceError(f"{name} --version returned no version")
    return version


def _run_harness(
    harness: str,
    *,
    model: str,
    thinking: str,
    workspace: Path,
    timeout_seconds: int,
) -> dict[str, object]:
    if harness == "pi":
        name = "Pi"
        prefix = _command_prefix("METERING_PI_COMMAND", "PI_BIN", "pi")
        tool = "bash"
        receipt = workspace / "pi-metering.json"
        prompt = _pi_prompt(receipt)
        command = [
            *prefix,
            "--mode",
            "json",
            "--offline",
            "--model",
            model,
            "--thinking",
            thinking,
            "--no-session",
            "--no-skills",
            "--skill",
            str(SKILL),
            "--no-extensions",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
            "--tools",
            "read,bash",
            prompt,
        ]
    else:
        name = "Prime Agent"
        prefix = _command_prefix(
            "METERING_PRIME_AGENT_COMMAND",
            "PRIME_AGENT_BIN",
            "prime-agent",
        )
        tool = "ipython"
        receipt = workspace / "prime-agent-metering.json"
        prompt = _prime_prompt(receipt)
        command = [
            *prefix,
            "--mode",
            "json",
            "--offline",
            "--model",
            model,
            "--thinking",
            thinking,
            "--no-session",
            "--no-skills",
            "--skill",
            str(SKILL),
            "--no-extensions",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
            "--tools",
            "ipython",
            prompt,
        ]

    environment = {
        **os.environ,
        "PI_SKIP_VERSION_CHECK": "1",
        "PI_TELEMETRY": "0",
        "PRIME_AGENT_TELEMETRY": "0",
    }
    if harness == "pi":
        reviewed = os.environ.get("METERING_PI_CONFIG_DIR")
        if reviewed:
            configuration = Path(reviewed)
            if not configuration.is_absolute() or not configuration.is_dir():
                raise AcceptanceError(
                    "METERING_PI_CONFIG_DIR must name an existing absolute directory"
                )
        else:
            configuration = workspace / "pi-config"
            configuration.mkdir(exist_ok=True)
            source_name = os.environ.get("PI_CODING_AGENT_DIR")
            source = (
                Path(source_name).expanduser()
                if source_name
                else Path.home() / ".pi" / "agent"
            )
            source_file = source / "models.json"
            if source_file.is_file() and not source_file.is_symlink():
                target = configuration / "models.json"
                shutil.copyfile(source_file, target)
                target.chmod(0o600)
        environment["PI_CODING_AGENT_DIR"] = str(configuration)
    else:
        reviewed = os.environ.get("METERING_PRIME_AGENT_CONFIG_DIR")
        if reviewed:
            configuration = Path(reviewed)
            if not configuration.is_absolute() or not configuration.is_dir():
                raise AcceptanceError(
                    "METERING_PRIME_AGENT_CONFIG_DIR must name an existing "
                    "absolute directory"
                )
        else:
            configuration = workspace / "prime-agent-config"
            configuration.mkdir(exist_ok=True)
            source_name = os.environ.get("PRIME_AGENT_CODING_AGENT_DIR")
            source = (
                Path(source_name).expanduser()
                if source_name
                else Path.home() / ".prime" / "agent"
            )
            for filename in ("models.json",):
                source_file = source / filename
                if source_file.is_file() and not source_file.is_symlink():
                    target = configuration / filename
                    shutil.copyfile(source_file, target)
                    target.chmod(0o600)
        environment["PRIME_AGENT_CODING_AGENT_DIR"] = str(configuration)
    result = _run(
        command,
        cwd=workspace,
        environment=environment,
        timeout_seconds=timeout_seconds,
        name=name,
    )
    if result.returncode != 0:
        raise AcceptanceError(
            result.stderr.strip() or f"{name} exited with {result.returncode}"
        )
    if result.stderr:
        raise AcceptanceError(
            f"{name} wrote unexpected standard error: {result.stderr.strip()}"
        )
    events = _events(result.stdout, name)
    _verify_tool_event(events, tool, name)
    if not receipt.is_file():
        raise AcceptanceError(f"{name} did not create its Metering receipt")
    try:
        measured = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"{name} receipt is invalid: {exc}") from exc
    if measured != EXPECTED:
        raise AcceptanceError(f"{name} returned the wrong Metering result")
    if "METERING_TOOL_OK" not in _assistant_text(events):
        raise AcceptanceError(f"{name} did not acknowledge the completed tool call")
    return {
        "agent": harness,
        "metering_response": measured,
        "model": model,
        "tool": tool,
        "version": _version(prefix, environment, workspace, name),
    }


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Require real Pi and Prime Agent CLIs to call Metering."
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("METERING_LIVE_AGENT_MODEL"),
        help="model selector available to both harnesses",
    )
    parser.add_argument(
        "--thinking",
        default=os.environ.get("METERING_LIVE_AGENT_THINKING", "low"),
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    arguments = parser.parse_args(argv)
    if not arguments.model:
        parser.error("--model or METERING_LIVE_AGENT_MODEL is required")
    if arguments.timeout_seconds < 1:
        parser.error("--timeout-seconds must be positive")
    return arguments


def main(argv: list[str] | None = None) -> int:
    arguments = _arguments(sys.argv[1:] if argv is None else argv)
    try:
        with tempfile.TemporaryDirectory(prefix="metering-agent-acceptance-") as temp:
            workspace = Path(temp)
            agents = [
                _run_harness(
                    harness,
                    model=arguments.model,
                    thinking=arguments.thinking,
                    workspace=workspace,
                    timeout_seconds=arguments.timeout_seconds,
                )
                for harness in ("pi", "prime-agent")
            ]
    except AcceptanceError as exc:
        print(_canonical_json({"error": str(exc)}), file=sys.stderr)
        return 2
    print(
        _canonical_json(
            {
                "agents": agents,
                "schema_version": 1,
                "status": "accepted",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
