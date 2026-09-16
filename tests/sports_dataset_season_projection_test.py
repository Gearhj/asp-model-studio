"""Season metadata projection accepts registered years without inventing counts."""
from contextlib import contextmanager
from copy import deepcopy
import pytest
from server.sports_datasets.registry import SportsDatasetRegistry


class ReadOnlyMetadata:
    def __init__(self): self.queries = []
    @contextmanager
    def connection(self): yield self
    def execute(self, sql, parameters):
        assert sql.lstrip().upper().startswith("SELECT "), "Projection attempted a metadata write"
        self.queries.append((sql, parameters))
        return self
    def fetchall(self): return []
    def fetchone(self): return None
    def transaction(self): raise AssertionError("Projection must not start a write transaction")


def registration(seasons):
    return {"registration_id": "synthetic-companion", "dataset_id": "synthetic.companion", "dataset_version_id": "synthetic-version",
        "manifest_id": "synthetic-manifest", "manifest_sha": "a" * 64, "package_id": "synthetic-package", "sport": "BASEBALL", "league": "MLB",
        "evidence_cutoff": "2026-01-01", "published_at": "2026-01-01T00:00:00Z", "logical_package_root": "asp://synthetic/companion",
        "validation_status": "VALID", "registered_at": "2026-01-01T00:00:00Z", "rights_status": "GOVERNED_LOCAL_RESEARCH_ONLY",
        "limitation_count": 0, "active": 0, "totals_json": {"rows": 7, "bytes": 91}, "seasons_json": deepcopy(seasons),
        "metadata_json": {"authorityState": "COMPANION_ONLY", "workspaceActivationEligible": False, "modelEligible": False}}


@pytest.mark.parametrize("seasons,expected_years,expected_counts", [
    ([2023, 2024, 2025, 2026], [2023, 2024, 2025, 2026], [None, None, None, None]),
    ([{"season": 2024, "games": 0, "plate_appearances": 7, "date_range": {"earliestDate": "2024-01-01", "latestDate": "2024-01-02"}}], [2024], [7]),
    ([2026, {"season": 2023, "plate_appearances": 3}], [2026, 2023], [None, 3]),
    ([], [], []),
], ids=["integer-companion-seasons", "detailed-season-metadata", "mixed-order-preserved", "empty-seasons"])
def test_public_projection_preserves_registered_seasons_and_unknown_counts(seasons, expected_years, expected_counts):
    stored = registration(seasons); before = deepcopy(stored); database = ReadOnlyMetadata()
    projected = SportsDatasetRegistry(database).public_dataset(stored)
    assert projected["seasons"] == expected_years
    assert [row["season"] for row in projected["seasonCoverage"]] == expected_years
    assert [row["plateAppearances"] for row in projected["seasonCoverage"]] == expected_counts
    for source, row in zip(seasons, projected["seasonCoverage"]):
        if type(source) is int:
            assert all(value is None for key, value in row.items() if key != "season")
        elif source.get("date_range"):
            assert row["games"] == 0
            assert row["earliestDate"] == "2024-01-01" and row["latestDate"] == "2024-01-02"
    assert projected["totals"] == before["totals_json"]
    assert projected["manifestSha"] == before["manifest_sha"]
    assert projected["datasetVersionId"] == before["dataset_version_id"]
    assert projected["authorityState"] == "COMPANION_ONLY"
    assert projected["workspaceActivationEligible"] is False
    assert stored == before and len(database.queries) == 6


@pytest.mark.parametrize("invalid", [True, False, 2024.0, "2024"])
def test_projection_does_not_coerce_other_scalars_to_seasons(invalid):
    with pytest.raises(TypeError):
        SportsDatasetRegistry(ReadOnlyMetadata()).public_dataset(registration([invalid]))
