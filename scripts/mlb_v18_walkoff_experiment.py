"""One source-bound, private terminal-credit sensitivity; never a rules fix.

The observed non-HR terminal transition first giving the home team a lead is
credited only the runs needed to take that lead. Every HOME_RUN keeps its full
sampled credit: V18 cannot distinguish over-fence from inside-park home runs.
Runner touches, appeals, awards and third-out timing are not retained, so this
is deliberately an experimental scoring convention, not certified baseball
adjudication. No transition, PA, pitcher hook, RNG draw or winner is changed.

Raw trajectory events remain raw. One annotated insertion, after trajectories
terminate and before aggregation, applies the terminal-event credit. This is
equivalent to changing credit at that event because the draw has no later PA;
it avoids falsely imposing runner conservation on a truncated scoring credit.
"""

from __future__ import annotations

import ast
import copy
import difflib
import hashlib
import inspect
from pathlib import Path
from typing import Any, Callable

import numpy as np


BASELINE_SOURCE_SHA256 = "dc423012278709e7da2c85aeec6b81974db721c6d01c0c802ab83630499dd288"
VARIANT_ID = "NON_HR_TERMINAL_CREDIT_SENSITIVITY_V1"
PRIVATE_SCHEMA = "MLB_V18_PRIVATE_TERMINAL_CREDIT_SENSITIVITY_V1"
_MARKER = "    nonterminated = int((~terminal).sum())\n"
_INSERTION = (
    "    # PRIVATE SENSITIVITY: trajectories and events above remain raw and unchanged.\n"
    "    # Credit only the observed non-HR terminal runs needed for the lead.\n"
    "    home_score = _terminal_credit_context.apply(away_score, home_score, terminal)\n"
    "\n"
)


class TerminalCreditError(ValueError):
    """A binding or terminal-trajectory inconsistency must fail closed."""


class TerminalCreditContext:
    """Observe raw events without mutating them, then apply one terminal credit."""

    def __init__(self, n_sims: int, regulation: int = 9, observer: Any = None):
        if n_sims <= 0 or regulation <= 0:
            raise TerminalCreditError("positive population and regulation required")
        self.n_sims = int(n_sims)
        self.regulation = int(regulation)
        self.observer = observer
        self.walkoffs: dict[int, dict[str, Any]] = {}
        self.summary: dict[str, Any] | None = None

    def observe(self, simulation: int, event: dict[str, Any]) -> None:
        simulation = int(simulation)
        if not 0 <= simulation < self.n_sims:
            raise TerminalCreditError("simulation outside population")
        if simulation in self.walkoffs:
            raise TerminalCreditError("event after a retained terminal walkoff")
        if (
            event["half"] == "BOTTOM"
            and int(event["inning"]) >= self.regulation
            and int(event["homeScoreAfter"]) > int(event["awayScoreAfter"])
        ):
            raw_runs = int(event["runsScored"])
            before = int(event["homeScoreAfter"]) - raw_runs
            needed = int(event["awayScoreAfter"]) - before + 1
            if not 1 <= needed <= raw_runs:
                raise TerminalCreditError("event is not a first lead-taking transition")
            credit = raw_runs if event["outcome"] == "HOME_RUN" else needed
            self.walkoffs[simulation] = {
                "simulationIndex": simulation,
                "rawEvent": copy.deepcopy(event),
                "rawTransition": [
                    int(event["outsAfter"]) - int(event["outsBefore"]),
                    int(event["baseMaskAfter"]),
                    raw_runs,
                ],
                "rawTerminalRuns": raw_runs,
                "runsNeededForLead": needed,
                "terminalRunsCredited": credit,
                "terminalCreditReduction": raw_runs - credit,
            }
        if self.observer is not None:
            self.observer(simulation, event)

    def apply(self, away: np.ndarray, home: np.ndarray, terminal: np.ndarray) -> np.ndarray:
        if self.summary is not None:
            raise TerminalCreditError("terminal credit already applied")
        away = np.asarray(away)
        home = np.asarray(home)
        terminal = np.asarray(terminal)
        if any(value.shape != (self.n_sims,) for value in (away, home, terminal)):
            raise TerminalCreditError("population shape mismatch")
        if not np.issubdtype(away.dtype, np.integer) or not np.issubdtype(home.dtype, np.integer):
            raise TerminalCreditError("integer raw population required")
        reduction = np.zeros(self.n_sims, dtype=np.int64)
        for simulation, retained in self.walkoffs.items():
            event = retained["rawEvent"]
            if (
                not bool(terminal[simulation])
                or int(away[simulation]) != int(event["awayScoreAfter"])
                or int(home[simulation]) != int(event["homeScoreAfter"])
            ):
                raise TerminalCreditError("raw final scores do not match terminal event")
            reduction[simulation] = retained["terminalCreditReduction"]
        candidate = home.copy() - reduction
        if not np.array_equal(home > away, candidate > away):
            raise TerminalCreditError("winner changed by terminal credit")
        if not np.array_equal(home == away, candidate == away):
            raise TerminalCreditError("tie state changed by terminal credit")
        self.summary = {
            "variantId": VARIANT_ID,
            "status": "PRIVATE_SENSITIVITY_NOT_CERTIFIED_RULES_FIX",
            "traceSemantics": "UNCHANGED_RAW_SAMPLED_TRANSITIONS_AND_RAW_SCORE_PATH",
            "rawAwayRuns": away.copy(),
            "rawHomeRuns": home.copy(),
            "terminalCreditReduction": reduction,
            "walkoffCount": len(self.walkoffs),
            "nonHomeRunWalkoffCount": sum(
                item["rawEvent"]["outcome"] != "HOME_RUN" for item in self.walkoffs.values()
            ),
            "changedSimulationCount": int((reduction > 0).sum()),
            "totalTerminalCreditReduction": int(reduction.sum()),
            "rawTerminalEvents": [self.walkoffs[key] for key in sorted(self.walkoffs)],
            "homeRunLimitation": "All HOME_RUN credit preserved; over-fence/inside-park detail absent.",
            "unresolvedRuleDetails": "Runner touches, appeals, awards and third-out timing absent.",
        }
        return candidate


def _bound_function_source(core: Any) -> tuple[str, dict[str, Any]]:
    path = Path(core.__file__).resolve()
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != BASELINE_SOURCE_SHA256:
        raise TerminalCreditError(f"baseline physical source binding mismatch: {digest}")
    source = raw.decode("utf-8-sig").replace("\r\n", "\n")
    nodes = [
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "simulate_prospective_game"
    ]
    if len(nodes) != 1:
        raise TerminalCreditError("expected one top-level simulator")
    node = nodes[0]
    original = "".join(source.splitlines(keepends=True)[node.lineno - 1:node.end_lineno])
    original = original.rstrip("\n") + "\n"
    loaded = inspect.getsource(core.simulate_prospective_game).replace("\r\n", "\n")
    if loaded.rstrip("\n") + "\n" != original:
        raise TerminalCreditError("loaded simulator source differs from bound source")
    if original.count(_MARKER) != 1:
        raise TerminalCreditError("terminal aggregation injection point changed")
    variant = original.replace(_MARKER, _INSERTION + _MARKER, 1)
    binding = {
        "variantId": VARIANT_ID,
        "baselineSourcePath": str(path),
        "baselineSourceSha256": digest,
        "baselineFunctionSha256": hashlib.sha256(original.encode()).hexdigest(),
        "variantFunctionSha256": hashlib.sha256(variant.encode()).hexdigest(),
        "insertionCount": 1,
        "insertion": _INSERTION,
        "annotatedDiff": "".join(difflib.unified_diff(
            original.splitlines(keepends=True), variant.splitlines(keepends=True),
            fromfile="bound_original/simulate_prospective_game",
            tofile="private_terminal_credit/simulate_prospective_game",
        )),
        "rngAndPathPolicy": "Unchanged engine loop; current core globals copied at each invocation.",
        "creditPolicy": "Only observed non-HOME_RUN first-lead terminal excess is removed.",
        "homeRunPolicy": "Preserve every HOME_RUN in full; subtype unavailable.",
        "authority": "Private sensitivity only; not a certified rules fix or production model.",
    }
    return variant, binding


def build_terminal_credit_simulator(core: Any) -> tuple[Callable[..., dict[str, Any]], dict[str, Any]]:
    """Return private simulator plus JSON-serializable exact source/diff binding.

    The private function resolves a fresh copy of ``core.__dict__`` at invocation
    time, so a caller's RNGStreamAudit(core) instruments those exact generators.
    This module never patches core or numpy. It neither fits nor runs on build.
    """
    variant, binding = _bound_function_source(core)
    code = compile(variant, "<private-source-bound-v18-terminal-credit>", "exec")

    def simulator(**kwargs: Any) -> dict[str, Any]:
        # Recheck source at invocation; never silently run against edited baseline.
        current_variant, current_binding = _bound_function_source(core)
        if current_variant != variant or current_binding != binding:
            raise TerminalCreditError("baseline changed after variant construction")
        call_kwargs = dict(kwargs)
        context = TerminalCreditContext(
            n_sims=int(call_kwargs["n_sims"]),
            regulation=int(call_kwargs.get("regulation", 9)),
            observer=call_kwargs.get("event_observer"),
        )
        call_kwargs["event_observer"] = context.observe
        namespace = dict(core.__dict__)
        namespace["_terminal_credit_context"] = context
        exec(code, namespace)
        result = namespace["simulate_prospective_game"](**call_kwargs)
        if context.summary is None:
            raise TerminalCreditError("terminal credit insertion did not execute")
        result["baselineSchemaVersion"] = result["schemaVersion"]
        result["schemaVersion"] = PRIVATE_SCHEMA
        result["terminalCreditSensitivity"] = context.summary
        return result

    simulator.__name__ = "simulate_private_terminal_credit_sensitivity"
    return simulator, binding
