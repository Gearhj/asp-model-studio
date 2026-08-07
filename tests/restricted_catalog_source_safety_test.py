"""Hermetic tests for the read-only restricted-catalog source-safety scanner."""
from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_restricted_catalog_source_safety import (  # noqa: E402
    FINGERPRINT_ALGORITHM,
    RULE_CATALOG_AUTHENTICATION,
    RULE_CATALOG_ENTITLEMENT,
    RULE_CATALOG_FALLBACK,
    RULE_CLIENT_AUTHORITY,
    RULE_FRONTEND_RESTRICTED_PATH,
    RULE_FUZZY_AUTHORITY,
    RULE_GLOBAL_SPECIAL_MEANING,
    RULE_HARDCODED_USER_PROFILE,
    RULE_LIVE_ACCEPTANCE_ID,
    RULE_SCREENSHOT_OCR_COVERAGE,
    RULE_SCREENSHOT_VENDOR_FINGERPRINT,
    RULE_TRACKED_RESTRICTED_ARTIFACT,
    RULE_UNBOUNDED_CATALOG_SURFACE,
    RULE_VENDOR_DESCRIPTION_FINGERPRINT,
    RULE_VENDOR_FINGERPRINT_COVERAGE,
    description_fingerprint,
    discover_git_working_tree_source_paths,
    main,
    scan_source_tree,
)


_SYNTHETIC_DESCRIPTION = (
    "Synthetic restricted definition used only to prove fingerprint isolation behavior."
)


def _write(root: Path, relative: str, payload: str | bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(textwrap.dedent(payload), encoding="utf-8", newline="\n")
    return path


def _fingerprint_manifest(root: Path) -> Path:
    fingerprint = description_fingerprint(_SYNTHETIC_DESCRIPTION)
    return _write(
        root,
        "safe-input/fingerprints.json",
        json.dumps(
            {
                "schema_version": 1,
                "algorithm": FINGERPRINT_ALGORITHM,
                "fingerprints": [
                    {
                        "sha256": fingerprint.sha256,
                        "token_count": fingerprint.token_count,
                    }
                ],
            },
            sort_keys=True,
        ),
    )


def _codes(report: dict[str, object]) -> set[str]:
    findings = report["findings"]
    assert isinstance(findings, list)
    return {str(item["code"]) for item in findings if isinstance(item, dict)}


@contextmanager
def _temporary_test_root():
    """Create a writable fixture root without Windows owner-only temp ACLs.

    The hermetic launcher can run under a restricted-token SID that cannot
    create children beneath ``TemporaryDirectory``'s owner-only directory.
    A normal directory inside the preserved child authority is both isolated
    and writable; it intentionally remains as regression evidence.
    """

    hermetic_root = str(os.environ.get("ATLAS_HERMETIC_ROOT") or "").strip()
    if hermetic_root:
        root = (
            Path(hermetic_root)
            / "authorities"
            / "source-safety-fixtures"
            / uuid.uuid4().hex
        )
        root.mkdir(parents=True, exist_ok=False)
        yield root
        return
    with tempfile.TemporaryDirectory(prefix="atlas-source-safety-") as raw_root:
        yield Path(raw_root)


class RestrictedCatalogSourceSafetyTest(unittest.TestCase):
    def test_working_tree_inventory_scans_untracked_source_but_excludes_only_root_inputs(self) -> None:
        payload = (
            "src/safe.ts\0"
            "tests/new_test.py\0"
            "credit_bureau_premier.csv\0"
            "Experian_Premier_Credit_Bureau.pdf\0"
            "public/copied-provider.csv\0"
        ).encode("utf-8")
        with patch(
            "scripts.check_restricted_catalog_source_safety.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0,
                stdout=payload,
                stderr=b"",
            ),
        ):
            inventory = discover_git_working_tree_source_paths(Path("synthetic-root"))
        self.assertEqual(
            inventory,
            (
                "public/copied-provider.csv",
                "src/safe.ts",
                "tests/new_test.py",
            ),
        )

    def test_strict_vendor_fingerprint_coverage_fails_closed_when_unconfigured(self) -> None:
        with _temporary_test_root() as root:
            note = _write(root, "docs/catalog-safety.md", "Synthetic safe documentation only.")
            report = scan_source_tree(root, tracked_paths=(note.relative_to(root).as_posix(),))
            self.assertFalse(report["passed"])
            self.assertIn(RULE_VENDOR_FINGERPRINT_COVERAGE, _codes(report))
            self.assertEqual(report["vendor_fingerprint"]["coverage"], "not-configured")

    def test_safe_authenticated_entitled_fixture_passes(self) -> None:
        with _temporary_test_root() as root:
            manifest = _fingerprint_manifest(root)
            _write(
                root,
                "server/bureau_metadata/catalog_router.py",
                """
                from fastapi import APIRouter, Depends
                router = APIRouter()

                @router.get("/bureau-catalogs/{catalog_version_id}/attributes")
                def search_catalog(catalog_version_id, user=Depends(require_user)):
                    return service.search_attributes(
                        principal_id=user["id"],
                        catalog_version_id=catalog_version_id,
                    )
                """,
            )
            _write(root, "docs/catalog-safety.md", "Synthetic safe documentation only.")
            report = scan_source_tree(
                root,
                vendor_fingerprint_manifest=manifest,
                require_screenshot_ocr=True,
            )
            self.assertTrue(report["passed"])
            self.assertEqual(report["findings"], [])
            self.assertEqual(report["screenshots"]["ocr_status"], "not-required")

    def test_tracked_vendor_inputs_and_normalized_artifacts_are_path_only_findings(self) -> None:
        with _temporary_test_root() as root:
            manifest = _fingerprint_manifest(root)
            source = _write(root, "credit_bureau_premier.csv", b"synthetic-binary-payload")
            source_pdf = _write(root, "experian_premier_credit_bureau.pdf", b"synthetic-pdf-payload")
            normalized = _write(root, "restricted/catalog_manifest.json", "{}")
            report = scan_source_tree(
                root,
                tracked_paths=(
                    source.relative_to(root).as_posix(),
                    source_pdf.relative_to(root).as_posix(),
                    normalized.relative_to(root).as_posix(),
                ),
                vendor_fingerprint_manifest=manifest,
            )
            self.assertIn(RULE_TRACKED_RESTRICTED_ARTIFACT, _codes(report))
            rendered = json.dumps(report, sort_keys=True)
            self.assertNotIn("synthetic-binary-payload", rendered)
            self.assertTrue(all("content_sha256" in item for item in report["findings"]))

    def test_vendor_description_match_reports_only_fingerprint_count_and_digest(self) -> None:
        with _temporary_test_root() as root:
            manifest = _fingerprint_manifest(root)
            note = _write(
                root,
                "docs/copied-description.md",
                "A prefix. " + _SYNTHETIC_DESCRIPTION + " A suffix.",
            )
            report = scan_source_tree(
                root,
                tracked_paths=(note.relative_to(root).as_posix(),),
                vendor_fingerprint_manifest=manifest,
            )
            self.assertIn(RULE_VENDOR_DESCRIPTION_FINGERPRINT, _codes(report))
            rendered = json.dumps(report, sort_keys=True)
            self.assertNotIn(_SYNTHETIC_DESCRIPTION, rendered)
            finding = next(
                item
                for item in report["findings"]
                if item["code"] == RULE_VENDOR_DESCRIPTION_FINGERPRINT
            )
            self.assertEqual(
                set(finding),
                {"code", "path", "count", "content_sha256"},
            )

    def test_screenshot_inventory_fails_closed_without_ocr_and_accepts_text_free_attestation(self) -> None:
        with _temporary_test_root() as root:
            manifest = _fingerprint_manifest(root)
            screenshot = _write(root, "docs/screenshots/catalog.png", b"synthetic-image")
            relative = screenshot.relative_to(root).as_posix()
            digest = hashlib.sha256(screenshot.read_bytes()).hexdigest()
            uncovered = scan_source_tree(
                root,
                tracked_paths=(relative,),
                vendor_fingerprint_manifest=manifest,
            )
            self.assertIn(RULE_SCREENSHOT_OCR_COVERAGE, _codes(uncovered))
            self.assertEqual(
                uncovered["screenshots"]["ocr_status"],
                "not-performed-or-stale",
            )

            safe_attestation = _write(
                root,
                "safe-input/ocr.json",
                json.dumps(
                    {
                        "schema_version": 1,
                        "engine": "synthetic-ocr-attestation",
                        "fingerprint_algorithm": FINGERPRINT_ALGORITHM,
                        "fingerprint_manifest_sha256": hashlib.sha256(
                            manifest.read_bytes()
                        ).hexdigest(),
                        "records": [
                            {
                                "path": relative,
                                "content_sha256": digest,
                                "vendor_fingerprint_matches": 0,
                            }
                        ],
                    },
                    sort_keys=True,
                ),
            )
            covered = scan_source_tree(
                root,
                tracked_paths=(relative,),
                vendor_fingerprint_manifest=manifest,
                screenshot_ocr_manifest=safe_attestation,
            )
            self.assertTrue(covered["passed"])
            self.assertEqual(covered["screenshots"]["ocr_status"], "verified-external-ocr")

            unsafe_payload = json.loads(safe_attestation.read_text(encoding="utf-8"))
            unsafe_payload["records"][0]["vendor_fingerprint_matches"] = 2
            safe_attestation.write_text(json.dumps(unsafe_payload), encoding="utf-8")
            matched = scan_source_tree(
                root,
                tracked_paths=(relative,),
                vendor_fingerprint_manifest=manifest,
                screenshot_ocr_manifest=safe_attestation,
            )
            self.assertIn(RULE_SCREENSHOT_VENDOR_FINGERPRINT, _codes(matched))

    def test_catalog_routes_require_authentication_entitlement_and_bounded_operations(self) -> None:
        with _temporary_test_root() as root:
            manifest = _fingerprint_manifest(root)
            router = _write(
                root,
                "server/bureau_metadata/unsafe_catalog_router.py",
                """
                from fastapi import APIRouter, Depends
                router = APIRouter()

                @router.get("/bureau-catalogs/{catalog_version_id}/attributes")
                def unauthenticated(catalog_version_id):
                    return registry.get_version(catalog_version_id)

                @router.get("/bureau-catalogs/{catalog_version_id}/raw")
                def entitlement_missing(catalog_version_id, user=Depends(require_user)):
                    return registry.get_version(catalog_version_id)

                @router.get("/bureau-catalogs/{catalog_version_id}/export")
                def export_all(catalog_version_id, user=Depends(require_user)):
                    return service.search_attributes(catalog_version_id=catalog_version_id)
                """,
            )
            report = scan_source_tree(
                root,
                tracked_paths=(router.relative_to(root).as_posix(),),
                vendor_fingerprint_manifest=manifest,
            )
            codes = _codes(report)
            self.assertTrue(
                {
                    RULE_CATALOG_AUTHENTICATION,
                    RULE_CATALOG_ENTITLEMENT,
                    RULE_UNBOUNDED_CATALOG_SURFACE,
                }.issubset(codes)
            )

    def test_fuzzy_authority_global_special_meanings_and_fallback_are_rejected(self) -> None:
        with _temporary_test_root() as root:
            manifest = _fingerprint_manifest(root)
            source = _write(
                root,
                "server/bureau_metadata/unsafe_catalog_policy.py",
                """
                SPECIAL_VALUE_MEANINGS = {-9: "synthetic-a", -8: "synthetic-b"}

                def accept_semantic_match(fuzzy):
                    persist(fuzzy)

                def get_latest_catalog(catalogs):
                    return catalogs[0]
                """,
            )
            report = scan_source_tree(
                root,
                tracked_paths=(source.relative_to(root).as_posix(),),
                vendor_fingerprint_manifest=manifest,
            )
            self.assertTrue(
                {
                    RULE_FUZZY_AUTHORITY,
                    RULE_GLOBAL_SPECIAL_MEANING,
                    RULE_CATALOG_FALLBACK,
                }.issubset(_codes(report))
            )

    def test_frontend_physical_paths_client_authority_bulk_and_live_ids_are_rejected(self) -> None:
        with _temporary_test_root() as root:
            manifest = _fingerprint_manifest(root)
            live_project = "atlas-" + "mrzpau4t"
            source = _write(
                root,
                "src/bureauCatalogUnsafe.ts",
                f'''
                const catalogRoot = "C:/Users/synthetic/restricted-catalog/registry.db";
                localStorage.setItem("catalog-entitlement", "authorized");
                const selected = catalogs[0];
                function downloadFullCatalog() {{ return selected; }}
                const acceptanceProject = "{live_project}";
                ''',
            )
            report = scan_source_tree(
                root,
                tracked_paths=(source.relative_to(root).as_posix(),),
                vendor_fingerprint_manifest=manifest,
            )
            expected_codes = {
                    RULE_FRONTEND_RESTRICTED_PATH,
                    RULE_HARDCODED_USER_PROFILE,
                    RULE_CLIENT_AUTHORITY,
                    RULE_UNBOUNDED_CATALOG_SURFACE,
                    RULE_CATALOG_FALLBACK,
                    RULE_LIVE_ACCEPTANCE_ID,
                }
            observed_codes = _codes(report)
            self.assertTrue(
                expected_codes.issubset(observed_codes),
                sorted(expected_codes - observed_codes),
            )

    def test_api_user_routes_are_not_misclassified_as_posix_profile_paths(self) -> None:
        with _temporary_test_root() as root:
            manifest = _fingerprint_manifest(root)
            source = _write(
                root,
                "src/api.ts",
                '''
                const currentUser = "/users/current";
                const updateRole = "/admin/users/{user_id}/role";
                ''',
            )
            report = scan_source_tree(
                root,
                tracked_paths=(source.relative_to(root).as_posix(),),
                vendor_fingerprint_manifest=manifest,
            )
            self.assertNotIn(RULE_HARDCODED_USER_PROFILE, _codes(report))

    def test_posix_home_profile_paths_remain_rejected(self) -> None:
        with _temporary_test_root() as root:
            manifest = _fingerprint_manifest(root)
            source = _write(
                root,
                "src/unsafe.ts",
                '''
                const linuxPath = "/home/synthetic/catalog.db";
                const macPath = "/Users/synthetic/catalog.db";
                ''',
            )
            report = scan_source_tree(
                root,
                tracked_paths=(source.relative_to(root).as_posix(),),
                vendor_fingerprint_manifest=manifest,
            )
            self.assertIn(RULE_HARDCODED_USER_PROFILE, _codes(report))

    def test_cli_failure_output_never_contains_matched_text_or_absolute_root(self) -> None:
        with _temporary_test_root() as root:
            manifest = _fingerprint_manifest(root)
            _write(root, "tests/copied.txt", _SYNTHETIC_DESCRIPTION)
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--root",
                        str(root),
                        "--inventory-mode",
                        "fixture",
                        "--vendor-fingerprint-manifest",
                        str(manifest),
                    ]
                )
            rendered = output.getvalue()
            self.assertEqual(exit_code, 1)
            self.assertNotIn(_SYNTHETIC_DESCRIPTION, rendered)
            self.assertNotIn(str(root), rendered)
            payload = json.loads(rendered)
            self.assertFalse(payload["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
