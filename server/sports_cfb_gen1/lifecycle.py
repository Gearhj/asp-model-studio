"""Offline CFB publication lifecycle. Numerical models are injected, never fitted.

All mutable pointers are atomic; evidence, packages, discoveries and invocation
receipts are append-only. The process lock is released by the OS after a crash.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import uuid

from .publication_io import reference, verified_bytes
from .publication_io import canonical_bytes, digest

SCHEMA = "CFB_GEN1_SLATE_POLICY_V1"
POLICY = {
    "schema": SCHEMA,
    "checkpointsMinutesBeforeKickoff": [10080, 1440, 360, 60],
    "lastPublicationMinutesBeforeKickoff": 30,
    "scheduleMaxAgeHours": 24,
    "historyMembershipMaxAgeHours": 24,
    "finalCheckpointMaxAgeHours": 2,
    "cadenceMinutes": 15,
    "newRevision": "Prediction-affecting admitted content, target identity/time, or frozen release binding changes while due; validation-only 304 retains original forecast",
    "unchangedCheckpoint": "Verify current eligibility and reuse original bytes; receipt records checkpoint",
}


def utc(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timezone-bearing clock required")
    return result.astimezone(timezone.utc)


def now():
    return datetime.now(timezone.utc).isoformat()


def read_ref(bound):
    return json.loads(verified_bytes(bound))


def immutable(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Immutable conflict: " + str(path))
    else:
        temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        with temp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # On Windows rename refuses an existing destination. Single-owner lock
        # serializes all package/pointer operations in the production path.
        temp.rename(path)
    return reference(path)


def object_json(root, value, name="receipt.json"):
    data = canonical_bytes(value)
    return immutable(Path(root) / "sha256" / digest(data) / name, data)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temp.open("xb") as handle:
        handle.write(canonical_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


@contextmanager
def owner_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        # Do not read the byte while another Windows owner holds its range lock.
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("OWNER_BUSY") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def paper_eligibility_authorization(release, clock):
    """Validate only the separately bound virtual-use extension, never publication."""
    bound = release.get("paperEligibilityAuthorization")
    if bound is None:
        return None
    grant = read_ref(bound)
    policy = grant.get("policyAuthorization", {})
    plan_ref = release.get("refreshPlan", {})
    if (grant.get("schema") != "CFB_VIRTUAL_POLICY_EXTENSION_AUTHORIZATION_V1"
            or grant.get("approvedBy") != "James"
            or grant.get("consumerVirtualExperimentAuthorized") is not True
            or grant.get("realMoneyAuthorized") is not False
            or grant.get("modelPromotionAuthorized") is not False
            or grant.get("modelConfiguration") != "CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1"
            or grant.get("planSha256") != plan_ref.get("sha256")
            or policy.get("mode") != "VIRTUAL_RESEARCH_ONLY"
            or policy.get("realMoneyExecutionAllowed") is not False):
        raise ValueError("Invalid separately bound CFB paper eligibility authorization")
    plan = read_ref(plan_ref)
    first = max(utc(grant["retainedAtUtc"]), utc(plan["validFromUtc"]))
    last = min(utc(grant["validUntilUtc"]), utc(plan["validUntilUtc"]))
    if not first <= utc(clock) < last:
        return None
    return {"reference": bound, "validFromUtc": first.isoformat(), "validUntilUtc": last.isoformat()}


def eligibility(row, bundle, clock, policy=POLICY, *, paper_authorization=None):
    """No package lookup is permitted before this decision. No outcomes read."""
    if row.get("exclusion"):
        return {"disposition": "EXCLUDED", "reason": row["exclusion"], "currentlyEligible": False}
    target = row["target"]
    start, clock = utc(target["scheduled_at"]), utc(clock)
    if target["status"] != "SCHEDULED":
        return {"disposition": "GAME_NOT_SCHEDULED", "reason": target["status"], "currentlyEligible": False}
    if clock >= start:
        return {"disposition": "POST_KICKOFF_REJECTED", "currentlyEligible": False}
    stop = start - timedelta(minutes=policy["lastPublicationMinutesBeforeKickoff"])
    paper = paper_authorization if (paper_authorization and
        utc(paper_authorization["validFromUtc"]) <= clock < utc(paper_authorization["validUntilUtc"])) else None
    retained_stop = min(start - timedelta(minutes=15), utc(paper["validUntilUtc"])) if paper else stop
    if clock >= stop and paper is None:
        return {"disposition": "PUBLICATION_CUTOFF_PASSED", "currentlyEligible": False}
    if clock >= retained_stop:
        return {"disposition": "PAPER_DECISION_CUTOFF_PASSED", "currentlyEligible": False}
    checkpoints = [(start - timedelta(minutes=m), m) for m in policy["checkpointsMinutesBeforeKickoff"]]
    reached = [(at, minutes) for at, minutes in checkpoints if at <= clock]
    issues = []
    max_age = policy["finalCheckpointMaxAgeHours"] if reached and reached[-1][1] == 60 else policy["scheduleMaxAgeHours"]
    schedule_clock = "scheduleValidatedAtUtc" if "scheduleValidatedAtUtc" in bundle else "scheduleCapturedAtUtc"
    for field, hours in [(schedule_clock, max_age),
                         ("historyCompleteThroughUtc", min(max_age, policy["historyMembershipMaxAgeHours"]))]:
        stamp = utc(bundle[field])
        if stamp > clock:
            issues.append("FUTURE_" + field)
        elif clock - stamp > timedelta(hours=hours):
            issues.append("STALE_" + field)
    if not reached:
        return {"disposition": "NOT_DUE", "currentlyEligible": False,
                "nextCheckpointUtc": checkpoints[0][0].isoformat(), "inputBlockers": issues}
    if issues:
        return {"disposition": "STALE_INPUT_REJECTED", "currentlyEligible": False, "inputBlockers": issues}
    if row.get("inputBlockers"):
        return {"disposition":"INPUTS_PENDING", "currentlyEligible":False, "inputBlockers":row["inputBlockers"]}
    if bundle.get("historyMissingGameIds"):
        return {"disposition": "HISTORY_INCOMPLETE", "currentlyEligible": False,
                "missingGameIds": bundle["historyMissingGameIds"]}
    result = {"disposition": "DUE" if clock < stop else "RETAINED_ONLY", "currentlyEligible": clock < stop,
            "checkpointMinutesBeforeKickoff": reached[-1][1], "publicationDeadlineUtc": stop.isoformat(),
            "eligibilityValidUntilUtc": min(retained_stop, clock + timedelta(minutes=policy["cadenceMinutes"]),
                utc(bundle[schedule_clock]) + timedelta(hours=max_age),
                utc(bundle["historyCompleteThroughUtc"]) + timedelta(hours=min(max_age, policy["historyMembershipMaxAgeHours"])) ).isoformat()}
    if paper:
        result.update(paperEligibilityAuthorization=paper["reference"], eligibilityAuthority="VIRTUAL_RESEARCH_ONLY",
                      publicationAllowed=clock < stop)
    return result


def verify_retained_publication(saved, key, gid, deadline, clock, verifier):
    """Prove an exact immutable prior publication; never recover a prepared one."""
    if (saved.get("revisionKey") != key or str(saved.get("gameId")) != str(gid)
            or not utc(saved["committedAtUtc"]) < utc(deadline)
            or utc(saved["committedAtUtc"]) > utc(clock)):
        raise ValueError("Retained forecast lacks exact pre-cutoff publication proof")
    bound_index = read_ref(saved["index"])
    index = verifier(Path(saved["packageDirectory"]))
    if (index != bound_index or index.get("revisionKey") != key
            or str(index.get("gameId")) != str(gid)
            or index.get("forecastId") != saved.get("forecastId")):
        raise ValueError("Retained package identity differs from exact committed revision")


def revision_key(row, bundle_ref, release):
    bundle = read_ref(bundle_ref)
    release_data=read_ref(release)
    # A refreshed capture clock or an unrelated game's change cannot restamp a
    # numerically unchanged target. Eligibility is still checked on every tick.
    target = {k:v for k,v in row["target"].items() if k != "source_revision"}
    return digest({"target": target, "predictionInputs": row.get("predictionInputIdentity", bundle.get("predictionInputIdentity", bundle_ref["sha256"])),
                   "release": release_data.get('predictionReleaseIdentity',release["sha256"]), "policy": POLICY})


def tick(*, bundle_ref, release_ref, state_root, exchange_root, renderer,
         verifier, clock=now, fault=None, bundle_validator=None, owner_lock_already_held=False):
    """One bounded tick. Renderer returns a fully written private package folder.

    fault is a test-only callback; the production CLI never exposes it. Complete
    prepared packages survive interruption and are recovered without resimulation.
    """
    state, exchange = Path(state_root), Path(exchange_root)
    started = clock()
    invocation = uuid.uuid4().hex
    start_ref = object_json(state / "runner-starts", {"invocationId": invocation,
        "startedAtUtc": started, "status": "STARTED", "input": bundle_ref, "release": release_ref})
    receipt = {"schema": "CFB_GEN1_SLATE_RUNNER_RECEIPT_V1", "invocationId": invocation,
        "startedAtUtc": started, "startReceipt": start_ref, "input": bundle_ref,
        "release": release_ref, "games": [], "providerCalls": 0, "providerBytes": 0,
        "costUsd": 0, "aispWrites": 0, "exitCode": 0}
    try:
        with (nullcontext() if owner_lock_already_held else owner_lock(state / "publisher.lock")):
            bundle = read_ref(bundle_ref)
            release = read_ref(release_ref)
            if bundle["schema"] != "CFB_GEN1_SLATE_INPUT_V1":
                raise ValueError("Wrong input schema")
            if bundle_validator:
                bundle_validator(bundle, release)
            if utc(started) < utc(release["prospectiveEffectiveAtUtc"]):
                raise ValueError("Release not yet effective")
            paper = paper_eligibility_authorization(release, started)
            journal = state / "committed"
            prepared = state / "prepared"
            # An input update is snapshotted once; every package binds that exact version.
            for row in bundle["games"]:
                gid = row["gameId"]
                item = {"gameId": gid, **eligibility(row, bundle, clock(), paper_authorization=paper)}
                try:
                    if item["disposition"] in ("DUE", "RETAINED_ONLY"):
                        key = revision_key(row, bundle_ref, release_ref)
                        item["revisionKey"] = key
                        committed = journal / (key + ".json")
                        transaction = prepared / (key + ".json")
                        if committed.exists():
                            saved = json.loads(committed.read_bytes())
                            if paper:
                                verify_retained_publication(saved, key, gid, item["publicationDeadlineUtc"], clock(), verifier)
                            else:
                                verifier(Path(saved["packageDirectory"]))
                            check = eligibility(row, bundle, clock(), paper_authorization=paper)
                            item.update(check)
                            if check["disposition"] in ("DUE", "RETAINED_ONLY"):
                                item.update(disposition="REUSED_IMMUTABLE", currentlyEligible=True, package=saved)
                        elif item["disposition"] == "RETAINED_ONLY":
                            item.update(disposition="RETAINED_FORECAST_UNAVAILABLE", currentlyEligible=False)
                        else:
                            if transaction.exists():
                                pending = json.loads(transaction.read_bytes())
                                directory = Path(pending["stagingDirectory"])
                                destination = Path(pending["packageDirectory"])
                                directory = destination if destination.exists() else directory
                            else:
                                directory = renderer(row, bundle_ref, release_ref, key, state / "builds" / key)
                                index = verifier(directory)
                                address = digest((directory / "index.json").read_bytes())
                                destination = exchange / "forecasts/sha256" / address
                                pending = {"stagingDirectory": str(directory), "packageDirectory": str(destination),
                                           "packageAddress": address, "revisionKey": key,
                                           "forecastId": index["forecastId"], "gameId": gid}
                                immutable(transaction, canonical_bytes(pending))
                            # Time/status/input freshness rechecked after expensive rendering.
                            check = eligibility(row, bundle, clock())
                            if check["disposition"] != "DUE":
                                item.update(check)
                            else:
                                verifier(directory)
                                if fault:
                                    fault("prepared", gid)
                                if not destination.exists():
                                    destination.parent.mkdir(parents=True, exist_ok=True)
                                    # Stage on the destination volume; cross-volume copies are verified.
                                    import shutil
                                    stage = destination.parent / (".stage-" + uuid.uuid4().hex)
                                    shutil.copytree(directory, stage)
                                    verifier(stage)
                                    if eligibility(row, bundle, clock())["disposition"] != "DUE":
                                        raise ValueError("Eligibility expired during publication copy")
                                    stage.rename(destination)
                                index = verifier(destination)
                                if fault:
                                    fault("published", gid)
                                committed_at = clock()
                                if eligibility(row, bundle, committed_at)["disposition"] != "DUE":
                                    raise ValueError("Publication cutoff passed before durable commitment")
                                saved = {k: v for k, v in pending.items() if k != "stagingDirectory"}
                                saved.update(index=reference(destination / "index.json"),
                                    committedAtUtc=committed_at, originallyPublishedAtUtc=index.get("publishedAtUtc"),
                                    publicationClockSemantics="First durable availability confirmation; package preparation is not publication")
                                immutable(committed, canonical_bytes(saved))
                                item.update(disposition="PUBLISHED_NEW_PROSPECTIVE", package=saved)
                                final_check = eligibility(row, bundle, clock(), paper_authorization=paper)
                                item.update(final_check, package=saved)
                                if final_check["disposition"] in ("DUE", "RETAINED_ONLY"):
                                    item.update(disposition="PUBLISHED_NEW_PROSPECTIVE", currentlyEligible=True)
                    # Never describe an existing package as current when the new version failed.
                except Exception as exc:
                    item.update(disposition="GAME_FAILED", currentlyEligible=False,
                                errorType=type(exc).__name__, reason=str(exc))
                    receipt["exitCode"] = 1
                receipt["games"].append(item)
                # One game's completion is durable even if the process dies on the next.
                # Offseason/full-year inventories need one runner receipt, not
                # thousands of tiny NOT_DUE files every quarter hour. Publication
                # and per-game failure work remains independently durable.
                if item.get("package") or item["disposition"] == "GAME_FAILED":
                    object_json(state / "game-receipts", {"invocationId": invocation, "observedAtUtc": clock(), **item})
            packages = []
            for path in sorted(journal.glob("*.json")) if journal.exists() else []:
                saved = json.loads(path.read_bytes())
                publication_ref = object_json(exchange / "publication-receipts", saved)
                packages.append(dict(saved, publicationReceipt=publication_ref))
            covered = {g["gameId"] for g in receipt["games"]}
            for gid in sorted({p["gameId"] for p in packages} - covered):
                receipt["games"].append({"gameId": gid, "disposition": "ABSENT_FROM_CURRENT_SCHEDULE",
                                         "currentlyEligible": False})
            for row in packages:
                verified_bytes(row["index"])
                current = next((g for g in receipt["games"] if g.get("package", {}).get("packageAddress") == row["packageAddress"]), None)
                row.update(currentlyEligible=bool(current and current["currentlyEligible"]),
                    eligibilityValidUntilUtc=current.get("eligibilityValidUntilUtc") if current else None,
                    status="CURRENT_ELIGIBLE" if current and current["currentlyEligible"] else "PRESERVED_HISTORICAL_VERSION")
                if current and current.get("paperEligibilityAuthorization"):
                    row.update(paperEligibilityAuthorization=current["paperEligibilityAuthorization"],
                               eligibilityAuthority="VIRTUAL_RESEARCH_ONLY")
            pointer = exchange / "slate-discovery/current.json"
            predecessor = reference(pointer) if pointer.exists() else None
            previous = read_ref(predecessor) if predecessor else None
            prior_manifest = previous["manifest"] if previous else None
            legacy = release.get("preservedDiscovery")
            retained = read_ref(legacy).get("packages", []) if legacy else []
            discovery = {"schemaVersion": "CFB_GEN1_SLATE_DISCOVERY_V1", "createdAtUtc": clock(),
                "predecessor": prior_manifest, "inputVersion": bundle_ref, "release": release_ref,
                "packages": packages, "preservedEarlierPackages": retained,
                "games": receipt["games"], "consumerAcknowledged": False,
                "semantics": "All revisions retained; currentlyEligible describes this tick only. Recheck expiry before consumer use."}
            manifest = object_json(exchange / "slate-discovery/versions", discovery, "index.json")
            atomic_json(pointer, {"schemaVersion": "CFB_GEN1_SLATE_DISCOVERY_POINTER_V1", "manifest": manifest})
            receipt["discovery"] = manifest
            kinds = {item["disposition"] for item in receipt["games"]}
            receipt["disposition"] = ("PARTIAL_FAILURE" if receipt["exitCode"] else
                "PUBLISHED" if "PUBLISHED_NEW_PROSPECTIVE" in kinds else
                "REUSED_IMMUTABLE" if "REUSED_IMMUTABLE" in kinds else
                "STALE_INPUT_REJECTED" if "STALE_INPUT_REJECTED" in kinds else
                "INPUTS_BLOCKED" if kinds & {"HISTORY_INCOMPLETE", "INPUTS_PENDING"} else "NOT_DUE")
    except Exception as exc:
        receipt.update(exitCode=1, disposition="FAILED", errorType=type(exc).__name__, reason=str(exc))
    receipt["completedAtUtc"] = clock()
    bound = object_json(state / "runner-receipts", receipt)
    return receipt, bound
