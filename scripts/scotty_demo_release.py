"""Bounded, read-only forecast audit and additive demo-release publication.

This module never selects/fits a model, contacts a provider, edits AISP, or
activates a producer. Source artifacts are referenced with physical hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_shared.content_addressed_package import (
    IDENTITY_ALGORITHM, package_content_sha256, member_records, verify_package_directory,
)

SCHEMA = "ASP_MULTISPORT_DEMO_RELEASE_V1"
DECLARATION = "ASP_RETAINED_CHAMPION_DECLARATION_V1"
NY = ZoneInfo("America/New_York")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def clock(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("NAIVE_CLOCK")
    return result.astimezone(timezone.utc)


def now():
    return datetime.now(timezone.utc).isoformat()


def physical(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def checked(ref):
    actual = physical(ref["path"])
    expected = ref.get("sha256", ref.get("physicalSha256"))
    if actual["sha256"] != expected or actual["bytes"] != ref["bytes"]:
        raise ValueError("PHYSICAL_BINDING_MISMATCH: " + ref["path"])
    return actual


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = canonical(value)
    if path.exists():
        if path.read_bytes() != blob:
            raise ValueError("IMMUTABLE_CONFLICT: " + str(path))
    else:
        with path.open("xb") as handle:
            handle.write(blob)
    return physical(path)


def probabilities(home, away, tie):
    values = (home, away, tie)
    if any(not math.isfinite(x) or x < 0 or x > 1 for x in values):
        raise ValueError("PROBABILITY_UNITS_OR_RANGE")
    if abs(sum(values) - 1) > 1e-9:
        raise ValueError("PROBABILITY_MASS")


def chronology(cut, created, published, kickoff):
    a, b, c, d = map(clock, (cut, created, published, kickoff))
    if not a <= b <= c < d:
        raise ValueError("FORECAST_CHRONOLOGY")
    return {"sourceCutoffUtc": cut, "createdAtUtc": created,
            "publishedAtUtc": published, "scheduledStartUtc": kickoff,
            "scheduledStartEastern": d.astimezone(NY).isoformat()}


def joint_summary(home, away, counts=None):
    import numpy as np
    h, a = np.asarray(home), np.asarray(away)
    c = np.ones(len(h), dtype=np.int64) if counts is None else np.asarray(counts)
    if h.shape != a.shape or h.shape != c.shape or not len(h):
        raise ValueError("JOINT_SHAPE")
    if not all(np.isfinite(x).all() for x in (h, a, c)):
        raise ValueError("JOINT_NONFINITE")
    if (h < 0).any() or (a < 0).any() or (c <= 0).any() or (c != np.floor(c)).any():
        raise ValueError("JOINT_SUPPORT")
    if (h != np.floor(h)).any() or (a != np.floor(a)).any():
        raise ValueError("JOINT_INTEGER_FINAL_SUPPORT")
    n = int(c.sum())
    return {"drawCount": n, "expectedHome": float(h @ c / n),
            "expectedAway": float(a @ c / n), "expectedTotal": float((h+a) @ c/n),
            "homeWin": float(c[h>a].sum()/n), "awayWin": float(c[a>h].sum()/n),
            "tie": float(c[h==a].sum()/n),
            "probabilityUnits": "FRACTIONS_0_TO_1", "pairingPreserved": True}


def agree(actual, expected, tolerance=1e-8):
    if not math.isfinite(float(expected)) or abs(float(actual)-float(expected)) > tolerance:
        raise ValueError(f"NUMERICAL_BINDING_MISMATCH: {actual} != {expected}")


def verify_index_package(directory):
    directory = Path(directory)
    ref = physical(directory / "index.json")
    if ref["sha256"] != directory.name:
        raise ValueError("INDEX_ADDRESS_MISMATCH")
    doc = read(ref["path"])
    members = []
    for item in doc["files"]:
        name = item.get("relativePath", item.get("path"))
        p = (directory / name).resolve()
        if directory.resolve() not in p.parents:
            raise ValueError("UNSAFE_MEMBER")
        members.append(checked({**item, "path": str(p)}))
    return doc, {"index": ref, "members": members, "identityAlgorithm": "PHYSICAL_INDEX_SHA256"}


def audit_nfl(bundle_path, forecast_id, supplement_dir):
    from server.sports_gold.nfl_shadow_exchange import verify_sports_forecast_bundle
    p = Path(bundle_path)
    doc = verify_sports_forecast_bundle(p.parents[3], p.parent.name).record
    f = next(x for x in doc["forecasts"] if x["forecastId"] == forecast_id)
    if f["engine"]["engineId"] != "NFL_M1_XGBOOST" or f["snapshotType"] != "CURRENT":
        raise ValueError("NFL_MODEL_OR_HORIZON")
    if not f["features"]["readiness"]["isReady"] or not f["researchShadowOnly"] or f["executionAllowed"]:
        raise ValueError("NFL_READINESS_OR_AUTHORITY")
    n = f["simulator"]["completedSimulations"]
    cells = f["jointScoreDistribution"]
    counts = [round(x["probability"]*n) for x in cells]
    for x,c in zip(cells,counts): agree(x["probability"],c/n)
    s = joint_summary([x["homeScore"] for x in cells], [x["awayScore"] for x in cells], counts)
    if s["drawCount"] != n or n != 10000: raise ValueError("NFL_DRAW_COUNT")
    for ours, theirs in [("expectedHome","expectedHomeScore"),("expectedAway","expectedAwayScore"),
                         ("homeWin","homeWinProbability"),("awayWin","awayWinProbability"),("tie","tieProbability")]:
        agree(s[ours],f[theirs])
    sup = read(Path(supplement_dir)/"supplement.json")
    if sup["binding"]["forecastId"] != forecast_id or sup["binding"]["eventId"] != f["eventId"]:
        raise ValueError("NFL_ELIGIBILITY_BINDING")
    if sup["binding"]["modelArtifactSha256"] != f["engine"]["modelBinarySha256"]:
        raise ValueError("NFL_ELIGIBILITY_MODEL")
    # The established independent contract validator checks canonical UTF-8,
    # the supplement identity algorithm, physical manifest and authority.
    from server.sports_nfl_m1.week2_paper_eligibility import verify_package
    verify_package(Path(supplement_dir))
    clocks = chronology(f["sourceCutoffUtc"], f["availableAsOfUtc"],doc["generatedAtUtc"],f["scheduledStartUtc"])
    # generatedAtUtc is a bundle-generation clock, not a separately measured
    # filesystem publication instant. Preserve that distinction explicitly.
    clocks["bundleGeneratedAtUtc"] = clocks.pop("publishedAtUtc")
    clocks["publishedAtUtc"] = None
    clocks["publicationObservedAtUtc"] = now()
    clocks["publicationClockQualification"] = "Exact original publication instant absent from bundle contract; immutable package is physically present at audit."
    if clock(clocks["publicationObservedAtUtc"]) >= clock(f["scheduledStartUtc"]):
        raise ValueError("NFL_CURRENT_DEMO_TARGET_ALREADY_STARTED")
    deadline = clock(f["scheduledStartUtc"])-timedelta(minutes=15)
    clocks["consumerDecisionCutoffUtc"] = deadline.isoformat()
    clocks["consumerWindowOpensUtc"] = (deadline-timedelta(minutes=15)).isoformat()
    return {"sport":"NFL", "eventId":f["eventId"], "forecastId":forecast_id,
        "horizon":f["snapshotType"], "version":f["snapshotVersion"],
        "away":f["awayTeam"], "home":f["homeTeam"], "clocks":clocks,
        "forecastCanonicalSha256":sha(canonical(f)), "package":physical(p),
        "engine":f["engine"], "numericalVerification":s,
        "inputReadiness":f["features"], "eligibility":physical(Path(supplement_dir)/"supplement.json"),
        "consumerUse":"EXACT_FORECAST_PAPER_ELIGIBILITY_SUBJECT_TO_EXISTING_AISP_GATES",
        "marketAuthorityGrantedByRelease":False, "consumerAcknowledgement":None}


def publish(stage, exchange):
    stage, exchange = Path(stage), Path(exchange)
    release = read(stage/"release.json")
    validate_release(release)
    names = sorted(p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()
                   and p.name != "package-manifest.json")
    records = member_records(stage, names)
    digest = package_content_sha256({x["path"]:x["sha256"] for x in records})
    manifest={"schemaVersion":SCHEMA+"_PACKAGE", "identityAlgorithm":IDENTITY_ALGORITHM,
              "packageContentSha256":digest,"files":records}
    write(stage/"package-manifest.json",manifest)
    root=exchange/"demo-releases-v1"; dest=root/"sha256"/digest
    root.mkdir(parents=True,exist_ok=True)
    lock=root/"publication.lock"
    handle = lock.open("x")
    handle.close()
    try:
            if not dest.exists():
                tmp=root/".staging"/digest
                if tmp.exists(): raise ValueError("INCOMPLETE_STAGE_EXISTS")
                shutil.copytree(stage,tmp)
                # Verify directory-addressed bytes before visibility.
                verify_package_directory(tmp)
                dest.parent.mkdir(parents=True,exist_ok=True)
                os.rename(tmp,dest)
            verified=verify_package_directory(dest)
            receipt_path=dest/"publication-receipt.json"
            if not receipt_path.exists():
                write(receipt_path,{"schemaVersion":SCHEMA+"_PUBLICATION", "publishedAtUtc":now(),
                    "packageContentSha256":digest,"consumerAcknowledgement":None,
                    "aispWrites":0,"authorityChanged":False})
            discovery=root/"discovery.json"
            old=read(discovery) if discovery.exists() else {"schemaVersion":SCHEMA+"_DISCOVERY","releases":[]}
            if not any(x["packageContentSha256"]==digest for x in old["releases"]):
                old["releases"].append({"packageContentSha256":digest,"packagePath":str(dest),
                    "manifest":physical(dest/"package-manifest.json"),"publicationReceipt":physical(receipt_path)})
                if discovery.exists():
                    prior=discovery.read_bytes();snap=root/"index-history"/(sha(prior)+".json")
                    snap.parent.mkdir(exist_ok=True)
                    if not snap.exists():snap.write_bytes(prior)
                temp=discovery.with_suffix(".new")
                temp.write_bytes(canonical(old));os.replace(temp,discovery)
            return {"package":str(dest),"verification":verified,"discovery":physical(discovery),
                    "publicationReceipt":physical(receipt_path)}
    finally:
        lock.unlink()


def validate_release(doc):
    if doc["schemaVersion"] != SCHEMA: raise ValueError("RELEASE_SCHEMA")
    if set(x["sport"] for x in doc["champions"]) != {"MLB","NFL","NBA","CFB"}:
        raise ValueError("FOUR_CHAMPIONS_REQUIRED")
    if any(doc["authority"].get(x) is not False for x in
           ("modelPromotion","wagering","positions","schedulerActivation","aispWrites")):
        raise ValueError("RELEASE_CANNOT_GRANT_AUTHORITY")
    for d in doc["champions"]:
        if d["schemaVersion"] != DECLARATION: raise ValueError("DECLARATION_SCHEMA")
        for key in ("modelIdentity","channels","training","featureContract","limitations","historicalMetrics","authority"):
            if key not in d: raise ValueError("DECLARATION_MISSING_"+key)
    for f in doc["forecasts"]:
        if f["horizon"] == "SHOW_PREVIEW" and f.get("consumerUse") != "EDITORIAL_ONLY":
            raise ValueError("PREVIEW_AUTHORITY_ESCALATION")
        if f.get("marketAuthorityGrantedByRelease") is not False: raise ValueError("FORECAST_AUTHORITY")


def main():
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["publish","verify"])
    p.add_argument("--stage",type=Path);p.add_argument("--exchange",type=Path);p.add_argument("--package",type=Path)
    a=p.parse_args()
    if a.mode == "publish":
        result = publish(a.stage, a.exchange)
    else:
        result = verify_package_directory(a.package)
        validate_release(read(a.package / "release.json"))
    print(json.dumps(result,indent=2))


if __name__=="__main__": main()
