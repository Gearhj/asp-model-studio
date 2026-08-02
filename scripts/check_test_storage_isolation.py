"""Fail closed on Dataset Library test-storage isolation regressions.

This source guard intentionally runs without importing ATLAS server modules.
Dataset Library paths are cached during those imports, so importing application
code while checking import order would recreate the class of defect this guard
is designed to prevent.

Run:
    .venv/Scripts/python.exe scripts/check_test_storage_isolation.py
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from functools import lru_cache
import importlib.util
import os
from pathlib import Path
import re
import sys
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIVE_ROOT = (
    REPO_ROOT / "server" / "artifacts" / "datasets"
).resolve()
DATASET_ENVIRONMENT_KEY = "ATLAS_DATASET_LIBRARY_ROOT"
CHECKPOINT_ENVIRONMENT_KEY = "ATLAS_CHECKPOINT_PATH"
DEFAULT_LIVE_CHECKPOINT_PATH = (
    REPO_ROOT / ".runtime" / "workflow_checkpoint.json"
).resolve()
TEST_MODE_KEYS = frozenset({"ATLAS_TEST_MODE", "ATLAS_ENV"})
_CHECKPOINT_MUTATORS = frozenset(
    {
        "discard_modeling_scopes",
        "flush_checkpoint",
        "save_checkpoint",
        "schedule_checkpoint_save",
    }
)
_CHECKPOINT_FILE_MUTATORS = frozenset(
    {"replace", "unlink", "write_bytes", "write_text"}
)
_BASELINE_DATASET_MUTATORS = frozenset(
    {
        "add_dataset_version",
        "archive_dataset",
        "create_dataset_from_upload",
        "create_dataset_from_dataframe",
        "create_metadata_only_dataset",
        "ensure_store",
        "grant_dataset_access",
        "link_project",
        "revoke_dataset_access",
        "register_workspace_dataset",
        "save_users",
        "save_links",
        "save_registry",
        "share_dataset",
        "unlink_all_project_datasets",
        "unlink_project_dataset",
        "write_json",
        "write_version_manifest",
    }
)
_MUTATING_CALL_PRIMITIVES = frozenset(
    {
        "atomic_restore_json_bytes",
        "atomic_write_json",
        "create_backup_bundle",
        "mkdir",
        "prune_backup_bundles",
        "replace",
        "rmdir",
        "to_csv",
        "unlink",
        "write_bytes",
        "write_recovery_journal",
        "write_text",
    }
)
_MUTATING_HTTP_METHODS = frozenset({"post", "put", "patch", "delete"})
_ENDPOINT_PROPAGATING_MUTATORS = frozenset(
    {
        "add_dataset_version",
        "archive_dataset",
        "create_dataset_from_dataframe",
        "create_dataset_from_upload",
        "create_metadata_only_dataset",
        "grant_dataset_access",
        "link_project",
        "register_workspace_dataset",
        "revoke_dataset_access",
        "save_links",
        "save_registry",
        "share_dataset",
        "unlink_all_project_datasets",
        "unlink_project_dataset",
    }
)
REQUIRED_REBINDINGS = frozenset(
    {"ARTIFACT_ROOT", "REGISTRY_PATH", "USERS_PATH", "PROJECT_LINKS_PATH"}
)


@dataclass(frozen=True)
class IsolationViolation:
    path: Path
    line: int
    rule: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.rule} {self.message}"


def _mapping_assignments(tree: ast.AST) -> dict[str, ast.Dict]:
    mappings: dict[str, ast.Dict] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                mappings[target.id] = value
    return mappings


def _dict_value(mapping: ast.Dict, key: str) -> ast.expr | None:
    for item_key, item_value in zip(mapping.keys, mapping.values):
        if isinstance(item_key, ast.Constant) and item_key.value == key:
            return item_value
    return None


def _is_os_environ(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
        and node.attr == "environ"
    )


def _subscript_key(node: ast.Subscript) -> str | None:
    value = node.slice
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


@lru_cache(maxsize=None)
def _environment_writes(
    tree: ast.AST,
    key: str,
) -> list[tuple[int, ast.expr | None]]:
    """Return real writes to one environment key, including mapping updates."""

    mappings = _mapping_assignments(tree)
    writes: list[tuple[int, ast.expr | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if (
                    isinstance(target, ast.Subscript)
                    and _is_os_environ(target.value)
                    and _subscript_key(target) == key
                ):
                    writes.append((node.lineno, node.value))
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not _is_os_environ(node.func.value):
            continue
        if node.func.attr == "setdefault" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and first.value == key:
                value = node.args[1] if len(node.args) > 1 else None
                writes.append((node.lineno, value))
        if node.func.attr != "update" or not node.args:
            continue
        source = node.args[0]
        mapping = source if isinstance(source, ast.Dict) else None
        if isinstance(source, ast.Name):
            mapping = mappings.get(source.id)
        if mapping is not None:
            value = _dict_value(mapping, key)
            if value is not None:
                writes.append((node.lineno, value))
    return sorted(writes, key=lambda item: item[0])


@lru_cache(maxsize=None)
def _environment_setdefault_lines(tree: ast.AST, key: str) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setdefault"
            and _is_os_environ(node.func.value)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == key
        ):
            lines.add(node.lineno)
    return lines


def _server_import_lines(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "server" or alias.name.startswith("server.") for alias in node.names):
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "server" or module.startswith("server."):
                lines.append(node.lineno)
    return sorted(lines)


@lru_cache(maxsize=None)
def _function_nodes(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _called_attribute_name(call: ast.Call) -> str | None:
    function = call.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


def _discover_dataset_mutators(repo_root: Path = REPO_ROOT) -> frozenset[str]:
    """Derive registry mutators from the implementation's write call graph.

    ``ensure_store`` is itself reportable because it bootstraps authority files,
    but its edge is intentionally not propagated into read helpers.  That keeps
    ordinary reads out of scope while ensuring every public operation that
    reaches an actual JSON/artifact write is included automatically.
    """

    registry_path = repo_root / "server" / "datasets" / "dataset_registry.py"
    try:
        tree = ast.parse(
            registry_path.read_text(encoding="utf-8"),
            filename=str(registry_path),
        )
    except (OSError, SyntaxError, UnicodeError):
        return _BASELINE_DATASET_MUTATORS
    functions = {node.name: node for node in _function_nodes(tree)}
    local_calls: dict[str, set[str]] = {}
    direct_mutators: set[str] = set()
    for name, function in functions.items():
        called: set[str] = set()
        for child in ast.walk(function):
            if not isinstance(child, ast.Call):
                continue
            called_name = _called_attribute_name(child)
            if called_name:
                called.add(called_name)
            if called_name in _MUTATING_CALL_PRIMITIVES:
                direct_mutators.add(name)
        local_calls[name] = called
    direct_mutators.add("ensure_store")
    mutators = set(_BASELINE_DATASET_MUTATORS) | direct_mutators
    while True:
        propagating = mutators - {"ensure_store"}
        discovered = {
            name
            for name, called in local_calls.items()
            if called.intersection(propagating)
        }
        expanded = mutators | discovered
        if expanded == mutators:
            break
        mutators = expanded
    return frozenset(mutators)


DATASET_MUTATORS = _discover_dataset_mutators()


def _resolve_import_module(
    current_module: str,
    node: ast.ImportFrom,
    *,
    is_package: bool,
) -> str | None:
    if not node.level:
        return node.module
    package = current_module if is_package else current_module.rpartition(".")[0]
    try:
        return importlib.util.resolve_name(
            "." * node.level + (node.module or ""),
            package,
        )
    except (ImportError, ValueError):
        return None


def _module_name(repo_root: Path, path: Path) -> tuple[str, bool]:
    relative = path.relative_to(repo_root).with_suffix("")
    parts = list(relative.parts)
    is_package = bool(parts and parts[-1] == "__init__")
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _attribute_parts(node: ast.AST) -> list[str] | None:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        parent = _attribute_parts(node.value)
        if parent:
            return [*parent, node.attr]
    return None


def _static_string(
    expression: ast.AST | None,
    assignments: dict[str, ast.AST],
    *,
    _seen: frozenset[str] = frozenset(),
) -> str | None:
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return expression.value
    if isinstance(expression, ast.Name):
        if expression.id in _seen:
            return None
        return _static_string(
            assignments.get(expression.id),
            assignments,
            _seen=_seen | {expression.id},
        )
    if isinstance(expression, ast.JoinedStr):
        parts: list[str] = []
        for value in expression.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("{}")
            else:
                return None
        return "".join(parts)
    if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.Add):
        left = _static_string(expression.left, assignments, _seen=_seen)
        right = _static_string(expression.right, assignments, _seen=_seen)
        return left + right if left is not None and right is not None else None
    if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Attribute):
        if expression.func.attr == "format":
            template = _static_string(expression.func.value, assignments, _seen=_seen)
            if template is not None:
                return re.sub(r"\{[^{}]*\}", "{}", template)
    return None


def _normalize_route(route: str) -> str:
    normalized = str(route or "").split("?", 1)[0].strip()
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    if normalized == "/api":
        normalized = "/"
    elif normalized.startswith("/api/"):
        normalized = normalized[4:]
    segments = []
    for segment in normalized.strip("/").split("/"):
        segments.append("{}" if "{" in segment and "}" in segment else segment)
    return "/" + "/".join(segments)


def _route_matches(actual: str, expected: str) -> bool:
    actual_parts = _normalize_route(actual).strip("/").split("/")
    expected_parts = _normalize_route(expected).strip("/").split("/")
    if len(actual_parts) < len(expected_parts):
        return False
    # Router decorators often carry only their local path (for example
    # ``/apply``), while tests call the fully mounted path
    # (``/api/outliers/apply``).  Conservatively match that exact suffix so a
    # prefixless decorator cannot hide checkpoint mutation from this guard.
    compared_actual = actual_parts[-len(expected_parts) :]
    return all(
        expected_part == "{}"
        or actual_part == "{}"
        or actual_part == expected_part
        for actual_part, expected_part in zip(compared_actual, expected_parts)
    )


def _server_mutation_graph(
    repo_root: Path = REPO_ROOT,
) -> tuple[
    frozenset[str],
    frozenset[tuple[str, str]],
    frozenset[str],
    frozenset[tuple[str, str]],
]:
    """Return Dataset Library and checkpoint mutation call graphs/routes."""

    server_root = repo_root / "server"
    parsed: dict[str, tuple[ast.AST, bool]] = {}
    for source_path in sorted(server_root.rglob("*.py")):
        try:
            module, is_package = _module_name(repo_root, source_path)
            parsed[module] = (
                ast.parse(
                    source_path.read_text(encoding="utf-8"),
                    filename=str(source_path),
                ),
                is_package,
            )
        except (OSError, SyntaxError, UnicodeError, ValueError):
            continue
    modules = set(parsed)
    top_level_functions: dict[tuple[str, str], str] = {}
    function_nodes: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    route_decorators: dict[str, list[tuple[str, str]]] = {}
    for module, (tree, _is_package) in parsed.items():
        for node in getattr(tree, "body", []):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key = f"{module}:{node.lineno}:{node.name}"
                top_level_functions[(module, node.name)] = key
                function_nodes[key] = node
        # FastAPI permits route functions nested in an application factory.
        for node in _function_nodes(tree):
            key = top_level_functions.get((module, node.name))
            if key is None or function_nodes.get(key) is not node:
                key = f"{module}:{node.lineno}:{node.name}"
                function_nodes[key] = node
            routes: list[tuple[str, str]] = []
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                parts = _attribute_parts(decorator.func)
                if not parts or parts[-1].casefold() not in _MUTATING_HTTP_METHODS:
                    continue
                if not decorator.args:
                    continue
                route = _static_string(decorator.args[0], {})
                if route:
                    routes.append((parts[-1].casefold(), _normalize_route(route)))
            if routes:
                route_decorators[key] = routes

    edges: dict[str, set[str]] = {key: set() for key in function_nodes}
    for module, (tree, is_package) in parsed.items():
        module_aliases: dict[str, str] = {}
        symbol_aliases: dict[str, tuple[str, str]] = {}
        for statement in ast.walk(tree):
            if isinstance(statement, ast.Import):
                for alias in statement.names:
                    if alias.name in modules:
                        module_aliases[alias.asname or alias.name.split(".")[0]] = alias.name
            elif isinstance(statement, ast.ImportFrom):
                imported_module = _resolve_import_module(
                    module,
                    statement,
                    is_package=is_package,
                )
                if not imported_module:
                    continue
                for alias in statement.names:
                    local_name = alias.asname or alias.name
                    submodule = f"{imported_module}.{alias.name}"
                    if submodule in modules:
                        module_aliases[local_name] = submodule
                    else:
                        symbol_aliases[local_name] = (imported_module, alias.name)

        for key, function in function_nodes.items():
            if not key.startswith(f"{module}:"):
                continue
            for child in ast.walk(function):
                if not isinstance(child, ast.Call):
                    continue
                target: tuple[str, str] | None = None
                if isinstance(child.func, ast.Name):
                    target = symbol_aliases.get(child.func.id) or (
                        (module, child.func.id)
                        if (module, child.func.id) in top_level_functions
                        else None
                    )
                else:
                    parts = _attribute_parts(child.func)
                    if parts and len(parts) >= 2 and parts[0] in module_aliases:
                        target = (module_aliases[parts[0]], parts[-1])
                if target and target in top_level_functions:
                    edges[key].add(top_level_functions[target])

    registry_module = "server.datasets.dataset_registry"
    registry_mutators = {
        key
        for (module, name), key in top_level_functions.items()
        if module == registry_module and name in _ENDPOINT_PROPAGATING_MUTATORS
    }
    checkpoint_mutators = {
        key
        for (module, name), key in top_level_functions.items()
        if module == "server.core.session_checkpoint"
        and name in _CHECKPOINT_MUTATORS
    }

    def _closure(
        roots: set[str],
    ) -> tuple[frozenset[str], frozenset[tuple[str, str]]]:
        mutating = set(roots)
        propagating = set(roots)
        while True:
            discovered = {
                caller
                for caller, callees in edges.items()
                if callees.intersection(propagating)
            }
            expanded = mutating | discovered
            if expanded == mutating:
                break
            mutating = expanded
            propagating |= discovered
        routes = frozenset(
            route
            for key, decorated in route_decorators.items()
            if key in mutating
            for route in decorated
        )
        qualified = frozenset(
            f"{key.split(':', 1)[0]}.{function_nodes[key].name}"
            for key in mutating
        )
        return qualified, routes

    dataset_functions, dataset_routes = _closure(registry_mutators)
    checkpoint_functions, checkpoint_routes = _closure(checkpoint_mutators)
    return (
        dataset_functions,
        dataset_routes,
        checkpoint_functions,
        checkpoint_routes,
    )


(
    MUTATING_SERVER_FUNCTIONS,
    DATASET_MUTATING_ENDPOINTS,
    CHECKPOINT_MUTATING_SERVER_FUNCTIONS,
    CHECKPOINT_MUTATING_ENDPOINTS,
) = _server_mutation_graph()


@lru_cache(maxsize=None)
def _test_import_bindings(tree: ast.AST) -> tuple[dict[str, str], dict[str, str]]:
    module_aliases: dict[str, str] = {"dataset_registry": "server.datasets.dataset_registry"}
    symbol_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("server."):
                    module_aliases[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                if module == "server.datasets" and alias.name == "dataset_registry":
                    module_aliases[local] = "server.datasets.dataset_registry"
                elif module.startswith("server."):
                    symbol_aliases[local] = f"{module}.{alias.name}"
    return module_aliases, symbol_aliases


def _dataset_mutator_calls(tree: ast.AST) -> list[ast.Call]:
    module_aliases, symbol_aliases = _test_import_bindings(tree)
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        qualified: str | None = None
        if isinstance(node.func, ast.Name):
            qualified = symbol_aliases.get(node.func.id)
        else:
            parts = _attribute_parts(node.func)
            if parts and len(parts) >= 2 and parts[0] in module_aliases:
                qualified = f"{module_aliases[parts[0]]}.{parts[-1]}"
        registry_prefix = "server.datasets.dataset_registry."
        if (
            qualified is not None
            and qualified.startswith(registry_prefix)
            and qualified[len(registry_prefix) :] in DATASET_MUTATORS
        ):
            calls.append(node)
    return sorted(calls, key=lambda item: item.lineno)


def _string_assignments(tree: ast.AST) -> dict[str, ast.AST]:
    assignments: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assignments[node.target.id] = node.value
    return assignments


def _call_keyword(call: ast.Call, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _dataset_endpoint_calls(tree: ast.AST) -> list[ast.Call]:
    assignments = _string_assignments(tree)
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        called_method = node.func.attr.casefold()
        method: str | None = None
        route_expression: ast.AST | None = None
        if called_method in _MUTATING_HTTP_METHODS:
            method = called_method
            route_expression = (
                node.args[0] if node.args else _call_keyword(node, "url")
            )
        elif called_method == "request":
            method_expression = (
                node.args[0] if node.args else _call_keyword(node, "method")
            )
            route_expression = (
                node.args[1]
                if len(node.args) > 1
                else _call_keyword(node, "url")
            )
            rendered_method = _static_string(method_expression, assignments)
            method = rendered_method.casefold() if rendered_method else None
        if method not in _MUTATING_HTTP_METHODS:
            continue
        route = _static_string(route_expression, assignments)
        if route is None:
            continue
        if any(
            method == expected_method and _route_matches(route, expected_route)
            for expected_method, expected_route in DATASET_MUTATING_ENDPOINTS
        ):
            calls.append(node)
    return sorted(calls, key=lambda item: item.lineno)


@lru_cache(maxsize=None)
def _checkpoint_import_bindings(
    tree: ast.AST,
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve direct checkpoint imports without importing ATLAS modules."""

    module_aliases: dict[str, str] = {}
    symbol_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "server.core.session_checkpoint":
                    module_aliases[alias.asname or "server"] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                if module == "server.core" and alias.name == "session_checkpoint":
                    module_aliases[local] = "server.core.session_checkpoint"
                elif module == "server.core.session_checkpoint":
                    symbol_aliases[local] = f"{module}.{alias.name}"
                elif (
                    module == "server.persistence.persistence_router"
                    and alias.name == "delete_project"
                ):
                    symbol_aliases[local] = f"{module}.{alias.name}"
    return module_aliases, symbol_aliases


def _checkpoint_mutator_calls(tree: ast.AST) -> list[ast.Call]:
    """Find direct and HTTP mutations that can persist the live checkpoint."""

    assignments = _string_assignments(tree)
    module_aliases, symbol_aliases = _checkpoint_import_bindings(tree)
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        qualified: str | None = None
        parts = _attribute_parts(node.func)
        if isinstance(node.func, ast.Name):
            qualified = symbol_aliases.get(node.func.id)
        elif parts and len(parts) >= 2 and parts[0] in module_aliases:
            module = module_aliases[parts[0]]
            if len(parts) == 2:
                qualified = f"{module}.{parts[-1]}"
            elif (
                len(parts) == 3
                and parts[1] == "CHECKPOINT_PATH"
                and parts[-1] in _CHECKPOINT_FILE_MUTATORS
            ):
                qualified = f"{module}.CHECKPOINT_PATH.{parts[-1]}"
        elif (
            parts
            and len(parts) == 2
            and symbol_aliases.get(parts[0])
            == "server.core.session_checkpoint.CHECKPOINT_PATH"
            and parts[-1] in _CHECKPOINT_FILE_MUTATORS
        ):
            qualified = f"{symbol_aliases[parts[0]]}.{parts[-1]}"

        if qualified is not None:
            checkpoint_prefix = "server.core.session_checkpoint."
            if (
                qualified.startswith(checkpoint_prefix)
                and (
                    qualified[len(checkpoint_prefix) :] in _CHECKPOINT_MUTATORS
                    or qualified[len(checkpoint_prefix) :].startswith(
                        "CHECKPOINT_PATH."
                    )
                )
            ) or qualified in CHECKPOINT_MUTATING_SERVER_FUNCTIONS:
                calls.append(node)
                continue

        if not isinstance(node.func, ast.Attribute):
            continue
        called_method = node.func.attr.casefold()
        method: str | None = None
        route_expression: ast.AST | None = None
        if called_method in _MUTATING_HTTP_METHODS:
            method = called_method
            route_expression = (
                node.args[0] if node.args else _call_keyword(node, "url")
            )
        elif called_method == "request":
            method_expression = (
                node.args[0] if node.args else _call_keyword(node, "method")
            )
            route_expression = (
                node.args[1]
                if len(node.args) > 1
                else _call_keyword(node, "url")
            )
            rendered_method = _static_string(method_expression, assignments)
            method = rendered_method.casefold() if rendered_method else None
        if method not in _MUTATING_HTTP_METHODS:
            continue
        route = _static_string(route_expression, assignments)
        if route is not None and any(
            method == expected_method and _route_matches(route, expected_route)
            for expected_method, expected_route in CHECKPOINT_MUTATING_ENDPOINTS
        ):
            calls.append(node)
    return sorted({id(call): call for call in calls}.values(), key=lambda item: item.lineno)


def _checkpoint_path_rebindings(tree: ast.AST) -> list[tuple[int, ast.expr]]:
    module_aliases, _ = _checkpoint_import_bindings(tree)
    rebindings: list[tuple[int, ast.expr]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "CHECKPOINT_PATH"
                and isinstance(target.value, ast.Name)
                and target.value.id in module_aliases
            ):
                rebindings.append((node.lineno, node.value))
    return sorted(rebindings, key=lambda item: item[0])


@lru_cache(maxsize=None)
def _binding_assignments(tree: ast.AST) -> dict[str, list[tuple[int, ast.expr]]]:
    """Collect simple name/attribute assignments without executing the test."""

    assignments: dict[str, list[tuple[int, ast.expr]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            parts = _attribute_parts(target)
            if parts:
                assignments.setdefault(".".join(parts), []).append(
                    (node.lineno, node.value)
                )
    for entries in assignments.values():
        entries.sort(key=lambda item: item[0])
    # Resolve helper parameters from their explicit call sites.  This permits
    # safe wrappers such as ``_set_checkpoint_path(_CHECKPOINT_PATH)`` while
    # still requiring the argument itself to trace to UUID-owned temp state.
    functions = {node.name: node for node in _function_nodes(tree)}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        function = functions.get(node.func.id)
        if function is None:
            continue
        parameters = [*function.args.posonlyargs, *function.args.args]
        for index, parameter in enumerate(parameters):
            value: ast.expr | None = node.args[index] if index < len(node.args) else None
            if value is None:
                value = _call_keyword(node, parameter.arg)
            if value is not None:
                assignments.setdefault(parameter.arg, []).append(
                    (node.lineno, value)
                )
    for entries in assignments.values():
        entries.sort(key=lambda item: item[0])
    return assignments


def _latest_binding(
    assignments: dict[str, list[tuple[int, ast.expr]]],
    key: str,
    before_line: int,
) -> ast.expr | None:
    candidates = [
        expression
        for line, expression in assignments.get(key, [])
        if line < before_line
    ]
    return candidates[-1] if candidates else None


def _expression_uses_uuid(
    expression: ast.expr | None,
    assignments: dict[str, list[tuple[int, ast.expr]]],
    before_line: int,
    *,
    _seen: frozenset[str] = frozenset(),
) -> bool:
    if expression is None:
        return False
    for node in ast.walk(expression):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "uuid"
            and function.attr == "uuid4"
        ) or (isinstance(function, ast.Name) and function.id == "uuid4"):
            return True
    for node in ast.walk(expression):
        parts = _attribute_parts(node)
        if not parts:
            continue
        key = ".".join(parts)
        if key in _seen:
            continue
        binding = _latest_binding(assignments, key, before_line)
        if binding is not None and _expression_uses_uuid(
            binding,
            assignments,
            before_line,
            _seen=_seen | {key},
        ):
            return True
    return False


def _expression_uses_temporary_location(
    expression: ast.expr | None,
    assignments: dict[str, list[tuple[int, ast.expr]]],
    before_line: int,
    *,
    _seen: frozenset[str] = frozenset(),
) -> bool:
    if expression is None:
        return False
    fragments = {
        fragment.replace("\\", "/").strip("/").casefold()
        for fragment in _string_fragments(expression)
    }
    if any(
        fragment in {".tmp", "tmp", "temp", "temporary"}
        or fragment.startswith((".tmp/", "tmp/", "temp/"))
        for fragment in fragments
    ):
        return True
    rendered = ast.unparse(expression).casefold()
    if "tempfile.mkdtemp" in rendered or "tempfile.gettempdir" in rendered:
        return True
    for node in ast.walk(expression):
        parts = _attribute_parts(node)
        if not parts:
            continue
        key = ".".join(parts)
        if key in _seen:
            continue
        binding = _latest_binding(assignments, key, before_line)
        if binding is not None and _expression_uses_temporary_location(
            binding,
            assignments,
            before_line,
            _seen=_seen | {key},
        ):
            return True
    return False


def _references_checkpoint_environment(expression: ast.expr | None) -> bool:
    if expression is None:
        return False
    rendered = ast.unparse(expression)
    return CHECKPOINT_ENVIRONMENT_KEY in rendered and (
        "os.environ" in rendered or "os.getenv" in rendered
    )


def _owned_uuid_checkpoint_expression(
    expression: ast.expr | None,
    tree: ast.AST,
    before_line: int,
) -> bool:
    """Prove a checkpoint expression belongs to this test's UUID temp root."""

    if expression is None or _points_at_live_checkpoint(expression):
        return False
    assignments = _binding_assignments(tree)
    candidate = expression
    if _references_checkpoint_environment(expression):
        setdefault_lines = _environment_setdefault_lines(
            tree, CHECKPOINT_ENVIRONMENT_KEY
        )
        local_writes = [
            value
            for line, value in _environment_writes(
                tree, CHECKPOINT_ENVIRONMENT_KEY
            )
            if line < before_line
            and line not in setdefault_lines
        ]
        if not local_writes:
            return False
        candidate = local_writes[-1]
        if candidate is None or _inherits_configured_checkpoint_path(candidate):
            return False
    return _expression_uses_uuid(
        candidate, assignments, before_line
    ) and _expression_uses_temporary_location(
        candidate, assignments, before_line
    )


def _owned_uuid_dataset_expression(
    expression: ast.expr | None,
    tree: ast.AST,
    before_line: int,
) -> bool:
    if expression is None or _points_at_checked_in_root(expression):
        return False
    assignments = _binding_assignments(tree)
    candidate = expression
    if _inherits_configured_dataset_root(expression):
        setdefault_lines = _environment_setdefault_lines(
            tree, DATASET_ENVIRONMENT_KEY
        )
        local_writes = [
            value
            for line, value in _environment_writes(tree, DATASET_ENVIRONMENT_KEY)
            if line < before_line
            and line not in setdefault_lines
        ]
        if not local_writes:
            return False
        candidate = local_writes[-1]
        if candidate is None or _inherits_configured_dataset_root(candidate):
            return False
    return _expression_uses_uuid(
        candidate, assignments, before_line
    ) and _expression_uses_temporary_location(
        candidate, assignments, before_line
    )


def _unwrap_path_expression(expression: ast.expr) -> ast.expr:
    current = expression
    while isinstance(current, ast.Call):
        if (
            isinstance(current.func, ast.Attribute)
            and current.func.attr in {"resolve", "expanduser", "absolute"}
            and not current.args
        ):
            current = current.func.value
            continue
        if (
            isinstance(current.func, ast.Name)
            and current.func.id in {"Path", "str"}
            and len(current.args) == 1
        ):
            current = current.args[0]
            continue
        break
    return current


def _path_parent_for_leaf(expression: ast.expr, leaf: str) -> ast.expr | None:
    current = _unwrap_path_expression(expression)
    if (
        isinstance(current, ast.BinOp)
        and isinstance(current.op, ast.Div)
        and isinstance(current.right, ast.Constant)
        and current.right.value == leaf
    ):
        return current.left
    if (
        isinstance(current, ast.Call)
        and isinstance(current.func, ast.Attribute)
        and current.func.attr == "joinpath"
        and len(current.args) == 1
        and isinstance(current.args[0], ast.Constant)
        and current.args[0].value == leaf
    ):
        return current.func.value
    return None


def _expanded_expression_key(
    expression: ast.expr,
    assignments: dict[str, list[tuple[int, ast.expr]]],
    before_line: int,
    *,
    _seen: frozenset[str] = frozenset(),
) -> str:
    current = _unwrap_path_expression(expression)
    parts = _attribute_parts(current)
    if parts:
        key = ".".join(parts)
        if key.endswith("dataset_registry.ARTIFACT_ROOT") or key.endswith(
            "dataset_registry_module.ARTIFACT_ROOT"
        ):
            return "<DATASET_ARTIFACT_ROOT>"
        if key not in _seen:
            binding = _latest_binding(assignments, key, before_line)
            if binding is not None:
                return _expanded_expression_key(
                    binding,
                    assignments,
                    before_line,
                    _seen=_seen | {key},
                )
    if isinstance(current, ast.BinOp) and isinstance(current.op, ast.Div):
        return (
            _expanded_expression_key(
                current.left, assignments, before_line, _seen=_seen
            )
            + "/"
            + _expanded_expression_key(
                current.right, assignments, before_line, _seen=_seen
            )
        )
    return ast.dump(current, annotate_fields=False, include_attributes=False)


@lru_cache(maxsize=None)
def _dataset_rebindings_in_scope(
    tree: ast.AST,
    scope: ast.AST,
    before_line: int,
) -> dict[str, tuple[int, ast.expr]]:
    module_aliases, _ = _test_import_bindings(tree)
    rebound: dict[str, tuple[int, ast.expr]] = {}
    expected_owner = (
        scope
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef))
        else None
    )
    for node in ast.walk(scope):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.lineno >= before_line:
            continue
        if _enclosing_function(tree, node.lineno) is not expected_owner:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and module_aliases.get(target.value.id)
                == "server.datasets.dataset_registry"
                and target.attr in REQUIRED_REBINDINGS
            ):
                rebound[target.attr] = (node.lineno, node.value)
    return rebound


def _dataset_rebindings_are_owned(
    tree: ast.AST,
    rebound: dict[str, tuple[int, ast.expr]],
    before_line: int,
) -> bool:
    if not REQUIRED_REBINDINGS.issubset(rebound):
        return False
    artifact_expression = rebound["ARTIFACT_ROOT"][1]
    if not _owned_uuid_dataset_expression(
        artifact_expression, tree, before_line
    ):
        return False
    assignments = _binding_assignments(tree)
    artifact_key = _expanded_expression_key(
        artifact_expression, assignments, before_line
    )
    expected_leaves = {
        "REGISTRY_PATH": "registry.json",
        "USERS_PATH": "users.json",
        "PROJECT_LINKS_PATH": "project_links.json",
    }
    for binding, leaf in expected_leaves.items():
        parent = _path_parent_for_leaf(rebound[binding][1], leaf)
        if parent is None:
            return False
        parent_key = _expanded_expression_key(parent, assignments, before_line)
        if parent_key not in {artifact_key, "<DATASET_ARTIFACT_ROOT>"}:
            return False
    return True


def _is_empty_catalog_write(call: ast.Call) -> bool:
    if not isinstance(call.func, ast.Attribute) or not call.args:
        return False
    expected_key = {
        "save_registry": "datasets",
        "save_links": "links",
    }.get(call.func.attr)
    payload = call.args[0]
    if expected_key is None or not isinstance(payload, ast.Dict):
        return False
    value = _dict_value(payload, expected_key)
    return isinstance(value, (ast.List, ast.Tuple)) and not value.elts


def _uuid_call_lines(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "uuid"
            and function.attr == "uuid4"
        ) or (isinstance(function, ast.Name) and function.id == "uuid4"):
            lines.append(node.lineno)
    return sorted(lines)


def _string_fragments(expression: ast.expr | None) -> list[str]:
    if expression is None:
        return []
    return [
        str(node.value)
        for node in ast.walk(expression)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _inherits_configured_dataset_root(expression: ast.expr | None) -> bool:
    if expression is None:
        return False
    rendered = ast.unparse(expression)
    return (
        DATASET_ENVIRONMENT_KEY in rendered
        and ("os.environ" in rendered or "os.getenv" in rendered)
    )


def _inherits_configured_checkpoint_path(expression: ast.expr | None) -> bool:
    if expression is None:
        return False
    rendered = ast.unparse(expression)
    return (
        CHECKPOINT_ENVIRONMENT_KEY in rendered
        and ("os.environ" in rendered or "os.getenv" in rendered)
    )


def _points_at_checked_in_root(expression: ast.expr | None) -> bool:
    fragments = [fragment.replace("\\", "/").strip("/").casefold() for fragment in _string_fragments(expression)]
    joined = "/".join(fragment for fragment in fragments if fragment)
    return "server/artifacts/datasets" in joined or {
        "server",
        "artifacts",
        "datasets",
    }.issubset(fragments)


def _points_at_live_checkpoint(expression: ast.expr | None) -> bool:
    fragments = [
        fragment.replace("\\", "/").strip("/").casefold()
        for fragment in _string_fragments(expression)
    ]
    joined = "/".join(fragment for fragment in fragments if fragment)
    if ".runtime/workflow_checkpoint.json" in joined:
        return True
    literal = _literal_path(expression)
    return literal == DEFAULT_LIVE_CHECKPOINT_PATH


def _literal_path(expression: ast.expr | None) -> Path | None:
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        try:
            return Path(expression.value).expanduser().resolve()
        except OSError:
            return None
    return None


@lru_cache(maxsize=None)
def _function_rebindings(tree: ast.AST) -> dict[str, set[str]]:
    results: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        rebound = _dataset_rebindings_in_scope(
            tree, node, getattr(node, "end_lineno", node.lineno) + 1
        )
        if REQUIRED_REBINDINGS.issubset(rebound):
            results[node.name] = set(rebound)
    return results


def _prior_direct_dataset_rebindings(
    tree: ast.AST,
    function: ast.FunctionDef | ast.AsyncFunctionDef | None,
    line: int,
) -> dict[str, tuple[int, ast.expr]]:
    scope: ast.AST = function if function is not None else tree
    return _dataset_rebindings_in_scope(tree, scope, line)


@lru_cache(maxsize=None)
def _enclosing_function(tree: ast.AST, line: int) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    candidates: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, "end_lineno", node.lineno)
        if node.lineno <= line <= end:
            candidates.append(node)
    if not candidates:
        return None
    return min(candidates, key=lambda node: getattr(node, "end_lineno", node.lineno) - node.lineno)


@lru_cache(maxsize=None)
def _enclosing_class(tree: ast.AST, line: int) -> ast.ClassDef | None:
    candidates: list[ast.ClassDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        end = getattr(node, "end_lineno", node.lineno)
        if node.lineno <= line <= end:
            candidates.append(node)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda node: getattr(node, "end_lineno", node.lineno) - node.lineno,
    )


@lru_cache(maxsize=None)
def _reachable_helpers_before(
    tree: ast.AST,
    line: int,
    owner: ast.FunctionDef | ast.AsyncFunctionDef | None,
) -> set[str]:
    functions = {node.name: node for node in _function_nodes(tree)}
    owner_class = _enclosing_class(tree, line)
    reachable: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or node.lineno >= line:
            continue
        if not isinstance(node.func, ast.Name) or node.func.id not in functions:
            continue
        caller = _enclosing_function(tree, node.lineno)
        caller_class = _enclosing_class(tree, node.lineno)
        if (
            caller is None
            or caller is owner
            or (
                caller.name in {"setUp", "setUpClass", "asyncSetUp"}
                and caller_class is owner_class
            )
        ):
            reachable.add(node.func.id)
    while True:
        expanded = set(reachable)
        for name in reachable:
            for node in ast.walk(functions[name]):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in functions:
                        expanded.add(node.func.id)
        if expanded == reachable:
            return reachable
        reachable = expanded


def _has_prior_rebind_call(
    function: ast.FunctionDef | ast.AsyncFunctionDef | None,
    line: int,
    rebinders: set[str],
) -> bool:
    if function is None:
        return False
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or node.lineno >= line:
            continue
        if isinstance(node.func, ast.Name) and node.func.id in rebinders:
            return True
    return False


def _has_complete_dataset_rebind_before(
    tree: ast.AST,
    call: ast.Call,
    rebinders: set[str],
) -> bool:
    function = _enclosing_function(tree, call.lineno)
    direct = _prior_direct_dataset_rebindings(tree, function, call.lineno)
    if _dataset_rebindings_are_owned(tree, direct, call.lineno):
        return True
    # A module-level bootstrap or unittest setUp/asyncSetUp call executes before
    # test methods and is an accepted explicit cache rebind.  Only calls that
    # textually precede this mutator can satisfy the fail-closed guard.
    reachable = rebinders.intersection(
        _reachable_helpers_before(tree, call.lineno, function)
    )
    function_nodes = {node.name: node for node in _function_nodes(tree)}
    for name in reachable:
        rebind_function = function_nodes[name]
        rebound = _dataset_rebindings_in_scope(
            tree,
            rebind_function,
            getattr(rebind_function, "end_lineno", rebind_function.lineno) + 1,
        )
        if _dataset_rebindings_are_owned(tree, rebound, call.lineno):
            return True
    return False


def _is_checkpoint_cleanup_rebinding(tree: ast.AST, line: int) -> bool:
    owner = _enclosing_function(tree, line)
    return owner is not None and owner.name in {
        "tearDown",
        "tearDownClass",
        "asyncTearDown",
    }


def scan_test_source(
    path: Path,
    source: str,
    *,
    configured_live_roots: Iterable[Path] = (),
) -> list[IsolationViolation]:
    """Inspect one Python test without executing or importing it."""

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            IsolationViolation(
                path,
                exc.lineno or 1,
                "TSI000",
                f"cannot inspect invalid Python syntax: {exc.msg}",
            )
        ]

    violations: list[IsolationViolation] = []
    imports = _server_import_lines(tree)
    first_import = imports[0] if imports else sys.maxsize
    direct_mutators = _dataset_mutator_calls(tree)
    endpoint_mutators = _dataset_endpoint_calls(tree)
    mutators = sorted(
        {id(call): call for call in (*direct_mutators, *endpoint_mutators)}.values(),
        key=lambda item: item.lineno,
    )
    dataset_writes = _environment_writes(tree, DATASET_ENVIRONMENT_KEY)
    checkpoint_mutators = _checkpoint_mutator_calls(tree)
    checkpoint_writes = _environment_writes(tree, CHECKPOINT_ENVIRONMENT_KEY)
    checkpoint_rebindings = _checkpoint_path_rebindings(tree)

    for line, expression in checkpoint_writes:
        if _points_at_live_checkpoint(expression):
            violations.append(
                IsolationViolation(
                    path,
                    line,
                    "TSI010",
                    "checkpoint test path resolves to the live workflow checkpoint",
                )
            )
        if _inherits_configured_checkpoint_path(expression):
            violations.append(
                IsolationViolation(
                    path,
                    line,
                    "TSI010",
                    "test inherits the configured checkpoint path instead of owning a temporary path",
                )
            )

    if checkpoint_mutators:
        first_mutator = checkpoint_mutators[0].lineno
        first_mutator_owner = _enclosing_function(tree, first_mutator)
        reachable_checkpoint_helpers = _reachable_helpers_before(
            tree, first_mutator, first_mutator_owner
        )
        prior_rebindings = [
            (line, expression)
            for line, expression in checkpoint_rebindings
            if line < first_mutator
            and not _is_checkpoint_cleanup_rebinding(tree, line)
            and (
                _enclosing_function(tree, line) is None
                or _enclosing_function(tree, line) is first_mutator_owner
                or (
                    _enclosing_function(tree, line) is not None
                    and _enclosing_function(tree, line).name
                    in {"setUp", "setUpClass", "asyncSetUp"}
                    and _enclosing_class(tree, line)
                    is _enclosing_class(tree, first_mutator)
                )
                or (
                    _enclosing_function(tree, line) is not None
                    and _enclosing_function(tree, line).name
                    in reachable_checkpoint_helpers
                )
            )
        ]
        for line, expression in prior_rebindings:
            if _points_at_live_checkpoint(expression) or not _owned_uuid_checkpoint_expression(
                expression, tree, first_mutator
            ):
                violations.append(
                    IsolationViolation(
                        path,
                        line,
                        "TSI010",
                        "cached CHECKPOINT_PATH rebind is not a provably owned UUID temporary path",
                    )
                )
        if not checkpoint_writes and not checkpoint_rebindings:
            violations.append(
                IsolationViolation(
                    path,
                    first_mutator,
                    "TSI007",
                    "checkpoint mutation has no explicit temporary checkpoint path",
                )
            )
        elif not prior_rebindings:
            violations.append(
                IsolationViolation(
                    path,
                    min(
                        [line for line, _ in checkpoint_writes]
                        + [line for line, _ in checkpoint_rebindings]
                    ),
                    "TSI008",
                    "checkpoint-mutating test does not explicitly rebind the cached CHECKPOINT_PATH before mutation",
                )
            )

        isolation_lines = sorted(
            line
            for line, expression in prior_rebindings
            if _owned_uuid_checkpoint_expression(expression, tree, first_mutator)
        )
        if not isolation_lines:
            violations.append(
                IsolationViolation(
                    path,
                    isolation_lines[0] if isolation_lines else first_mutator,
                    "TSI009",
                    "checkpoint-mutating test does not create a UUID-specific path before configuration",
                )
            )

    for line, expression in dataset_writes:
        if _points_at_checked_in_root(expression):
            violations.append(
                IsolationViolation(
                    path,
                    line,
                    "TSI004",
                    "Dataset Library test root resolves beneath server/artifacts/datasets",
                )
            )
        literal = _literal_path(expression)
        if literal is not None:
            forbidden = {DEFAULT_LIVE_ROOT, *(Path(root).resolve() for root in configured_live_roots)}
            if literal in forbidden or any(root in literal.parents for root in forbidden):
                violations.append(
                    IsolationViolation(
                        path,
                        line,
                        "TSI004",
                        f"Dataset Library test root targets configured live storage: {literal}",
                    )
                )
        if _inherits_configured_dataset_root(expression):
            violations.append(
                IsolationViolation(
                    path,
                    line,
                    "TSI004",
                    "test inherits the configured Dataset Library root instead of owning a temporary root",
                )
            )

    if not mutators:
        return sorted(violations, key=lambda item: (item.line, item.rule))

    if not dataset_writes:
        violations.append(
            IsolationViolation(
                path,
                mutators[0].lineno,
                "TSI001",
                "Dataset Library mutation has no explicit temporary root",
            )
        )
    elif dataset_writes[0][0] >= first_import:
        violations.append(
            IsolationViolation(
                path,
                dataset_writes[0][0],
                "TSI002",
                "Dataset Library root is configured after an ATLAS server import cached paths",
            )
        )

    root_write_line = dataset_writes[0][0] if dataset_writes else first_import
    if not any(line < root_write_line for line in _uuid_call_lines(tree)):
        violations.append(
            IsolationViolation(
                path,
                root_write_line if root_write_line != sys.maxsize else mutators[0].lineno,
                "TSI003",
                "mutable Dataset Library test does not create a UUID-specific root before configuration",
            )
        )

    empty_writes = [call for call in direct_mutators if _is_empty_catalog_write(call)]
    if empty_writes:
        test_mode_writes = sorted(
            line
            for key in TEST_MODE_KEYS
            for line, _ in _environment_writes(tree, key)
        )
        if not test_mode_writes or test_mode_writes[0] >= first_import:
            violations.append(
                IsolationViolation(
                    path,
                    empty_writes[0].lineno,
                    "TSI005",
                    "empty-catalog fixture must enable test mode before ATLAS imports",
                )
            )
    rebinders = set(_function_rebindings(tree))
    for call in mutators:
        if not _has_complete_dataset_rebind_before(tree, call, rebinders):
            violations.append(
                IsolationViolation(
                    path,
                    call.lineno,
                    "TSI006",
                    "Dataset Library mutation is not preceded by a complete, UUID-owned cached-path rebind",
                )
            )

    return sorted(violations, key=lambda item: (item.line, item.rule))


def scan_repository(
    repo_root: Path = REPO_ROOT,
    *,
    configured_live_roots: Iterable[Path] = (),
) -> tuple[list[Path], list[IsolationViolation]]:
    tests_root = repo_root / "tests"
    paths = sorted(tests_root.rglob("*_test.py"))
    violations: list[IsolationViolation] = []
    for path in paths:
        violations.extend(
            scan_test_source(
                path,
                path.read_text(encoding="utf-8"),
                configured_live_roots=configured_live_roots,
            )
        )
    return paths, violations


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--configured-live-root",
        action="append",
        type=Path,
        default=[],
        help="Additional live Dataset Library root that tests must never target",
    )
    args = parser.parse_args(argv)
    configured = list(args.configured_live_root)
    environment_live_root = os.getenv("ATLAS_LIVE_DATASET_LIBRARY_ROOT")
    if environment_live_root:
        configured.append(Path(environment_live_root))
    paths, violations = scan_repository(
        args.repo_root.resolve(),
        configured_live_roots=configured,
    )
    if violations:
        print("Dataset Library test-storage isolation guard failed:")
        for violation in violations:
            print(f"  {violation.render()}")
        return 1
    print(
        "Dataset Library test-storage isolation guard passed: "
        f"{len(paths)} Python test sources inspected."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
