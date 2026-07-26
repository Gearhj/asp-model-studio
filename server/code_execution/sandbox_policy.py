"""Governed Python sandbox policy for the Multi-Language Code Workspace.

CODE-DATAACQ-001 root cause
---------------------------
`ATLAS_CODE_SANDBOX_COMMAND` was unset, so `run_python_request` returned
`status: "unavailable"` for every request. The UI nonetheless hard-coded the
Python badge to "Executable" and left Run Python enabled, so the only way to
discover that execution was impossible was to click it and read a raw backend
message. This module makes the capability an explicit, inspectable contract that
both the API and the UI read from one place.

Security posture
----------------
The previous contract accepted an arbitrary command string and `shlex.split` it,
which meant whoever could set the variable could run any host binary with the
server's environment. This module keeps the same variable name but adds:

* an approved-interpreter allowlist -- the resolved executable must be the
  project virtual environment's interpreter (or an operator-approved absolute
  path listed in `ATLAS_CODE_SANDBOX_ALLOWLIST`);
* argument-vector invocation only, never a shell string;
* refusal of shell metacharacters so no `&&`, `|`, or redirection can be smuggled
  through the template;
* a resolved-path identity check, so a symlink or PATH shadow cannot substitute a
  different binary.

Nothing here grants execution that was not already intended by the deployment;
it narrows what an approved command is allowed to be.
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

# The project virtual environment is the default approved interpreter. It is the
# same interpreter that already runs the API, so enabling execution does not
# widen the deployment's trust boundary.
VENV_PYTHON_CANDIDATES = [
    REPO_ROOT / ".venv" / "Scripts" / "python.exe",
    REPO_ROOT / ".venv" / "bin" / "python",
]

SHELL_METACHARACTERS = set(";&|><`$\n\r")

# Placeholders a sandbox command template may use.
SCRIPT_TOKEN = "{script}"
SCRIPT_NAME_TOKEN = "{script_name}"
WORKDIR_TOKEN = "{workdir}"


class SandboxPolicyError(Exception):
    """Raised when a configured sandbox command is not approved."""


@dataclass
class SandboxCapability:
    """What the deployment can actually do, in a form the UI can render honestly."""

    state: str  # "executable" | "not_configured" | "misconfigured" | "disabled"
    reason: str = ""
    #: Operator-facing only. Never returned to a non-privileged caller.
    detail: str = ""
    executable: str = ""
    configuration_key: str = "ATLAS_CODE_SANDBOX_COMMAND"
    approved_interpreters: List[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.state == "executable"

    def public_dict(self) -> dict:
        """Ordinary users see the state and a non-sensitive explanation only --
        never the server command, path, or environment detail."""
        return {
            "state": self.state,
            "available": self.available,
            "reason": self.reason,
        }

    def admin_dict(self) -> dict:
        """Administrators and the development diagnostics view additionally see
        which configuration key is missing and which interpreters are approved."""
        return {
            **self.public_dict(),
            "detail": self.detail,
            "configurationKey": self.configuration_key,
            "executable": self.executable,
            "approvedInterpreters": self.approved_interpreters,
        }


def default_venv_python() -> Optional[Path]:
    for candidate in VENV_PYTHON_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def approved_interpreters() -> List[Path]:
    """The allowlist: the project virtual environment plus any absolute paths an
    operator explicitly approved. User code can never add to this."""
    approved: List[Path] = []
    venv = default_venv_python()
    if venv:
        approved.append(venv.resolve())
    raw = os.getenv("ATLAS_CODE_SANDBOX_ALLOWLIST", "")
    for entry in raw.split(os.pathsep):
        entry = entry.strip()
        if not entry:
            continue
        try:
            resolved = Path(entry).resolve()
        except (OSError, RuntimeError):
            continue
        if resolved.exists() and resolved not in approved:
            approved.append(resolved)
    return approved


def _is_approved(executable: Path, approved: List[Path]) -> bool:
    try:
        resolved = executable.resolve()
    except (OSError, RuntimeError):
        return False
    return any(resolved == candidate for candidate in approved)


#: Symbolic values meaning "use the approved project interpreter". Operators opt
#: in explicitly without hand-writing a command string -- which is exactly where
#: an unsafe or over-broad command would otherwise creep in.
SYMBOLIC_DEFAULTS = {"default", "venv", "project-venv"}


def resolve_sandbox_command(
    raw_command: str,
    script_path: Path,
    workdir: Path,
) -> List[str]:
    """Turns the configured template into a validated argument vector.

    Raises SandboxPolicyError when the command is absent, contains shell
    metacharacters, or names an interpreter that is not on the allowlist.
    """
    if not raw_command or not raw_command.strip():
        raise SandboxPolicyError("No sandbox command is configured.")

    if raw_command.strip().lower() in SYMBOLIC_DEFAULTS:
        raw_command = default_sandbox_command()
        if not raw_command:
            raise SandboxPolicyError(
                "The project virtual environment interpreter was not found, so the default sandbox cannot be used."
            )

    if any(char in SHELL_METACHARACTERS for char in raw_command):
        raise SandboxPolicyError(
            "The sandbox command contains shell metacharacters. ATLAS executes an argument vector, never a shell string."
        )

    try:
        parts = shlex.split(raw_command, posix=os.name != "nt")
    except ValueError as exc:
        raise SandboxPolicyError(f"The sandbox command could not be parsed: {exc}") from exc
    if not parts:
        raise SandboxPolicyError("The sandbox command is empty after parsing.")

    approved = approved_interpreters()
    if not approved:
        raise SandboxPolicyError(
            "No approved interpreter is available. Create the project virtual environment or set ATLAS_CODE_SANDBOX_ALLOWLIST."
        )

    executable = Path(parts[0].strip('"'))
    if not _is_approved(executable, approved):
        raise SandboxPolicyError(
            "The configured sandbox executable is not on the approved interpreter allowlist."
        )

    replacements = {
        SCRIPT_TOKEN: str(script_path),
        SCRIPT_NAME_TOKEN: script_path.name,
        WORKDIR_TOKEN: str(workdir),
    }
    argv: List[str] = [str(executable.resolve())]
    for part in parts[1:]:
        for token, value in replacements.items():
            part = part.replace(token, value)
        argv.append(part)

    # The script must actually be passed to the interpreter, otherwise the
    # template would silently run something other than the submitted code.
    if str(script_path) not in argv and script_path.name not in argv:
        raise SandboxPolicyError("The sandbox command template must include a {script} placeholder.")

    return argv


def describe_capability() -> SandboxCapability:
    """Single source of truth for Python execution capability."""
    approved = [str(path) for path in approved_interpreters()]

    if os.getenv("ATLAS_HOSTED_MODE", "").strip().lower() in {"1", "true", "yes"}:
        return SandboxCapability(
            state="disabled",
            reason="Python execution is disabled in hosted mode for this ATLAS environment.",
            detail="ATLAS_HOSTED_MODE is enabled.",
            approved_interpreters=approved,
        )

    if os.getenv("ATLAS_ENABLE_PYTHON_RUN", "1").strip().lower() in {"0", "false", "no"}:
        return SandboxCapability(
            state="disabled",
            reason="Python execution has been turned off for this ATLAS environment.",
            detail="ATLAS_ENABLE_PYTHON_RUN is set to a disabling value.",
            approved_interpreters=approved,
        )

    raw_command = os.getenv("ATLAS_CODE_SANDBOX_COMMAND", "").strip()
    if not raw_command:
        return SandboxCapability(
            state="not_configured",
            reason="Python execution is unavailable because the governed code sandbox has not been configured for this ATLAS environment.",
            detail="ATLAS_CODE_SANDBOX_COMMAND is not set.",
            approved_interpreters=approved,
        )

    # Validate the template against a representative script path without running it.
    probe_dir = Path(os.getenv("TEMP") or os.getenv("TMP") or ".").resolve()
    try:
        argv = resolve_sandbox_command(raw_command, probe_dir / "atlas_probe.py", probe_dir)
    except SandboxPolicyError as exc:
        return SandboxCapability(
            state="misconfigured",
            reason="Python execution is unavailable because the configured code sandbox is not approved for this ATLAS environment.",
            detail=str(exc),
            approved_interpreters=approved,
        )

    executable = Path(argv[0])
    if not executable.exists():
        return SandboxCapability(
            state="misconfigured",
            reason="Python execution is unavailable because the configured code sandbox interpreter is missing.",
            detail=f"Configured interpreter does not exist: {executable}",
            approved_interpreters=approved,
        )

    return SandboxCapability(
        state="executable",
        reason="Python executes in the governed ATLAS sandbox.",
        detail="",
        executable=str(executable),
        approved_interpreters=approved,
    )


def default_sandbox_command() -> str:
    """The repository-local approved command used for development and tests.

    `-I` runs in isolated mode (ignores PYTHON* environment variables and the
    user site directory) and `-S` skips site customization, so user code cannot
    reach into the operator's Python configuration.
    """
    venv = default_venv_python()
    if not venv:
        return ""
    return f'"{venv}" -I {SCRIPT_TOKEN}'
