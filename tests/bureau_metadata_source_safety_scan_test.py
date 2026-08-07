from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path
from typing import Iterable, Iterator


ROOT = Path(__file__).resolve().parents[1]

_BUREAU_MODULE_ROOT = ROOT / "server" / "bureau_metadata"
_BUREAU_SCRIPT_GLOB = "*bureau_metadata*.py"
_AUTHENTICATED_ROUTERS = frozenset(
    {
        "server/bureau_metadata/catalog_router.py",
        "server/bureau_metadata/catalog_binding_router.py",
        "server/bureau_metadata/crosswalk_router.py",
    }
)
_AUTHENTICATED_DEPENDENCY_FACTORIES = frozenset(
    {"require_user", "get_crosswalk_router_runtime"}
)

_LIVE_ID_LITERALS = {
    "atlas-mrzpau4t",
    "ds_heloc_train_6bdb184b_05905",
    "v_1785186305905_6bdb184b",
}
_VENDOR_SOURCE_FILENAMES = {
    "experian_premier_credit_bureau.pdf",
    "credit_bureau_premier.csv",
}
_CATALOG_ARTIFACT_FILENAMES = {
    "catalog_manifest.json",
    "attribute_definitions.jsonl",
    "special_value_definitions.jsonl",
    "reconciliation_findings.jsonl",
    "lookup_index.json",
    "catalog_validation_summary.json",
    "catalog_build_log.json",
}
_RESTRICTED_SOURCE_SUFFIXES = {
    ".pdf",
    ".csv",
    ".jsonl",
    ".parquet",
    ".xlsx",
    ".xls",
    ".pkl",
    ".pickle",
    ".joblib",
    ".feather",
    ".arrow",
}

_LIVE_PROJECT_ID = re.compile(r"\batlas-[a-z0-9]{8,}\b", re.IGNORECASE)
_LIVE_DATASET_ID = re.compile(r"\bds_[a-z0-9_]+_[0-9]{5,}\b", re.IGNORECASE)
_LIVE_VERSION_ID = re.compile(r"\bv_[0-9]{10,}_[a-f0-9]{8,}\b", re.IGNORECASE)
_WINDOWS_HOST_PATH = re.compile(r"(?i)(?:^|\s)[a-z]:[\\/](?:users|documents and settings)[\\/]")
_POSIX_HOST_PATH = re.compile(r"(?i)(?:^|\s)/(?:home|users|tmp)/")

_ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "api_route", "websocket"}
_PUBLIC_CATALOG_OPERATIONS = {
    "download_catalog",
    "download_full_catalog",
    "export_catalog",
    "export_full_catalog",
    "get_full_catalog",
    "list_catalogs",
    "serve_catalog",
    "stream_catalog",
}
_FALLBACK_IDENTIFIERS = {
    "catalogs_first",
    "find_latest_catalog",
    "first_catalog",
    "first_catalog_version",
    "get_first_catalog",
    "get_latest_catalog",
    "latest_catalog",
    "latest_catalog_version",
    "list_catalogs",
    "load_first",
    "load_first_catalog",
    "load_latest",
    "load_latest_catalog",
    "resolve_first_catalog",
    "resolve_latest_catalog",
    "select_first_catalog",
    "select_latest_catalog",
}
_CATALOG_COLLECTION_NAMES = {
    "catalog_candidates",
    "catalog_directories",
    "catalog_versions",
    "catalogs",
    "manifest_candidates",
    "manifests",
}
_LOG_SINK_METHODS = {
    "critical",
    "debug",
    "error",
    "exception",
    "info",
    "log",
    "warning",
}
_SENSITIVE_IDENTIFIER = re.compile(
    r"(?:^|_)(?:api_?key|auth(?:entication|orization)?_?header|cookie|credential|"
    r"database_?url|dsn|password|passwd|secret|session_?token|token)(?:$|_)",
    re.IGNORECASE,
)


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _bureau_source_paths() -> tuple[Path, ...]:
    module_paths = sorted(_BUREAU_MODULE_ROOT.glob("*.py"))
    script_paths = sorted((ROOT / "scripts").glob(_BUREAU_SCRIPT_GLOB))
    return tuple(module_paths + script_paths)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=_relative(path))


def _docstring_nodes(tree: ast.AST) -> set[int]:
    nodes: set[int] = set()
    for owner in ast.walk(tree):
        if not isinstance(owner, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = owner.body
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            nodes.add(id(value))
    return nodes


def _negative_assertion_string_nodes(tree: ast.AST) -> set[int]:
    """Ignore strings that only assert that a forbidden capability is absent."""

    nodes: set[int] = set()
    for assertion in (node for node in ast.walk(tree) if isinstance(node, ast.Assert)):
        test = assertion.test
        negative = isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
        if isinstance(test, ast.Compare):
            negative = negative or any(
                isinstance(operator, (ast.NotIn, ast.IsNot))
                for operator in test.ops
            )
        if negative:
            nodes.update(
                id(node)
                for node in ast.walk(test)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            )
    return nodes


def _executable_strings(tree: ast.AST) -> Iterator[str]:
    ignored = _docstring_nodes(tree) | _negative_assertion_string_nodes(tree)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in ignored
        ):
            yield node.value


def _call_parts(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (*_call_parts(node.value), node.attr)
    return ()


def _identifier_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def _module_assignments(statements: Iterable[ast.stmt]) -> Iterator[tuple[str, ast.AST]]:
    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(statement, ast.Assign):
            names = [target.id for target in statement.targets if isinstance(target, ast.Name)]
            for name in names:
                yield name, statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            if statement.value is not None:
                yield statement.target.id, statement.value
        nested: list[ast.stmt] = []
        for field in ("body", "orelse", "finalbody"):
            value = getattr(statement, field, None)
            if isinstance(value, list):
                nested.extend(item for item in value if isinstance(item, ast.stmt))
        handlers = getattr(statement, "handlers", None)
        if isinstance(handlers, list):
            for handler in handlers:
                nested.extend(getattr(handler, "body", ()))
        if nested:
            yield from _module_assignments(nested)


def _numeric_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return True
        if isinstance(node.value, str):
            return bool(re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", node.value.strip()))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _numeric_literal(node.operand)
    return False


def _meaning_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and bool(node.value.strip())


def _numeric_meaning_pairs(node: ast.AST) -> int:
    if isinstance(node, ast.Call) and _call_parts(node.func)[-1:] == ("MappingProxyType",):
        return max((_numeric_meaning_pairs(argument) for argument in node.args), default=0)
    if isinstance(node, ast.Dict):
        return sum(
            1
            for key, value in zip(node.keys, node.values)
            if key is not None and _numeric_literal(key) and _meaning_literal(value)
        )
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return sum(
            1
            for item in node.elts
            if isinstance(item, (ast.Tuple, ast.List))
            and len(item.elts) == 2
            and _numeric_literal(item.elts[0])
            and _meaning_literal(item.elts[1])
        )
    return 0


def _contains_environment_value(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Subscript) and _call_parts(child.value)[-2:] == ("os", "environ"):
            return True
        if isinstance(child, ast.Name) and child.id.casefold() in {"environ", "environment"}:
            return True
        if isinstance(child, ast.Call):
            name = _call_parts(child.func)[-1:] or ("",)
            if name[0].casefold() in {"getenv", "load_dotenv", "dotenv_values"}:
                return True
    return False


def _contains_sensitive_reference(node: ast.AST) -> bool:
    return any(_SENSITIVE_IDENTIFIER.search(name) for name in _identifier_names(node))


def _contains_unsafe_exception_payload(node: ast.AST) -> bool:
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "__name__"
        and isinstance(node.value, ast.Call)
        and _call_parts(node.value.func)[-1:] == ("type",)
    ):
        return False
    if isinstance(node, ast.Name) and node.id.casefold() in {"exc", "exception"}:
        return True
    return any(_contains_unsafe_exception_payload(child) for child in ast.iter_child_nodes(node))


def _contains_bulk_runtime_namespace(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id.casefold() in {
            "args",
            "argv",
            "config",
            "environment",
            "settings",
        }:
            return True
        if isinstance(child, ast.Call) and _call_parts(child.func)[-1:] in {
            ("globals",),
            ("locals",),
            ("vars",),
        }:
            return True
    return False


def _is_log_sink(call: ast.Call) -> bool:
    parts = _call_parts(call.func)
    if parts == ("print",):
        return True
    return len(parts) >= 2 and parts[-1].casefold() in _LOG_SINK_METHODS


class BureauMetadataSourceSafetyScanTest(unittest.TestCase):
    """Static deny guards for the reusable restricted-catalog foundation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = _bureau_source_paths()
        if not cls.paths:
            raise AssertionError("Bureau metadata source-scan scope is empty.")
        cls.trees = {path: _parse(path) for path in cls.paths}

    def test_scan_scope_is_explicit_complete_and_parseable(self) -> None:
        expected_scripts = {
            "scripts/build_bureau_metadata_catalog.py",
            "scripts/build_bureau_metadata_crosswalk.py",
            "scripts/install_bureau_metadata_catalog.py",
            "scripts/run_bureau_metadata_operational_soak.py",
            "scripts/validate_bureau_metadata_catalog.py",
        }
        scanned = {_relative(path) for path in self.paths}
        self.assertTrue(expected_scripts.issubset(scanned))
        self.assertEqual(
            {path.name for path in _BUREAU_MODULE_ROOT.glob("*.py")},
            {path.name for path in self.paths if path.parent == _BUREAU_MODULE_ROOT},
        )
        self.assertEqual(set(self.paths), set(self.trees))

    def test_no_hardcoded_live_identity_vendor_source_or_host_path(self) -> None:
        findings: list[str] = []
        for path, tree in self.trees.items():
            for value in _executable_strings(tree):
                folded = value.casefold()
                if any(literal in folded for literal in _LIVE_ID_LITERALS):
                    findings.append(f"{_relative(path)}: live identity literal")
                if any(filename in folded for filename in _VENDOR_SOURCE_FILENAMES):
                    findings.append(f"{_relative(path)}: vendor source filename")
                if (
                    _LIVE_PROJECT_ID.search(value)
                    or _LIVE_DATASET_ID.search(value)
                    or _LIVE_VERSION_ID.search(value)
                ):
                    findings.append(f"{_relative(path)}: live-shaped identity literal")
                if _WINDOWS_HOST_PATH.search(value) or _POSIX_HOST_PATH.search(value):
                    findings.append(f"{_relative(path)}: host-specific external path")
        self.assertEqual(findings, [])

    def test_only_the_authenticated_bounded_router_is_present_and_no_bulk_surface_exists(self) -> None:
        findings: list[str] = []
        for path, tree in self.trees.items():
            relative = _relative(path)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "fastapi":
                    if any(alias.name == "APIRouter" for alias in node.names):
                        if relative not in _AUTHENTICATED_ROUTERS:
                            findings.append(f"{relative}: imports FastAPI APIRouter")
                elif isinstance(node, ast.Call):
                    parts = _call_parts(node.func)
                    if parts[-1:] == ("APIRouter",):
                        if relative not in _AUTHENTICATED_ROUTERS:
                            findings.append(f"{relative}: constructs APIRouter")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    function_name = node.name.casefold()
                    if function_name in _PUBLIC_CATALOG_OPERATIONS or (
                        "catalog" in function_name
                        and any(
                            token in function_name
                            for token in ("download", "export", "full_catalog", "serve", "stream")
                        )
                    ):
                        findings.append(f"{relative}: public-catalog operation {node.name}")
                    for decorator in node.decorator_list:
                        if not isinstance(decorator, ast.Call):
                            continue
                        parts = _call_parts(decorator.func)
                        if len(parts) >= 2 and parts[-1].casefold() in _ROUTE_METHODS:
                            if relative not in _AUTHENTICATED_ROUTERS:
                                findings.append(f"{relative}: HTTP route decorator on {node.name}")
                                continue
                            has_authenticated_dependency = any(
                                isinstance(call, ast.Call)
                                and _call_parts(call.func)[-1:] == ("Depends",)
                                and bool(call.args)
                                and _call_parts(call.args[0])[-1:]
                                and _call_parts(call.args[0])[-1]
                                in _AUTHENTICATED_DEPENDENCY_FACTORIES
                                for call in ast.walk(node)
                            )
                            if not has_authenticated_dependency:
                                findings.append(
                                    f"{relative}: unauthenticated route {node.name}"
                                )
            for value in _executable_strings(tree):
                folded = value.casefold()
                if (
                    "/" in folded
                    and "catalog" in folded
                    and any(token in folded for token in ("download", "export", "full"))
                ):
                    findings.append(f"{relative}: full-catalog route literal")
        self.assertEqual(findings, [])

    def test_no_first_or_latest_catalog_fallback_selector(self) -> None:
        findings: list[str] = []
        for path, tree in self.trees.items():
            relative = _relative(path)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.casefold() in _FALLBACK_IDENTIFIERS:
                        findings.append(f"{relative}: fallback function {node.name}")
                elif isinstance(node, ast.Call):
                    parts = _call_parts(node.func)
                    if parts and parts[-1].casefold() in _FALLBACK_IDENTIFIERS:
                        findings.append(f"{relative}: fallback call {parts[-1]}")
                elif isinstance(node, ast.Subscript):
                    names = {name.casefold() for name in _identifier_names(node.value)}
                    if not names.intersection(_CATALOG_COLLECTION_NAMES):
                        continue
                    index = node.slice
                    is_first = isinstance(index, ast.Constant) and index.value == 0
                    is_last = (
                        isinstance(index, ast.UnaryOp)
                        and isinstance(index.op, ast.USub)
                        and isinstance(index.operand, ast.Constant)
                        and index.operand.value == 1
                    )
                    if is_first or is_last:
                        findings.append(f"{relative}: positional catalog fallback")
        self.assertEqual(findings, [])

    def test_no_global_numeric_code_meaning_map(self) -> None:
        findings: list[str] = []
        for path, tree in self.trees.items():
            for name, value in _module_assignments(tree.body):
                if _numeric_meaning_pairs(value) >= 2:
                    findings.append(
                        f"{_relative(path)}: module-level numeric meaning map {name}"
                    )
                if isinstance(value, ast.DictComp) and re.search(
                    r"(?:code|meaning|sentinel|special|value)", name, re.IGNORECASE
                ):
                    findings.append(
                        f"{_relative(path)}: generated module-level meaning map {name}"
                    )
        self.assertEqual(findings, [])

    def test_no_source_document_or_catalog_artifact_in_code_or_frontend_paths(self) -> None:
        findings: list[str] = []
        protected_roots = (
            ROOT / "src",
            ROOT / "public",
            ROOT / "server" / "bureau_metadata",
            ROOT / "scripts",
        )
        for protected_root in protected_roots:
            if not protected_root.is_dir():
                continue
            for path in protected_root.rglob("*"):
                if not path.is_file():
                    continue
                name = path.name.casefold()
                if name in _VENDOR_SOURCE_FILENAMES or name in _CATALOG_ARTIFACT_FILENAMES:
                    findings.append(_relative(path))
                    continue
                if (
                    path.suffix.casefold() in _RESTRICTED_SOURCE_SUFFIXES
                    and "bureau_metadata" in path.as_posix().casefold()
                ):
                    findings.append(_relative(path))
        self.assertEqual(findings, [])

    def test_no_secret_environment_or_raw_exception_logging_pattern(self) -> None:
        findings: list[str] = []
        for path, tree in self.trees.items():
            for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
                if not _is_log_sink(call):
                    continue
                parts = _call_parts(call.func)
                if parts and parts[-1].casefold() == "exception":
                    findings.append(f"{_relative(path)}: exception logger")
                    continue
                payloads = [*call.args, *(keyword.value for keyword in call.keywords)]
                if any(
                    _contains_environment_value(payload)
                    or _contains_sensitive_reference(payload)
                    or _contains_unsafe_exception_payload(payload)
                    or _contains_bulk_runtime_namespace(payload)
                    for payload in payloads
                ):
                    findings.append(f"{_relative(path)}: unsafe logging payload")
        self.assertEqual(findings, [])

    def test_scanner_allows_safe_negative_assertions_comments_and_docstrings(self) -> None:
        synthetic = ast.parse(
            '''"""No APIRouter, full-catalog export, or latest fallback is allowed."""
# C:\\Users\\example\\restricted\\source.pdf must never be embedded.
assert not hasattr(service, "load_latest")
assert "APIRouter" not in source
DENY_PUBLIC_EXPORT = True
'''
        )
        self.assertEqual(list(_executable_strings(synthetic)), [])
        self.assertEqual(
            [
                name
                for name, value in _module_assignments(synthetic.body)
                if _numeric_meaning_pairs(value) >= 2
            ],
            [],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
