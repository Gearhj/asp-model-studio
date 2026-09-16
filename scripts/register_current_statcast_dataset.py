from __future__ import annotations

"""Validate and register one current-Statcast PA evidence manifest."""

import argparse
import json
from pathlib import Path

from server.persistence.db import Database
from server.sports_datasets.current_statcast import (
    CurrentStatcastDatasetRegistry,
    validate_current_statcast_manifest,
)
from server.sports_datasets.registry import SportsDatasetRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--registered-by", default="current-statcast-local-operator")
    args = parser.parse_args()

    database = Database(args.database)
    database.initialize()
    validated = validate_current_statcast_manifest(
        args.manifest,
        package_root=args.package_root,
    )
    registration = CurrentStatcastDatasetRegistry(database).register(
        validated,
        user_id=args.registered_by,
    )
    public = SportsDatasetRegistry(database).public_dataset(registration)
    print(
        json.dumps(
            {
                "datasetId": public["datasetId"],
                "datasetVersionId": public["datasetVersionId"],
                "dateCoverage": public["dateCoverage"],
                "manifestSha": public["manifestSha"],
                "modelFitOccurred": public["modelFitOccurred"],
                "modelingStatus": public["modelingStatus"],
                "partitionAuthoritySha": public["partitionAuthoritySha"],
                "registrationDisposition": registration["registration_disposition"],
                "registrationId": public["registrationId"],
                "validationStatus": public["validationStatus"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
