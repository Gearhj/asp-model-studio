import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_acquisition_is_bounded_and_avoids_nba_stats():
    plan = json.loads((ROOT / "docs/nba-gen2-production-readiness-v1/ACQUISITION_PLAN.json").read_text())
    addendum = json.loads((ROOT / "docs/nba-gen2-production-readiness-v1/ACQUISITION_ADDENDUM.json").read_text())
    assert plan["limits"]["maximumResponseBytes"] == 256 * 1024 * 1024
    assert addendum["plannedTotalSuccessfulRequests"] == 16
    assert addendum["totalSuccessfulRequestCeilingIncludingFirstResponse"] == 20
    assert addendum["nbaComRequests"] == 0


def test_staged_package_is_inactive_and_hashes_reconcile():
    current = json.loads((ROOT / "outputs/nba-production-readiness-v1/current.json").read_text())
    index_path = Path(current["index"]["path"])
    raw = index_path.read_bytes()
    import hashlib
    assert hashlib.sha256(raw).hexdigest() == current["packageAddress"]
    index = json.loads(raw)
    for member in index["members"]:
        path = index_path.parent / member["relativePath"]
        payload = path.read_bytes()
        assert len(payload) == member["bytes"]
        assert hashlib.sha256(payload).hexdigest() == member["sha256"]
    manifest = json.loads((index_path.parent / "manifest.json").read_text())
    assert manifest["status"] == "STAGED_INACTIVE"
    assert manifest["authority"]["currentlyActive"] is False
    assert manifest["authority"]["wageringAuthority"] is False
    scheduler = json.loads((index_path.parent / "SCHEDULER_STAGING.json").read_text())
    assert scheduler["status"] == "NOT_INSTALLED"
    assert scheduler["ownerCount"] == 0

