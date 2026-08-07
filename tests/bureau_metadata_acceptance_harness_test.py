from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from contextlib import contextmanager
from typing import Any, Iterator, Mapping
import uuid

import pytest

from scripts import validate_bureau_metadata_catalog as acceptance
from server.bureau_metadata.csv_parser import CsvParseResult
from server.bureau_metadata.pdf_parser import PdfParseResult
from server.bureau_metadata.source_reader import SourceDescriptor


@contextmanager
def _external_test_root() -> Iterator[Path]:
    # tempfile.TemporaryDirectory applies POSIX-style 0700 permissions that
    # translate into an unusable ACL under some Windows runners.  An ordinary
    # explicit Temp child retains the runner ACL while remaining outside the
    # repository, as production source isolation requires.
    root = Path(tempfile.gettempdir()) / f"atlas-bureau-acceptance-{uuid.uuid4().hex}"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _descriptor(path: Path) -> SourceDescriptor:
    payload = path.read_bytes()
    return SourceDescriptor(
        path=path.resolve(),
        filename=path.name,
        suffix=path.suffix,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _synthetic_record() -> dict[str, object]:
    # These values are deliberately synthetic.  The acceptance summary must
    # never reproduce them, which proves the harness emits aggregates only.
    return {
        "attribute_sequence": "1",
        "source_sequence": "1",
        "attribute_code": "SYN001",
        "description": "Licensed synthetic description must stay restricted",
        "units": "count",
        "field_length": "3",
        "numeric_type": "integer",
        "valid_value_expression": "0-100",
        "staging_ordinary_min": "0",
        "staging_ordinary_max": "100",
        "special_value_definitions_raw": (
            "98: Licensed synthetic exception must stay restricted"
        ),
        "versions": "1",
        "cross_bureau_availability": "",
        "leveling_indicator": "",
        "archive_indicator": "",
        "equifax_availability": "",
        "transunion_availability": "",
        "leveling_status": "",
        "archive_availability": "",
        "source_page": 1,
        "extraction_method": "pdf_text",
        "extraction_confidence": "high",
    }


def _install_synthetic_parsers(
    monkeypatch: pytest.MonkeyPatch,
    pdf_path: Path,
    csv_path: Path,
) -> None:
    pdf_source = _descriptor(pdf_path)
    csv_source = _descriptor(csv_path)
    record = _synthetic_record()

    def fake_pdf(*_args: Any, **_kwargs: Any) -> PdfParseResult:
        return PdfParseResult(
            source=pdf_source,
            records=(dict(record),),
            findings=(),
            pages_processed=1,
            pages_without_text=0,
            extraction_method="pdf_text",
            ocr_used=False,
            table_rows_examined=1,
            table_rows_skipped=0,
        )

    def fake_csv(*_args: Any, **_kwargs: Any) -> CsvParseResult:
        return CsvParseResult(
            source=csv_source,
            headers=("attribute_code",),
            records=(dict(record),),
            findings=(),
            rows_processed=1,
            date_conversion_detections=0,
        )

    monkeypatch.setattr(acceptance.builder_module, "parse_pdf", fake_pdf)
    monkeypatch.setattr(acceptance.builder_module, "parse_csv", fake_csv)


def _settings(root: Path) -> acceptance.AcceptanceSettings:
    source = root / "source"
    source.mkdir()
    pdf = source / "synthetic.pdf"
    csv = source / "synthetic.csv"
    pdf.write_bytes(b"synthetic-pdf-fixture")
    csv.write_text("synthetic,csv,fixture\n", encoding="utf-8")
    output = root / "acceptance-output"
    return acceptance.AcceptanceSettings(
        pdf_path=pdf,
        csv_path=csv,
        output_root=output,
        summary_path=output / "acceptance-summary.json",
        provider="Synthetic Provider",
        product="Synthetic Product",
        edition="Test",
        dictionary_version="1.0",
        policy_id="synthetic-restricted-policy",
        policy_version="1",
        built_by="synthetic-acceptance-test",
        source_control_commit="synthetic-test-commit",
        built_at="2026-08-05T00:00:00Z",
    )


def _assert_sane_operation_latency(metrics: Mapping[str, Any]) -> None:
    required = {
        "total_ms",
        "minimum_microseconds",
        "mean_microseconds",
        "p95_microseconds",
        "maximum_microseconds",
    }
    assert required.issubset(metrics)
    minimum = metrics["minimum_microseconds"]
    mean = metrics["mean_microseconds"]
    p95 = metrics["p95_microseconds"]
    maximum = metrics["maximum_microseconds"]
    assert metrics["total_ms"] >= 0
    assert 0 <= minimum <= mean <= maximum
    assert minimum <= p95 <= maximum


def test_acceptance_harness_runs_determinism_workloads_and_negative_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _external_test_root() as root:
        settings = _settings(root)
        _install_synthetic_parsers(
            monkeypatch,
            settings.pdf_path,
            settings.csv_path,
        )
        original_runtime = acceptance._run_runtime_workload

        def runtime_without_memory_tracing(**kwargs: Any) -> dict[str, Any]:
            assert acceptance.tracemalloc.is_tracing() is False
            return original_runtime(**kwargs)

        monkeypatch.setattr(
            acceptance,
            "_run_runtime_workload",
            runtime_without_memory_tracing,
        )
        summary = acceptance.run_acceptance(
            settings,
            workload=acceptance.AcceptanceWorkload(
                reload_count=5,
                exact_lookup_count=250,
                classification_count=300,
                reader_workers=8,
                concurrent_operations_per_worker=4,
            ),
        )

        assert summary["ok"] is True
        assert summary["deterministic_builds"]["completed"] == 3
        assert summary["deterministic_builds"]["catalog_checksums_equal"] is True
        assert summary["deterministic_builds"]["artifact_hashes_equal"] is True
        assert summary["runtime_workload"]["reloads"]["completed"] == 5
        assert (
            summary["runtime_workload"]["exact_attribute_lookups"]["completed"]
            == 250
        )
        assert (
            summary["runtime_workload"]["value_classifications"]["completed"]
            == 300
        )
        _assert_sane_operation_latency(
            summary["runtime_workload"]["exact_attribute_lookups"]
        )
        _assert_sane_operation_latency(
            summary["runtime_workload"]["value_classifications"]
        )
        assert (
            summary["runtime_workload"]["concurrent_readers"]["workers_completed"]
            == 8
        )
        assert all(summary["integrity_failures"].values())
        assert all(
            value is True
            for key, value in summary["safe_retry"].items()
            if key != "retry_elapsed_ms"
        )
        assert summary["latest_or_first_fallback_used"] is False
        memory = summary["performance"]["memory_measurement"]
        assert memory["scope"] == "one_uncached_exact_reload_only"
        assert memory["reloads_measured"] == 1
        assert memory["included_in_required_100_reload_count"] is False

        saved = json.loads(settings.summary_path.read_text(encoding="utf-8"))
        assert saved["catalog"]["catalog_checksum"] == summary["catalog"][
            "catalog_checksum"
        ]
        rendered = json.dumps(saved, sort_keys=True)
        assert "SYN001" not in rendered
        assert "Licensed synthetic" not in rendered
        assert str(settings.pdf_path) not in rendered
        assert str(settings.csv_path) not in rendered
        assert str(settings.output_root) not in rendered


def _publish_three_synthetic_builds(
    settings: acceptance.AcceptanceSettings,
) -> str:
    settings.output_root.mkdir()
    results, inventories, _ = acceptance._run_clean_builds(
        pdf=settings.pdf_path,
        csv=settings.csv_path,
        output_root=settings.output_root,
        config=settings.build_config(),
        build_function=acceptance.build_catalog,
    )
    assert len(results) == 3
    assert len(inventories) == 3
    return results[0].catalog_checksum


def test_acceptance_resumes_only_after_exact_three_build_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _external_test_root() as root:
        settings = _settings(root)
        _install_synthetic_parsers(
            monkeypatch,
            settings.pdf_path,
            settings.csv_path,
        )
        checksum = _publish_three_synthetic_builds(settings)
        resumed = replace(
            settings,
            resume_completed_builds=True,
            expected_catalog_checksum=checksum,
        )
        summary = acceptance.run_acceptance(
            resumed,
            workload=acceptance.AcceptanceWorkload(
                reload_count=3,
                exact_lookup_count=30,
                classification_count=40,
                reader_workers=8,
                concurrent_operations_per_worker=2,
            ),
        )

        builds = summary["deterministic_builds"]
        assert builds["completed"] == 3
        assert builds["execution_mode"] == "resumed_after_exact_verification"
        assert builds["resumed_after_exact_verification"] is True
        assert builds["timing_scope"] == "resume_exact_integrity_verification"
        assert builds["artifact_hashes_equal"] is True
        assert summary["runtime_workload"]["reloads"]["completed"] == 3


def test_acceptance_resume_rejects_any_unexpected_root_child_before_workload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _external_test_root() as root:
        settings = _settings(root)
        _install_synthetic_parsers(
            monkeypatch,
            settings.pdf_path,
            settings.csv_path,
        )
        checksum = _publish_three_synthetic_builds(settings)
        marker = settings.output_root / "unexpected.marker"
        marker.write_text("preserve", encoding="utf-8")
        resumed = replace(
            settings,
            resume_completed_builds=True,
            expected_catalog_checksum=checksum,
        )

        with pytest.raises(acceptance.CatalogAcceptanceError):
            acceptance.run_acceptance(
                resumed,
                workload=acceptance.AcceptanceWorkload(
                    reload_count=1,
                    exact_lookup_count=1,
                    classification_count=1,
                    reader_workers=1,
                    concurrent_operations_per_worker=1,
                ),
            )

        assert marker.read_text(encoding="utf-8") == "preserve"
        assert not resumed.summary_path.exists()


def test_acceptance_refuses_nonempty_output_without_modifying_it() -> None:
    with _external_test_root() as root:
        settings = _settings(root)
        settings.output_root.mkdir()
        marker = settings.output_root / "preexisting.marker"
        marker.write_text("preserve", encoding="utf-8")

        with pytest.raises(acceptance.CatalogAcceptanceError):
            acceptance.run_acceptance(
                settings,
                workload=acceptance.AcceptanceWorkload(
                    reload_count=1,
                    exact_lookup_count=1,
                    classification_count=1,
                    reader_workers=1,
                    concurrent_operations_per_worker=1,
                ),
            )

        assert marker.read_text(encoding="utf-8") == "preserve"
        assert tuple(settings.output_root.iterdir()) == (marker,)


def test_cli_workload_is_fixed_at_required_acceptance_counts() -> None:
    assert acceptance.DEFAULT_RELOAD_COUNT == 100
    assert acceptance.DEFAULT_LOOKUP_COUNT == 100_000
    assert acceptance.DEFAULT_CLASSIFICATION_COUNT == 100_000
    assert acceptance.DEFAULT_READER_WORKERS == 8
    parser = acceptance._parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert "--reload-count" not in option_strings
    assert "--lookup-count" not in option_strings
    assert "--classification-count" not in option_strings
    assert "--reader-workers" not in option_strings


def test_cli_failure_redacts_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(_settings: acceptance.AcceptanceSettings) -> Mapping[str, Any]:
        raise RuntimeError("licensed source fragment must never be printed")

    monkeypatch.setattr(acceptance, "run_acceptance", fail)
    result = acceptance.main(
        [
            "--pdf",
            "C:/external/source.pdf",
            "--csv",
            "C:/external/source.csv",
            "--output-root",
            "C:/external/output",
            "--summary-json",
            "C:/external/output/summary.json",
            "--provider",
            "P",
            "--product",
            "X",
            "--edition",
            "E",
            "--dictionary-version",
            "1",
            "--policy-id",
            "policy",
            "--policy-version",
            "1",
            "--built-by",
            "actor",
            "--source-control-commit",
            "commit",
        ]
    )
    output = capsys.readouterr().out
    assert result == 2
    assert "licensed source fragment" not in output
    assert "C:/external" not in output
    assert json.loads(output)["error_type"] == "RuntimeError"
