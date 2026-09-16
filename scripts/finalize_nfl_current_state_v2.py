"""Publish/register an already completed study; this command never fits."""
import argparse
import json
import platform
from pathlib import Path

import joblib
import pandas as pd
import numpy as np
import pyarrow
import scipy
import sklearn

from server.sports_nfl_m1.current_state_study import OUTPUT, EVIDENCE, publish_json
from server.sports_nfl_m1.current_state_publication import publish_current_v2
from server.sports_nfl_m1.current_state_market_comparison import prepare_market_comparison
from server.sports_nfl_m1.current_state_play_comparison import compare_current_with_play_base
from server.sports_nfl_m1.current_state_registration import register_study
from server.sports_nfl_m1.forward_vintages import _pointer
from server.sports_nfl_m1.labs_simulation import file_record, verify_object


def finalize(result_path):
    result_path = Path(result_path).resolve()
    if not result_path.is_relative_to((OUTPUT / "runs").resolve()):
        raise ValueError("completed dedicated V2 study path required")
    result = json.loads(result_path.read_bytes())
    if result.get("finalOotAccessed") is not False or not result.get("completedAtUtc"):
        raise ValueError("completed Development-only study required")
    for ref in result["artifacts"]:
        if file_record(Path(ref["path"])) != ref:
            raise ValueError("fitted study artifact changed")
    result_ref = file_record(result_path)
    declaration = json.loads(Path(result["declaration"]["path"]).read_bytes())
    team = pd.read_parquet(result_path.parent / "sufficient-statistics-team.parquet")
    qb = pd.read_parquet(result_path.parent / "sufficient-statistics-qb.parquet")
    fitted = joblib.load(result["finalModel"]["path"])
    publication = publish_current_v2(fitted, team, qb, result["finalModel"], result_ref,
        OUTPUT / "current-publication", source_receipt=declaration["sourceEvidence"],
        ensemble_weight=result["finalEnsembleResidualWeight"])
    handoff = json.loads(Path(publication["handoff"]["path"]).read_bytes())
    manifest = json.loads(Path(publication["manifest"]["path"]).read_bytes())
    for ref in manifest["files"]:
        if file_record(Path(ref["path"])) != ref:
            raise ValueError("publication checksum/byte count mismatch")
    for artifact in handoff["artifacts"]:
        verify_object(artifact)
    market = prepare_market_comparison(publication["handoff"], OUTPUT / "prospective-market-comparison")
    play_comparison = compare_current_with_play_base(publication["handoff"], OUTPUT / "independent-play-comparison")
    registration = register_study(result_ref, publication["handoff"])
    registration_repeat = register_study(result_ref, publication["handoff"])
    if registration_repeat["status"] != "NO_OP":
        raise ValueError("registration was not idempotent")
    _pointer(OUTPUT / "CURRENT.json", {"status":"COMPLETED","evidenceClass":EVIDENCE,
        "result":result_ref,"runId":result["runId"],"publication":publication["handoff"],"marketComparison":market["comparison"]})
    delivery = {"contract":"NFL_CURRENT_STATE_V2_DELIVERY_RECEIPT","evidenceClass":EVIDENCE,
        "study":result_ref,"publication":publication,"marketComparison":market,"registration":registration,
        "independentPlayComparison":play_comparison,
        "runtimeVersions":{"python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__,
            "pyarrow":pyarrow.__version__,"scipy":scipy.__version__,"scikitLearn":sklearn.__version__,
            "joblib":joblib.__version__,"platform":platform.platform()},
        "registrationRerun":registration_repeat,"verification":{"allPublicationChecksumsValid":True,
            "allScoreDistributionObjectsValid":True,"finalOotRead":False,"aispWrites":0,"providerCalls":0,"modelFits":0}}
    ref = publish_json(OUTPUT / "deliveries", "delivery.json", delivery)
    print(json.dumps({"delivery":ref,**delivery},indent=2),flush=True)
    return ref


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    finalize(parser.parse_args().result)
