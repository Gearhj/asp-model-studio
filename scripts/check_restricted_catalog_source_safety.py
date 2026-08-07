"""Read-only source-safety scanner for the restricted bureau catalog.

The scanner is deliberately independent of ATLAS application imports.  It can
inspect the real Git index, the current tracked-plus-untracked source tree
(both through read-only Git inventory probes), or a synthetic fixture tree
used by the hermetic regression harness. Findings are
content-minimizing: only stable rule codes, repository-relative paths, line or
match counts, and SHA-256 digests are returned.  Matched text is never emitted.

Vendor-description checking uses precomputed normalized token fingerprints.
Screenshot checking consumes a text-free OCR attestation containing only image
digests and match counts.  If strict coverage is requested and either input is
missing, the scan fails closed instead of claiming that content was inspected.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import unicodedata
from typing import Iterable, Iterator, Mapping, Sequence


SCHEMA_VERSION = 1
FINGERPRINT_ALGORITHM = "sha256-normalized-token-window-v1"

RULE_TRACKED_RESTRICTED_ARTIFACT = "BMS001_TRACKED_RESTRICTED_ARTIFACT"
RULE_VENDOR_DESCRIPTION_FINGERPRINT = "BMS002_VENDOR_DESCRIPTION_FINGERPRINT"
RULE_VENDOR_FINGERPRINT_COVERAGE = "BMS003_VENDOR_FINGERPRINT_COVERAGE_MISSING"
RULE_SCREENSHOT_VENDOR_FINGERPRINT = "BMS004_SCREENSHOT_VENDOR_FINGERPRINT"
RULE_SCREENSHOT_OCR_COVERAGE = "BMS005_SCREENSHOT_OCR_UNVERIFIED"
RULE_FRONTEND_RESTRICTED_PATH = "BMS006_FRONTEND_RESTRICTED_PATH"
RULE_HARDCODED_USER_PROFILE = "BMS007_HARDCODED_USER_PROFILE_PATH"
RULE_UNBOUNDED_CATALOG_SURFACE = "BMS008_UNBOUNDED_CATALOG_SURFACE"
RULE_CATALOG_AUTHENTICATION = "BMS009_CATALOG_ROUTE_AUTHENTICATION_MISSING"
RULE_CATALOG_ENTITLEMENT = "BMS010_CATALOG_ROUTE_ENTITLEMENT_MISSING"
RULE_FUZZY_AUTHORITY = "BMS011_FUZZY_MATCH_BECOMES_AUTHORITATIVE"
RULE_GLOBAL_SPECIAL_MEANING = "BMS012_GLOBAL_PROVIDER_SPECIAL_MEANING"
RULE_CATALOG_FALLBACK = "BMS013_FIRST_OR_LATEST_CATALOG_FALLBACK"
RULE_CLIENT_AUTHORITY = "BMS014_CLIENT_SIDE_AUTHORIZATION_AUTHORITY"
RULE_LIVE_ACCEPTANCE_ID = "BMS015_LIVE_HELOC_ID_IN_PRODUCTION"
RULE_SCAN_INPUT = "BMS016_SCAN_INPUT_UNVERIFIED"
RULE_TRACKED_PATH_ESCAPE = "BMS017_TRACKED_PATH_ESCAPE"

_TEXT_SUFFIXES = frozenset(
    {
        ".cjs",
        ".css",
        ".html",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".mjs",
        ".py",
        ".rst",
        ".scss",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)
_FRONTEND_SUFFIXES = frozenset(
    {".cjs", ".css", ".html", ".js", ".json", ".jsx", ".mjs", ".ts", ".tsx"}
)
_SCREENSHOT_SUFFIXES = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"})
_RESTRICTED_ARTIFACT_SUFFIXES = frozenset(
    {".arrow", ".csv", ".db", ".feather", ".jsonl", ".parquet", ".pdf", ".pkl", ".pickle", ".xlsx", ".xls"}
)
_KNOWN_RESTRICTED_BASENAMES = frozenset(
    {
        "attribute_definitions.jsonl",
        "catalog_build_log.json",
        "catalog_manifest.json",
        "catalog_validation_summary.json",
        "credit_bureau_premier.csv",
        "experian_premier_credit_bureau.pdf",
        "lookup_index.json",
        "reconciliation_findings.jsonl",
        "special_value_definitions.jsonl",
    }
)
_RESTRICTED_PATH_MARKERS = frozenset(
    {
        "bureau-catalog",
        "bureau_catalog",
        "catalog-registry",
        "catalog_registry",
        "experian",
        "premier",
        "restricted-catalog",
        "restricted_catalog",
        "vendor-metadata",
        "vendor_metadata",
    }
)
_SELF_PATH = "scripts/check_restricted_catalog_source_safety.py"

_WINDOWS_USER_PROFILE = re.compile(
    r"(?i)(?:[a-z]:[\\/](?:users|documents and settings)[\\/][^\\/\s\"']+)"
)
# POSIX home roots are case-sensitive on the platforms where these paths are
# conventional.  Keeping ``/Users`` case-sensitive also prevents ordinary API
# routes such as ``/users/current`` from being misclassified as host paths.
_POSIX_USER_PROFILE = re.compile(r"(?:/home/[^/\s\"']+|/Users/[^/\s\"']+)")
_FRONTEND_PHYSICAL_PATH = re.compile(
    r"(?i)(?:ATLAS_(?:BUREAU_)?(?:RESTRICTED_)?CATALOG_(?:ROOT|PATH)|"
    r"[\"']?(?:artifact_path|filesystem_path|physical_path|registry_path|storage_path|restricted_catalog_root)[\"']?\s*:|"
    r"(?:catalog|registry)(?:Root|Path|_root|_path)\s*[:=]\s*[\"'][^\"']*(?:[\\/]|\.db)|"
    r"file://[^\s\"']*(?:catalog|bureau)|"
    r"[a-z]:[\\/][^\r\n\"']*(?:restricted[_-]catalog|bureau[_-]catalog))"
)
_BULK_CATALOG_SURFACE = re.compile(
    r"""(?ix)(?:
        /(?:admin/)?bureau-catalogs?(?:/[^\s\"']*)?/(?:download|export|stream|copy-all)|
        \b(?:download|export|stream|serve|copy)[A-Za-z0-9_]*(?:full|all|bulk)[A-Za-z0-9_]*catalog|
        \b(?:download|export|stream|serve|copy)_(?:full|all|bulk)?_?catalog|
        \b(?:full|bulk)_catalog_(?:download|export|stream|copy)
    )"""
)
_FUZZY_AUTHORITY_FORWARD = re.compile(
    r"(?is)\b(?:fuzzy|semantic(?:_similarity|Similarity)?)\b.{0,240}"
    r"\b(?:authoritative|activate|accepted|confirmed|persist(?:ed)?|auto[_-]?link(?:ed)?|exact[_-]?match)\b"
)
_FUZZY_AUTHORITY_REVERSE = re.compile(
    r"(?is)\b(?:authoritative|activate|accepted|confirmed|persist(?:ed)?|auto[_-]?link(?:ed)?|exact[_-]?match)\b"
    r".{0,240}\b(?:fuzzy|semantic(?:_similarity|Similarity)?)\b"
)
_CLIENT_AUTHORITY = re.compile(
    r"(?is)(?:localStorage|sessionStorage|indexedDB).{0,260}"
    r"(?:catalog.{0,40}(?:entitlement|authorization|role)|(?:entitlement|authorization).{0,40}catalog)|"
    r"(?:catalog.{0,40}(?:entitlement|authorization|role)|(?:entitlement|authorization).{0,40}catalog)"
    r".{0,260}(?:localStorage|sessionStorage|indexedDB)|"
    r"\b(?:authorizeCatalogAccess|requireCatalogEntitlement|grantCatalogAccessLocally)\b"
)
_CATALOG_POSITIONAL_FALLBACK = re.compile(
    r"""(?ix)(?:
        \b(?:get|load|resolve|select|find)(?:First|Latest)Catalog\b|
        \b(?:get|load|resolve|select|find)_(?:first|latest)_catalog\b|
        \b(?:catalog|manifest)[A-Za-z0-9_$]*\s*\[\s*(?:0|-1)\s*\]|
        \b(?:catalog|manifest)[A-Za-z0-9_$]*\.at\(\s*(?:0|-1)\s*\)|
        \b[A-Za-z_$][A-Za-z0-9_$]*(?:catalog|manifest)[A-Za-z0-9_$]*\s*\[\s*(?:0|-1)\s*\]|
        \b[A-Za-z_$][A-Za-z0-9_$]*(?:catalog|manifest)[A-Za-z0-9_$]*\.at\(\s*(?:0|-1)\s*\)
    )"""
)

_CATALOG_COLLECTION_NAMES = frozenset(
    {"catalogs", "catalog_versions", "catalog_candidates", "manifests", "manifest_candidates"}
)
_FALLBACK_IDENTIFIERS = frozenset(
    {
        "find_latest_catalog",
        "first_catalog",
        "get_first_catalog",
        "get_latest_catalog",
        "latest_catalog",
        "load_first_catalog",
        "load_latest_catalog",
        "resolve_first_catalog",
        "resolve_latest_catalog",
        "select_first_catalog",
        "select_latest_catalog",
    }
)
_ENTITLEMENT_EVIDENCE_CALLS = frozenset(
    {
        "_require_catalog_administrator",
        "attribute_availability",
        "catalog_health",
        "exact_catalog_attribute",
        "get_attribute",
        "list_entitled_versions",
        "list_special_values",
        "search_attributes",
        "search_catalog_attributes",
    }
)
_AUTHORITY_MUTATION_CALLS = frozenset(
    {"accept", "activate", "authorize", "confirm", "persist", "promote", "save"}
)

# Exact acceptance identities are represented as assembled regexes so they are
# never accidentally emitted as an executable literal by this scanner itself.
_LIVE_ACCEPTANCE_PATTERNS = (
    re.compile("atlas-" + "mrzpau4t", re.IGNORECASE),
    re.compile("ds_" + "heloc_train_6bdb184b_05905", re.IGNORECASE),
    re.compile("v_" + "1785186305905_6bdb184b", re.IGNORECASE),
    re.compile("analysis-partition-" + "688c2184b4e9b8181946-r1", re.IGNORECASE),
)


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    content_sha256: str | None = None
    line: int | None = None
    count: int = 1

    def payload(self) -> dict[str, object]:
        result: dict[str, object] = {
            "code": self.code,
            "path": self.path,
            "count": self.count,
        }
        if self.line is not None:
            result["line"] = self.line
        if self.content_sha256 is not None:
            result["content_sha256"] = self.content_sha256
        return result


@dataclass(frozen=True)
class VendorFingerprint:
    sha256: str
    token_count: int


def _safe_relative(raw: str | Path) -> str:
    value = str(raw).replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", value):
        raise ValueError("unsafe-relative-path")
    normalized = path.as_posix()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized == ".":
        raise ValueError("empty-relative-path")
    return normalized


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _content_hash(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _normalized_tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))


def description_fingerprint(value: str) -> VendorFingerprint:
    """Return a text-free fingerprint suitable for a protected manifest."""

    tokens = _normalized_tokens(value)
    if len(tokens) < 4:
        raise ValueError("description-fingerprint-too-short")
    digest = _sha256_bytes(" ".join(tokens).encode("utf-8"))
    return VendorFingerprint(sha256=digest, token_count=len(tokens))


def _load_fingerprints(path: Path | None) -> tuple[VendorFingerprint, ...]:
    if path is None:
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("invalid-fingerprint-manifest")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported-fingerprint-manifest-schema")
    if payload.get("algorithm") != FINGERPRINT_ALGORITHM:
        raise ValueError("unsupported-fingerprint-algorithm")
    records = payload.get("fingerprints")
    if not isinstance(records, list):
        raise ValueError("invalid-fingerprint-records")
    fingerprints: set[VendorFingerprint] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("invalid-fingerprint-record")
        digest = str(record.get("sha256") or "").casefold()
        token_count = record.get("token_count")
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("invalid-fingerprint-digest")
        if not isinstance(token_count, int) or not 4 <= token_count <= 512:
            raise ValueError("invalid-fingerprint-token-count")
        fingerprints.add(VendorFingerprint(digest, token_count))
    if not fingerprints:
        raise ValueError("empty-fingerprint-manifest")
    return tuple(sorted(fingerprints, key=lambda item: (item.token_count, item.sha256)))


def _fingerprint_matches(text: str, fingerprints: Sequence[VendorFingerprint]) -> int:
    if not fingerprints:
        return 0
    tokens = _normalized_tokens(text)
    expected: dict[int, set[str]] = {}
    for fingerprint in fingerprints:
        expected.setdefault(fingerprint.token_count, set()).add(fingerprint.sha256)
    matches = 0
    for width, digests in expected.items():
        if width > len(tokens):
            continue
        for offset in range(0, len(tokens) - width + 1):
            digest = _sha256_bytes(" ".join(tokens[offset : offset + width]).encode("utf-8"))
            if digest in digests:
                matches += 1
    return matches


def _load_screenshot_attestations(
    path: Path | None,
    *,
    fingerprint_manifest_sha256: str | None,
) -> tuple[str | None, dict[str, tuple[str, int]]]:
    if path is None:
        return None, {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("invalid-screenshot-attestation")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported-screenshot-attestation-schema")
    engine = str(payload.get("engine") or "").strip()
    if not engine:
        raise ValueError("missing-screenshot-ocr-engine")
    if payload.get("fingerprint_algorithm") != FINGERPRINT_ALGORITHM:
        raise ValueError("unsupported-screenshot-fingerprint-algorithm")
    attested_manifest = str(payload.get("fingerprint_manifest_sha256") or "").casefold()
    if (
        fingerprint_manifest_sha256 is None
        or attested_manifest != fingerprint_manifest_sha256
    ):
        raise ValueError("screenshot-fingerprint-manifest-mismatch")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("invalid-screenshot-records")
    attestations: dict[str, tuple[str, int]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("invalid-screenshot-record")
        relative = _safe_relative(str(record.get("path") or ""))
        digest = str(record.get("content_sha256") or "").casefold()
        matches = record.get("vendor_fingerprint_matches")
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("invalid-screenshot-digest")
        if not isinstance(matches, int) or matches < 0:
            raise ValueError("invalid-screenshot-match-count")
        if relative in attestations:
            raise ValueError("duplicate-screenshot-attestation")
        attestations[relative] = (digest, matches)
    return engine, attestations


def discover_git_tracked_paths(root: Path) -> tuple[str, ...]:
    """Return the Git index inventory without reading working-tree content."""

    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("git-index-inventory-failed")
    entries = completed.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    return tuple(sorted(_safe_relative(entry) for entry in entries if entry))


def discover_git_working_tree_source_paths(root: Path) -> tuple[str, ...]:
    """Return tracked and non-ignored untracked source paths.

    The two explicitly supplied root-level proprietary source documents are
    excluded from application-source content scanning because they are
    separately classified as never-stage inputs. A copied CSV/PDF anywhere
    else, including frontend assets, remains in scope and fails closed.
    """

    completed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("git-working-tree-inventory-failed")
    entries = completed.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    never_stage_root_inputs = {
        "credit_bureau_premier.csv",
        "experian_premier_credit_bureau.pdf",
    }
    return tuple(
        sorted(
            relative
            for entry in entries
            if entry
            for relative in (_safe_relative(entry),)
            if relative.casefold() not in never_stage_root_inputs
        )
    )


def discover_fixture_paths(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        )
    )


def _is_doc_or_test(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return bool(parts) and parts[0].casefold() in {"docs", "tests"}


def _is_frontend(relative: str) -> bool:
    path = PurePosixPath(relative)
    return bool(path.parts) and path.parts[0].casefold() in {"public", "src"} and path.suffix.casefold() in _FRONTEND_SUFFIXES


def _is_production_logic(relative: str) -> bool:
    normalized = relative.casefold()
    if normalized == _SELF_PATH.casefold():
        return False
    path = PurePosixPath(relative)
    if not path.parts:
        return False
    root = path.parts[0].casefold()
    if root == "server":
        return path.suffix.casefold() == ".py"
    if root in {"public", "src"}:
        return path.suffix.casefold() in _FRONTEND_SUFFIXES
    if root != "scripts" or path.suffix.casefold() != ".py":
        return False
    name = path.name.casefold()
    return not (
        name.startswith("run_bureau_metadata_")
        or name.startswith("check_")
        or "acceptance" in name
        or "soak" in name
    )


def _is_catalog_related_path(relative: str) -> bool:
    folded = relative.casefold()
    return "catalog" in folded or "bureau_metadata" in folded or "bureaumetadata" in folded


def _is_restricted_artifact_path(relative: str) -> bool:
    path = PurePosixPath(relative.casefold())
    if path.name in _KNOWN_RESTRICTED_BASENAMES:
        return True
    if path.suffix not in _RESTRICTED_ARTIFACT_SUFFIXES:
        return False
    value = path.as_posix()
    return any(marker in value for marker in _RESTRICTED_PATH_MARKERS)


def _python_docstring_nodes(tree: ast.AST) -> set[int]:
    nodes: set[int] = set()
    for owner in ast.walk(tree):
        if not isinstance(owner, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(owner, "body", ())
        if body and isinstance(body[0], ast.Expr):
            value = body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                nodes.add(id(value))
    return nodes


def _python_executable_strings(tree: ast.AST) -> Iterator[tuple[int, str]]:
    ignored = _python_docstring_nodes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in ignored:
            yield node.lineno, node.value
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            combined = _static_string(node)
            if combined is not None:
                yield node.lineno, combined


def _static_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr):
        pieces: list[str] = []
        for value in node.values:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return None
            pieces.append(value.value)
        return "".join(pieces)
    return None


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


def _numeric_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return True
        if isinstance(node.value, str):
            return bool(re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", node.value.strip()))
        return False
    return isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)) and _numeric_literal(node.operand)


def _numeric_meaning_pairs(node: ast.AST) -> int:
    if isinstance(node, ast.Dict):
        return sum(
            1
            for key, value in zip(node.keys, node.values)
            if key is not None
            and _numeric_literal(key)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and bool(value.value.strip())
        )
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return sum(
            1
            for item in node.elts
            if isinstance(item, (ast.List, ast.Tuple))
            and len(item.elts) == 2
            and _numeric_literal(item.elts[0])
            and isinstance(item.elts[1], ast.Constant)
            and isinstance(item.elts[1].value, str)
        )
    if isinstance(node, ast.Call) and _call_parts(node.func)[-1:] == ("MappingProxyType",):
        return max((_numeric_meaning_pairs(item) for item in node.args), default=0)
    return 0


def _module_assignments(tree: ast.Module) -> Iterator[tuple[str, ast.AST, int]]:
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    yield target.id, statement.value, statement.lineno
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value is not None:
            yield statement.target.id, statement.value, statement.lineno


def _route_path(function: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call) or not decorator.args:
            continue
        parts = _call_parts(decorator.func)
        if not parts or parts[-1].casefold() not in {"get", "post", "put", "patch", "delete", "api_route"}:
            continue
        first = decorator.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    return None


def _has_authenticated_dependency(function: ast.AST) -> bool:
    return any(
        isinstance(call, ast.Call)
        and _call_parts(call.func)[-1:] == ("Depends",)
        and bool(call.args)
        and _call_parts(call.args[0])[-1:] == ("require_user",)
        for call in ast.walk(function)
    )


def _has_entitlement_evidence(function: ast.AST) -> bool:
    for child in ast.walk(function):
        if isinstance(child, ast.Call):
            parts = _call_parts(child.func)
            if parts and parts[-1] in _ENTITLEMENT_EVIDENCE_CALLS:
                return True
            if parts[-1:] == ("BureauCatalogAccessContext",):
                return True
    return False


def _python_scan(relative: str, text: str, digest: str) -> list[Finding]:
    try:
        tree = ast.parse(text, filename=relative)
    except (SyntaxError, ValueError):
        return [Finding(RULE_SCAN_INPUT, relative, digest)]
    findings: list[Finding] = []
    for line, value in _python_executable_strings(tree):
        if _is_production_logic(relative) and (
            _WINDOWS_USER_PROFILE.search(value) or _POSIX_USER_PROFILE.search(value)
        ):
            findings.append(Finding(RULE_HARDCODED_USER_PROFILE, relative, digest, line))
        if _is_production_logic(relative) and any(pattern.search(value) for pattern in _LIVE_ACCEPTANCE_PATTERNS):
            findings.append(Finding(RULE_LIVE_ACCEPTANCE_ID, relative, digest, line))
    if not _is_production_logic(relative) or not _is_catalog_related_path(relative):
        return findings

    for function in (
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        route = _route_path(function)
        if _BULK_CATALOG_SURFACE.search(function.name):
            findings.append(Finding(RULE_UNBOUNDED_CATALOG_SURFACE, relative, digest, function.lineno))
        if route is not None and "bureau-catalog" in route.casefold():
            if not _has_authenticated_dependency(function):
                findings.append(Finding(RULE_CATALOG_AUTHENTICATION, relative, digest, function.lineno))
            if not _has_entitlement_evidence(function):
                findings.append(Finding(RULE_CATALOG_ENTITLEMENT, relative, digest, function.lineno))
            if _BULK_CATALOG_SURFACE.search(route):
                findings.append(Finding(RULE_UNBOUNDED_CATALOG_SURFACE, relative, digest, function.lineno))
        if function.name.casefold() in _FALLBACK_IDENTIFIERS:
            findings.append(Finding(RULE_CATALOG_FALLBACK, relative, digest, function.lineno))
        names = {name.casefold() for name in _identifier_names(function)}
        target_informed = any("fuzzy" in name or "semantic" in name for name in names)
        mutation_calls = {
            (_call_parts(child.func)[-1] if _call_parts(child.func) else "").casefold()
            for child in ast.walk(function)
            if isinstance(child, ast.Call)
        }
        authority_mutation = any(
            any(
                call_name == verb
                or call_name.startswith(verb + "_")
                or call_name.endswith("_" + verb)
                for verb in _AUTHORITY_MUTATION_CALLS
            )
            for call_name in mutation_calls
        )
        authoritative_assignment = False
        if target_informed:
            for assignment in ast.walk(function):
                if not isinstance(assignment, (ast.Assign, ast.AnnAssign)):
                    continue
                value = assignment.value
                if isinstance(value, ast.Constant) and value.value is False:
                    continue
                targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
                target_names = {
                    name.casefold()
                    for target in targets
                    for name in _identifier_names(target)
                }
                value_names = {name.casefold() for name in _identifier_names(value)}
                value_strings = {
                    child.value.casefold()
                    for child in ast.walk(value)
                    if isinstance(child, ast.Constant) and isinstance(child.value, str)
                }
                authority_target = any(
                    token in name
                    for name in target_names
                    for token in ("authoritative", "accepted", "confirmed", "exact_match", "persisted")
                )
                fuzzy_value = any(
                    "fuzzy" in name or "semantic" in name for name in value_names
                )
                authority_value = bool(
                    value_strings.intersection(
                        {"accepted", "authoritative", "confirmed", "exact_match", "persisted"}
                    )
                )
                if (authority_target and fuzzy_value) or authority_value:
                    authoritative_assignment = True
                    break
        if target_informed and (authority_mutation or authoritative_assignment):
            findings.append(Finding(RULE_FUZZY_AUTHORITY, relative, digest, function.lineno))

    for name, value, line in _module_assignments(tree):
        if _numeric_meaning_pairs(value) >= 2:
            findings.append(Finding(RULE_GLOBAL_SPECIAL_MEANING, relative, digest, line))
        if isinstance(value, ast.DictComp) and re.search(r"(?:special|sentinel|meaning|code)", name, re.IGNORECASE):
            findings.append(Finding(RULE_GLOBAL_SPECIAL_MEANING, relative, digest, line))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            parts = _call_parts(node.func)
            if parts and parts[-1].casefold() in _FALLBACK_IDENTIFIERS:
                findings.append(Finding(RULE_CATALOG_FALLBACK, relative, digest, node.lineno))
            if parts and _BULK_CATALOG_SURFACE.search(parts[-1]):
                findings.append(Finding(RULE_UNBOUNDED_CATALOG_SURFACE, relative, digest, node.lineno))
        elif isinstance(node, ast.Subscript):
            names = {name.casefold() for name in _identifier_names(node.value)}
            if not (
                names.intersection(_CATALOG_COLLECTION_NAMES)
                or any("catalog" in name or "manifest" in name for name in names)
            ):
                continue
            index = node.slice
            first = isinstance(index, ast.Constant) and index.value == 0
            last = isinstance(index, ast.UnaryOp) and isinstance(index.op, ast.USub) and isinstance(index.operand, ast.Constant) and index.operand.value == 1
            if first or last:
                findings.append(Finding(RULE_CATALOG_FALLBACK, relative, digest, node.lineno))
    return findings


def _mask_javascript_comments(text: str) -> str:
    """Mask JS/TS comments while preserving strings and newline positions."""

    result = list(text)
    index = 0
    quote: str | None = None
    escaped = False
    while index < len(text):
        current = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif current == "\\":
                escaped = True
            elif current == quote:
                quote = None
            index += 1
            continue
        if current in {"'", '"', "`"}:
            quote = current
            index += 1
            continue
        if text.startswith("//", index):
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            for position in range(index, end):
                result[position] = " "
            index = end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = len(text) if end < 0 else end + 2
            for position in range(index, end):
                if result[position] not in {"\r", "\n"}:
                    result[position] = " "
            index = end
            continue
        index += 1
    return "".join(result)


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _text_pattern_findings(relative: str, text: str, digest: str) -> list[Finding]:
    if relative.endswith(".py"):
        return _python_scan(relative, text, digest)
    executable = _mask_javascript_comments(text) if PurePosixPath(relative).suffix.casefold() in _FRONTEND_SUFFIXES else text
    findings: list[Finding] = []
    if not _is_production_logic(relative):
        return findings
    for pattern in (_WINDOWS_USER_PROFILE, _POSIX_USER_PROFILE):
        for match in pattern.finditer(executable):
            findings.append(Finding(RULE_HARDCODED_USER_PROFILE, relative, digest, _line_number(executable, match.start())))
    for pattern in _LIVE_ACCEPTANCE_PATTERNS:
        for match in pattern.finditer(executable):
            findings.append(Finding(RULE_LIVE_ACCEPTANCE_ID, relative, digest, _line_number(executable, match.start())))
    if not _is_catalog_related_path(relative) and "bureau-catalog" not in executable.casefold():
        return findings
    if _is_frontend(relative):
        for pattern, code in (
            (_FRONTEND_PHYSICAL_PATH, RULE_FRONTEND_RESTRICTED_PATH),
            (_CLIENT_AUTHORITY, RULE_CLIENT_AUTHORITY),
        ):
            for match in pattern.finditer(executable):
                findings.append(Finding(code, relative, digest, _line_number(executable, match.start())))
    authority_scan = re.sub(
        r"(?i)\b(?:authoritative|persisted|accepted|confirmed|exact[_-]?match)\s*[:=]\s*false\b",
        "safe_negative_authority",
        executable,
    )
    for pattern, code, target in (
        (_BULK_CATALOG_SURFACE, RULE_UNBOUNDED_CATALOG_SURFACE, executable),
        (_FUZZY_AUTHORITY_FORWARD, RULE_FUZZY_AUTHORITY, authority_scan),
        (_FUZZY_AUTHORITY_REVERSE, RULE_FUZZY_AUTHORITY, authority_scan),
        (_CATALOG_POSITIONAL_FALLBACK, RULE_CATALOG_FALLBACK, executable),
    ):
        for match in pattern.finditer(target):
            findings.append(Finding(code, relative, digest, _line_number(target, match.start())))
    if _is_frontend(relative):
        special_object = re.compile(
            r"(?is)\b(?:const|let|var)\s+[A-Za-z0-9_$]*(?:special|sentinel|meaning)[A-Za-z0-9_$]*\s*=\s*\{(?P<body>.{0,4000}?)\}"
        )
        numeric_pair = re.compile(
            r"(?:^|[,\s])(?:[\"'])?[-+]?\d+(?:\.\d+)?(?:[\"'])?\s*:\s*[\"'][^\"']+[\"']"
        )
        for match in special_object.finditer(executable):
            if len(numeric_pair.findall(match.group("body"))) >= 2:
                findings.append(Finding(RULE_GLOBAL_SPECIAL_MEANING, relative, digest, _line_number(executable, match.start())))
    return findings


def _deduplicate(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    unique = {
        (item.code, item.path, item.line, item.content_sha256, item.count): item
        for item in findings
    }
    return tuple(
        unique[key]
        for key in sorted(unique, key=lambda value: (value[0], value[1], value[2] or 0, value[4]))
    )


def scan_source_tree(
    root: Path,
    *,
    tracked_paths: Iterable[str] | None = None,
    vendor_fingerprint_manifest: Path | None = None,
    screenshot_ocr_manifest: Path | None = None,
    require_vendor_fingerprints: bool = True,
    require_screenshot_ocr: bool = True,
    root_label: str = "synthetic-fixture",
) -> dict[str, object]:
    """Scan a source tree without importing it or mutating any repository state."""

    root = root.resolve(strict=True)
    source_inventory = discover_fixture_paths(root) if tracked_paths is None else tracked_paths
    inventory = tuple(sorted(_safe_relative(item) for item in source_inventory))
    fingerprints = _load_fingerprints(vendor_fingerprint_manifest)
    fingerprint_manifest_sha256 = (
        _content_hash(vendor_fingerprint_manifest.resolve(strict=True))
        if vendor_fingerprint_manifest is not None
        else None
    )
    ocr_engine, screenshot_attestations = _load_screenshot_attestations(
        screenshot_ocr_manifest,
        fingerprint_manifest_sha256=fingerprint_manifest_sha256,
    )
    findings: list[Finding] = []
    scanned_text = 0
    screenshot_inventory: list[dict[str, str]] = []
    fingerprint_candidates = 0

    for relative in inventory:
        candidate = root / Path(*PurePosixPath(relative).parts)
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            findings.append(Finding(RULE_SCAN_INPUT, relative))
            continue
        try:
            resolved.relative_to(root)
        except ValueError:
            findings.append(Finding(RULE_TRACKED_PATH_ESCAPE, relative))
            continue
        if not resolved.is_file():
            findings.append(Finding(RULE_SCAN_INPUT, relative))
            continue
        digest = _content_hash(resolved)
        suffix = PurePosixPath(relative).suffix.casefold()
        if _is_restricted_artifact_path(relative):
            findings.append(Finding(RULE_TRACKED_RESTRICTED_ARTIFACT, relative, digest))
        if suffix in _SCREENSHOT_SUFFIXES:
            screenshot_inventory.append({"path": relative, "content_sha256": digest})
            attestation = screenshot_attestations.get(relative)
            if attestation is None or attestation[0] != digest:
                if require_screenshot_ocr:
                    findings.append(Finding(RULE_SCREENSHOT_OCR_COVERAGE, relative, digest))
            elif attestation[1] > 0:
                findings.append(Finding(RULE_SCREENSHOT_VENDOR_FINGERPRINT, relative, digest, count=attestation[1]))
            continue
        if suffix not in _TEXT_SUFFIXES:
            continue
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            findings.append(Finding(RULE_SCAN_INPUT, relative, digest))
            continue
        scanned_text += 1
        findings.extend(_text_pattern_findings(relative, text, digest))
        if _is_doc_or_test(relative):
            fingerprint_candidates += 1
            match_count = _fingerprint_matches(text, fingerprints)
            if match_count:
                findings.append(Finding(RULE_VENDOR_DESCRIPTION_FINGERPRINT, relative, digest, count=match_count))

    if require_vendor_fingerprints and not fingerprints:
        findings.append(Finding(RULE_VENDOR_FINGERPRINT_COVERAGE, "<scan-inventory>", count=fingerprint_candidates))
    extra_ocr_paths = sorted(set(screenshot_attestations).difference(item["path"] for item in screenshot_inventory))
    for relative in extra_ocr_paths:
        findings.append(Finding(RULE_SCREENSHOT_OCR_COVERAGE, relative))

    result_findings = _deduplicate(findings)
    rule_counts: dict[str, int] = {}
    for finding in result_findings:
        rule_counts[finding.code] = rule_counts.get(finding.code, 0) + finding.count
    screenshot_status = "not-required"
    if screenshot_inventory:
        covered = all(
            item["path"] in screenshot_attestations
            and screenshot_attestations[item["path"]][0] == item["content_sha256"]
            for item in screenshot_inventory
        )
        screenshot_status = "verified-external-ocr" if covered else "not-performed-or-stale"
    return {
        "schema_version": SCHEMA_VERSION,
        "scanner": "restricted-catalog-source-safety",
        "root_label": root_label,
        "inventory_count": len(inventory),
        "text_file_count": scanned_text,
        "vendor_fingerprint": {
            "algorithm": FINGERPRINT_ALGORITHM,
            "configured_count": len(fingerprints),
            "candidate_file_count": fingerprint_candidates,
            "coverage": "verified" if fingerprints else "not-configured",
        },
        "screenshots": {
            "inventory_count": len(screenshot_inventory),
            "ocr_status": screenshot_status,
            "ocr_engine_attested": bool(ocr_engine),
            "items": screenshot_inventory,
        },
        "finding_count": len(result_findings),
        "rule_counts": dict(sorted(rule_counts.items())),
        "findings": [item.payload() for item in result_findings],
        "passed": not result_findings,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only restricted-catalog source-safety scan")
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--inventory-mode",
        choices=("git", "working-tree", "fixture"),
        required=True,
    )
    parser.add_argument("--vendor-fingerprint-manifest")
    parser.add_argument("--screenshot-ocr-manifest")
    parser.add_argument("--allow-missing-vendor-fingerprints", action="store_true")
    parser.add_argument("--allow-unverified-screenshots", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        root = Path(args.root)
        if args.inventory_mode == "git":
            tracked = discover_git_tracked_paths(root)
        elif args.inventory_mode == "working-tree":
            tracked = discover_git_working_tree_source_paths(root)
        else:
            tracked = discover_fixture_paths(root)
        report = scan_source_tree(
            root,
            tracked_paths=tracked,
            vendor_fingerprint_manifest=(Path(args.vendor_fingerprint_manifest) if args.vendor_fingerprint_manifest else None),
            screenshot_ocr_manifest=(Path(args.screenshot_ocr_manifest) if args.screenshot_ocr_manifest else None),
            require_vendor_fingerprints=not args.allow_missing_vendor_fingerprints,
            require_screenshot_ocr=not args.allow_unverified_screenshots,
            root_label={
                "git": "git-index",
                "working-tree": "git-working-tree-source",
                "fixture": "synthetic-fixture",
            }[args.inventory_mode],
        )
    except Exception:  # fail closed without exposing paths or source text
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "scanner": "restricted-catalog-source-safety",
                    "passed": False,
                    "finding_count": 1,
                    "rule_counts": {RULE_SCAN_INPUT: 1},
                    "findings": [{"code": RULE_SCAN_INPUT, "path": "<scan-input>", "count": 1}],
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
