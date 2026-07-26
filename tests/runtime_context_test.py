"""Python runtime-context serialization safety.

Defect under repair: the generated execution prelude pasted `json.dumps()`
output straight into Python source, so a single missing dataset cell produced

    ATLAS_CONTEXT = {"previewRows": [{"Amount": null}], ...}
    NameError: name 'null' is not defined

before the user's program ran. Context is now normalized, serialized once, and
embedded as a repr()-quoted string literal parsed with json.loads().
"""
from __future__ import annotations

import datetime
import json
import math
import sys
from pathlib import Path

import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.code_execution.runtime_context import (  # noqa: E402
    RuntimeContextError,
    build_context_assignment,
    embed_json_literal,
    normalize_runtime_context,
    normalize_runtime_value,
)


def roundtrip(value):
    """Executes the generated assignment and returns what the sandbox would see."""
    source = "import json\n" + build_context_assignment("VALUE", value)
    namespace: dict = {}
    exec(compile(source, "<prelude>", "exec"), namespace)  # noqa: S102 - this is the code under test
    return namespace["VALUE"]


# --- The exact reported failure -------------------------------------------

def test_json_null_becomes_python_none():
    """The live failure: a null dataset cell must not emit bare `null`."""
    context = {"previewRows": [{"Time": 0, "Amount": None}]}
    source = "import json\n" + build_context_assignment("ATLAS_CONTEXT", normalize_runtime_context(context)[0])
    assert "null" not in source.split("json.loads(")[0], "no bare JSON null may reach Python source"
    assert roundtrip(normalize_runtime_context(context)[0]) == context


def test_json_booleans_execute_correctly():
    value = {"a": True, "b": False, "nested": [True, False, None]}
    assert roundtrip(value) == value
    restored = roundtrip(value)
    assert restored["a"] is True and restored["b"] is False


def test_the_old_direct_json_embedding_would_have_failed():
    """Documents the defect: raw json.dumps in source is not valid Python."""
    bad_source = "ATLAS_CONTEXT = " + json.dumps({"Amount": None})
    try:
        exec(compile(bad_source, "<bad>", "exec"), {})  # noqa: S102
        raise AssertionError("raw JSON embedding should have raised NameError")
    except NameError:
        pass


# --- Part F test matrix ----------------------------------------------------

ROUND_TRIP_VALUES = [
        None,
        True,
        False,
        "",
        0,
        -17,
        3.5,
        'double "quoted" text',
        "apostrophe's text",
        "line one\nline two",
        "back\\slash and \\\\double",
        "unicode: café — 日本語 — ✓",
        "tab\there",
        {"nested": {"deeper": {"deepest": [1, {"x": None}]}}},
        [[1, 2], [3, [4, [5]]]],
        {"dataset name with spaces": "CLASS TRAIN v2"},
        {"project": "Fraud (2026) — Q1 'pilot'"},
        {"optional": None, "present": "yes"},
        [],
        {},
    ]


def test_context_values_round_trip_exactly(case):
    assert roundtrip(normalize_runtime_value(case)) == case


def test_malicious_looking_strings_remain_inert_text():
    """Context values must not be able to escape their literal or inject code."""
    hostile = {
        "a": "'); import os; os.system('calc'); ('",
        "b": '"""; __import__("os").system("calc"); """',
        "c": "\\'); print('escaped",
        "d": "') if False else exec('print(1)') #",
        "e": "\n__import__('os').system('calc')\n",
    }
    marker: dict = {}
    source = "import json\n" + build_context_assignment("VALUE", normalize_runtime_value(hostile))
    exec(compile(source, "<prelude>", "exec"), marker)  # noqa: S102
    # Every value survives as inert text, byte for byte.
    assert marker["VALUE"] == hostile
    # And the payload is a single quoted string argument to json.loads.
    assert source.count("json.loads(") == 1


def test_datetime_and_path_values_are_normalized():
    normalized = normalize_runtime_value(
        {
            "when": datetime.datetime(2026, 7, 25, 13, 45, 30),
            "day": datetime.date(2026, 7, 25),
            "artifact": Path("C:/Users/james/ds-workflow-starter/server/artifacts/secret/data_full.csv"),
        }
    )
    assert normalized["when"] == "2026-07-25T13:45:30"
    assert normalized["day"] == "2026-07-25"
    # A server artifact tree must never travel into runtime context.
    assert normalized["artifact"] == "data_full.csv"
    assert "artifacts" not in normalized["artifact"]
    assert roundtrip(normalized) == normalized


def test_numpy_scalars_become_native_python_values():
    import numpy
    normalized = normalize_runtime_value(
        {"i": numpy.int64(7), "f": numpy.float64(1.5), "b": numpy.bool_(True), "s": numpy.str_("text")}
    )
    assert normalized == {"i": 7, "f": 1.5, "b": True, "s": "text"}
    assert roundtrip(normalized) == normalized


def test_non_finite_floats_are_converted_and_recorded():
    conversions: list[str] = []
    normalized = normalize_runtime_value(
        {"nan": float("nan"), "inf": math.inf, "ninf": -math.inf}, conversions=conversions
    )
    assert normalized == {"nan": None, "inf": None, "ninf": None}
    assert len(conversions) == 3, "each lossy conversion must be recorded"
    assert all("non-finite" in note for note in conversions)
    assert roundtrip(normalized) == normalized


def test_unsupported_objects_are_recorded_not_silently_stringified():
    class Custom:
        def __repr__(self) -> str:
            return "<Custom>"

    conversions: list[str] = []
    normalized = normalize_runtime_value({"obj": Custom()}, conversions=conversions)
    assert isinstance(normalized["obj"], str)
    assert conversions, "an object conversion must be recorded"
    assert "Custom converted to string" in conversions[0]


def test_excessive_nesting_is_rejected_rather_than_emitting_broken_source():
    deep: dict = {}
    cursor = deep
    for _ in range(60):
        cursor["next"] = {}
        cursor = cursor["next"]
    try:
        normalize_runtime_context(deep)
        raise AssertionError("excessive nesting should be rejected")
    except RuntimeContextError:
        pass


def test_non_mapping_context_is_rejected():
    try:
        normalize_runtime_context(["not", "a", "mapping"])
        raise AssertionError("a non-mapping context should be rejected")
    except RuntimeContextError:
        pass


def test_embedded_payload_is_a_quoted_string_literal():
    """The payload must be a string literal, never inlined Python structure."""
    expression = embed_json_literal({"a": None, "b": True})
    assert expression.startswith("json.loads(")
    inner = expression[len("json.loads(") : -1]
    # repr() of a str always yields a quoted literal.
    assert inner[0] in {"'", '"'}
    assert eval(inner) == '{"a": null, "b": true}'  # noqa: S307 - asserting the literal's value


# --- Prelude integration ---------------------------------------------------

def test_generated_prelude_compiles_for_both_source_branches():
    from server.code_execution.dataset_binding import BoundDataset, build_runtime_prelude

    context = {
        "previewRows": [{"Time": 0, "Amount": None, "Flag": True, "Note": "it's \"fine\"\n"}],
        "datasetName": "CLASS TRAIN",
        "target": "Class",
        "selectedFeatures": ["Time"],
    }

    bound = BoundDataset("ds", "v1", "CLASS_TRAIN", Path("x.csv"), "csv", 10, "Class", ["Time"])
    registered = build_runtime_prelude(bound, Path("atlas_dataset.csv"), context=context)
    compile(registered, "<registered>", "exec")

    preview = build_runtime_prelude(None, None, preview_rows=context["previewRows"], context=context)
    compile(preview, "<preview>", "exec")

    for source in (registered, preview):
        assert "= null" not in source and "= true" not in source and "= false" not in source


def test_runtime_objects_are_defined_by_the_preview_prelude():
    from server.code_execution.dataset_binding import build_runtime_prelude

    source = build_runtime_prelude(
        None,
        None,
        preview_rows=[{"a": 1, "b": None}],
        target="a",
        selected_features=["b"],
        context={"datasetName": "X", "previewRows": [{"a": 1, "b": None}]},
    )
    namespace: dict = {}
    exec(compile(source, "<prelude>", "exec"), namespace)  # noqa: S102
    for name in ("df", "TARGET", "SELECTED_FEATURES", "ATLAS_DATASET_PATH", "ATLAS_CONTEXT"):
        assert name in namespace, f"runtime object missing: {name}"
    assert namespace["TARGET"] == "a"
    assert namespace["SELECTED_FEATURES"] == ["b"]
    assert len(namespace["df"]) == 1
    # Legacy aliases still resolve for previously-saved user code.
    for legacy in ("preview_rows", "dataset_name", "version_id"):
        assert legacy in namespace


class RuntimeContextTests(unittest.TestCase):
    """Adapter so this file runs under the repository's unittest convention."""

    def test_all(self):
        checks = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
        # Guard against the adapter silently running nothing.
        self.assertGreaterEqual(len(checks), 12, "expected the full runtime-context matrix to be collected")
        executed = 0
        for check in checks:
            if check is self.test_all:
                continue
            if check.__name__ == "test_context_values_round_trip_exactly":
                for index, case in enumerate(ROUND_TRIP_VALUES):
                    with self.subTest(check=check.__name__, case=index):
                        check(case)
                        executed += 1
                continue
            with self.subTest(check=check.__name__):
                check()
                executed += 1
        print(f"  [runtime-context] {executed} checks executed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
