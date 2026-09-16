"""Verify this bounded operational handoff's frozen evidence; no provider/model calls."""
from pathlib import Path
import hashlib
import json


def main():
    root = Path(__file__).resolve().parents[1]
    base = root / "outputs/producer-readiness-20260914-v1"
    index = json.loads((base / "evidence-index.json").read_bytes())
    for item in index["files"]:
        data = (base / item["relativePath"]).read_bytes()
        assert len(data) == item["bytes"], item["relativePath"]
        assert hashlib.sha256(data).hexdigest() == item["sha256"], item["relativePath"]
    mlb = json.loads((base / "mlb-readiness.json").read_bytes())
    assert len(mlb["games"]) == len({g["mlbamGamePk"] for g in mlb["games"]}) == 10
    assert all(not g["checkpoint"]["due"] and not g["currentParticipantsAvailable"] for g in mlb["games"])
    assert all(g["forecastIds"] == [] and g["produced"] == g["published"] == 0 for g in mlb["games"])
    nfl = json.loads((base / "nfl-readiness.json").read_bytes())
    f = nfl["effectiveForecast"]
    assert abs(f["homeWinProbability"] + f["awayWinProbability"] + f["tieProbability"] - 1) < 1e-12
    assert nfl["semanticReuse"]["changedFeatureCount"] == 0
    assert nfl["numericalInputCoverage"]["nonnullFeatureCount"] + nfl["numericalInputCoverage"]["missingFeatureCount"] == 197
    for key in ("currentAuthorityBundle", "originalBundle", "originalFeatureVector", "modelArtifactIncludingFittedPreprocessing", "modelManifest"):
        item = nfl["physicalReferences"][key]
        data = Path(item["path"]).read_bytes()
        assert len(data) == item["bytes"] and hashlib.sha256(data).hexdigest() == item["sha256"], key
    for key in ("localHandoff", "localSlateReceipt", "latestSubstantiveTick"):
        item = mlb[key]
        data = Path(item["path"]).read_bytes()
        assert len(data) == item["bytes"] and hashlib.sha256(data).hexdigest() == item["sha256"], key
    print(json.dumps({"status": "PASS", "frozenEvidenceFiles": len(index["files"]), "unchangedNflOriginalBindings": True, "mlbLocalReceiptBytes": "VERIFIED", "mlbExternalPackage": "OWNER_ATTESTED_ACCESS_DENIED_QUALIFICATION_RETAINED", "providerRequests": 0, "forecastExecutions": 0}))


if __name__ == "__main__":
    main()
