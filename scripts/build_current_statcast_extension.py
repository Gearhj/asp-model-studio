from __future__ import annotations

"""Publish and register the bounded 2023--2026 Statcast PA/Gold evidence.

This command only reads the frozen 2019--2024 authorities, normalizes the
separately acquired 2025--2026 Bronze partitions, publishes data outside Git,
and writes registration metadata to the existing ASP Model Studio database.
It contains no estimator, scoring, calibration, or promotion path.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from server.persistence.db import Database
from server.sports_current_statcast.gold import build_current_gold, verify_current_gold
from server.sports_current_statcast.pipeline import build_current_silver, verify_current_silver
from server.sports_datasets.current_statcast import (
    CurrentStatcastDatasetRegistry,
    build_current_statcast_warehouse_manifest,
    current_statcast_partition_descriptor,
)
from server.sports_gold.silver_inputs import resolve_current_silver


DEFAULT_STAGING = Path(r"C:\Users\james\asp-data-staging")


def _historical_pa_descriptors(
    *,
    package_root: Path,
    existing_silver_root: Path,
) -> list[dict[str, Any]]:
    handle = resolve_current_silver(
        existing_silver_root,
        "fact_statcast_plate_appearance",
    )
    if not handle.partitioned:
        raise RuntimeError("frozen Statcast PA authority is unexpectedly unpartitioned")
    publication = json.loads(
        (handle.object_dir / "manifest.json").read_text(encoding="utf-8")
    )
    descriptors: list[dict[str, Any]] = []
    for child in publication["children"]:
        source_partition_id = str(child["sourcePartitionId"])
        day = source_partition_id.rsplit("/", 1)[-1]
        if (
            "/regular/year=2023/" not in f"/{source_partition_id}"
            and "/regular/year=2024/" not in f"/{source_partition_id}"
        ) or not ("2023-03-30" <= day <= "2024-12-31"):
            continue
        child_sha = str(child["childSha256"])
        path = (handle.object_dir / "children" / f"{child_sha}.parquet").resolve()
        relative_path = path.relative_to(package_root.resolve()).as_posix()
        descriptors.append(
            current_statcast_partition_descriptor(
                package_root=package_root,
                relative_path=relative_path,
                partition_id=(
                    f"frozen-silver-pa:{source_partition_id}:sha256:{child_sha}"
                ),
                schema_id="FROZEN_SILVER_FACT_STATCAST_PA_SCHEMA_V1",
                source_lineage=(
                    {
                        "sourceId": f"frozen-silver-child:{source_partition_id}",
                        "sha256": child_sha,
                    },
                    {
                        "sourceId": "frozen-silver-pa-publication",
                        "sha256": handle.manifest_sha256,
                    },
                    {
                        "sourceId": "frozen-silver-pa-registration",
                        "sha256": handle.registration_sha256,
                    },
                ),
                target_eligibility=(
                    "EVIDENCE_ONLY",
                    "QUARANTINED",
                    "NOT_APPROVED_FOR_TRAINING",
                ),
                temporal_classification=(
                    "POINT_IN_TIME_DATE_EXCLUSIVE",
                    "FROZEN_HISTORICAL_AUTHORITY",
                ),
            )
        )
    if not descriptors:
        raise RuntimeError("frozen 2023/2024 Statcast PA partitions were not resolved")
    return descriptors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--legacy-bronze-root",
        type=Path,
        default=DEFAULT_STAGING / "mlb-advanced-bronze-v1",
    )
    parser.add_argument(
        "--current-bronze-root",
        type=Path,
        default=DEFAULT_STAGING / "mlb-current-statcast-bronze-v1",
    )
    parser.add_argument(
        "--existing-silver-root",
        type=Path,
        default=DEFAULT_STAGING / "mlb-silver-v1",
    )
    parser.add_argument(
        "--current-silver-root",
        type=Path,
        default=DEFAULT_STAGING / "mlb-current-statcast-silver-v1",
    )
    parser.add_argument(
        "--existing-gold-root",
        type=Path,
        default=DEFAULT_STAGING / "mlb-gold-v1",
    )
    parser.add_argument(
        "--current-gold-root",
        type=Path,
        default=DEFAULT_STAGING / "mlb-current-statcast-gold-v1",
    )
    parser.add_argument(
        "--exchange-root",
        type=Path,
        default=Path(r"C:\Users\james\asp-model-exchange"),
    )
    parser.add_argument("--package-root", type=Path, default=DEFAULT_STAGING)
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(".runtime/asp-model-studio/persistence/asp_model_studio.db"),
    )
    parser.add_argument("--registered-by", default="current-statcast-local-operator")
    args = parser.parse_args()

    print("CURRENT_STATCAST_STAGE silver_build", flush=True)
    silver = build_current_silver(
        legacy_bronze_root=args.legacy_bronze_root,
        current_bronze_root=args.current_bronze_root,
        existing_silver_root=args.existing_silver_root,
        output_root=args.current_silver_root,
    )
    silver_verification = verify_current_silver(
        args.current_silver_root,
        str(silver["manifestSha256"]),
    )
    print("CURRENT_STATCAST_STAGE silver_verified", flush=True)
    print("CURRENT_STATCAST_STAGE warehouse_build", flush=True)
    historical_descriptors = _historical_pa_descriptors(
        package_root=args.package_root,
        existing_silver_root=args.existing_silver_root,
    )
    validated = build_current_statcast_warehouse_manifest(
        args.package_root,
        Path(str(silver["manifestPath"])),
        extra_partitions=historical_descriptors,
        include_current_receipts=True,
        current_silver_root=args.current_silver_root,
        limitations=(
            {
                "description": "This registration exposes exact PA evidence and the authorized temporal coverage; no model was fitted, scored, selected, or promoted.",
                "limitationId": "CURRENT_STATCAST_PA_EVIDENCE_NO_FIT",
                "scope": "MODELING",
            },
            {
                "description": "Statcast source rights permit bounded local research; commercial use and raw redistribution require separate review.",
                "limitationId": "CURRENT_STATCAST_RIGHTS_REVIEW_REQUIRED",
                "scope": "RIGHTS",
            },
        ),
    )
    database = Database(args.database)
    database.initialize()
    registration = CurrentStatcastDatasetRegistry(database).register(
        validated,
        user_id=args.registered_by,
    )
    print("CURRENT_STATCAST_STAGE warehouse_registered", flush=True)
    print("CURRENT_STATCAST_STAGE gold_build", flush=True)
    gold = build_current_gold(
        current_silver_root=args.current_silver_root,
        existing_silver_root=args.existing_silver_root,
        existing_gold_root=args.existing_gold_root,
        exchange_root=args.exchange_root,
        output_root=args.current_gold_root,
    )
    gold_verification = verify_current_gold(args.current_gold_root)
    print("CURRENT_STATCAST_STAGE gold_verified", flush=True)

    print(
        json.dumps(
            {
                "silver": silver_verification,
                "gold": gold_verification,
                "goldFeatureAvailability": gold["featureAvailability"],
                "registration": {
                    "datasetId": registration["dataset_id"],
                    "datasetVersionId": registration["dataset_version_id"],
                    "dateCoverage": validated.manifest["dateCoverage"],
                    "manifestSha": registration["manifest_sha"],
                    "modelFitOccurred": False,
                    "modelingStatus": "EVIDENCE_REGISTERED_NO_FIT",
                    "registrationDisposition": registration["registration_disposition"],
                    "registrationId": registration["registration_id"],
                    "validationStatus": registration["validation_status"],
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
