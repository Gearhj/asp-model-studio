"""Exact-object NFL Week 2 paper eligibility publication.

The AISP consumer contract is event/forecast specific.  This module therefore
publishes one immutable supplement per admitted forecast, but does so in one
bounded batch.  A later forecast is never covered implicitly: rerunning the
batch publisher must verify and publish a new supplement for that exact object.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from server.sports_gold.nfl_shadow_exchange import verify_sports_forecast_bundle
from server.sports_nfl_m1.paper_research_eligibility import (
    GOVERNANCE,
    KIND,
    VERSION,
    canonical_json_bytes,
    immutable_json,
    physical,
)
from server.sports_shared.paper_research_eligibility import immutable_bytes


WEEK = 2
SEASON = 2026
DRAW_COUNT = 10_000
ENGINE_ID = "NFL_M1_XGBOOST"
ENGINE_VERSION = "NFL_M1_2026_RESEARCH_SHADOW_V1"
MODEL_BINARY_SHA256 = "7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd"
MODEL_MANIFEST_SHA256 = "ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9"
FEATURE_CONTRACT_SHA256 = "ef5c4f9ce8c3dd04a473e7ecb2ea3a255154f65a1bb3fda9d2ebc19bf1cb8f4d"
SIMULATOR_ID = "NFL_M1_EMPIRICAL_PAIRED_RESIDUAL"
SIMULATOR_VERSION = "NFL_M1_EMPIRICAL_CORRELATED_RESIDUAL_V1"
POLICY_VERSION = "AISP_NFL_PAPER_POLICY_V1"
STAKING_VERSION = "AISP_QUARTER_KELLY_NFL_V1"
EXPERIMENT_ID = "AISP_NFL_PAPER_POLICY_V1:NFL:2026"
EXPERIMENT_NAME = "ASP NFL RESEARCH PAPER BANKROLL — 2026 V1"
INDEX_SCHEMA = "AISP_NFL_LABS_SUPPLEMENT_INDEX_V1"
BATCH_SCHEMA = "ASP_NFL_WEEK2_PAPER_ELIGIBILITY_BATCH_V1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUCCESSOR_OUTPUT_ROOT = PROJECT_ROOT / "outputs/nfl-week2-successor-eligibility-v1"
DEFAULT_AUTHORIZATION_SOURCE_PATH = (
    PROJECT_ROOT
    / "outputs/nfl-week2-paper-eligibility-20260915-v1/batch/sha256"
    / "82d2a87fd4a24deb9c1a7b26dfc4f11347e9a3daf9f1a39d9ea4ac5aacc890b1"
    / "operational-readiness.json"
)


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp lacks a timezone")
    return parsed.astimezone(timezone.utc)


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_exact(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} differs: {actual!r} != {expected!r}")


def _population_summary(forecast: Mapping[str, Any]) -> dict[str, Any]:
    cells = forecast.get("jointScoreDistribution")
    if not isinstance(cells, list) or not cells:
        raise ValueError("Joint score population is unavailable")
    total = home = away = tie = expected_home = expected_away = 0.0
    inferred_draws = 0
    for cell in cells:
        probability = float(cell["probability"])
        if probability < 0 or probability > 1:
            raise ValueError("Joint population has invalid probability")
        home_score = int(cell["homeScore"])
        away_score = int(cell["awayScore"])
        total += probability
        expected_home += probability * home_score
        expected_away += probability * away_score
        inferred_draws += round(probability * DRAW_COUNT)
        if home_score > away_score:
            home += probability
        elif away_score > home_score:
            away += probability
        else:
            tie += probability
    if abs(total - 1.0) > 1e-10 or inferred_draws != DRAW_COUNT:
        raise ValueError("Joint population does not reconcile to 10,000 draws")
    for actual, expected, label in (
        (home, float(forecast["homeWinProbability"]), "home-win mass"),
        (away, float(forecast["awayWinProbability"]), "away-win mass"),
        (tie, float(forecast["tieProbability"]), "tie mass"),
        (expected_home, float(forecast["expectedHomeScore"]), "expected home score"),
        (expected_away, float(forecast["expectedAwayScore"]), "expected away score"),
    ):
        if abs(actual - expected) > 1e-9:
            raise ValueError(f"{label} does not reconcile")
    return {
        "drawCount": DRAW_COUNT,
        "jointScoreDistributionCanonicalSha256": hashlib.sha256(
            canonical_json_bytes(cells)
        ).hexdigest(),
        "probabilityMass": total,
        "homeWinProbability": home,
        "awayWinProbability": away,
        "tieProbability": tie,
        "expectedHomeScore": expected_home,
        "expectedAwayScore": expected_away,
        "pairingPreserved": True,
    }


def validate_forecast(forecast: Mapping[str, Any], *, published_utc: str) -> dict[str, Any]:
    """Fail closed on every bound model, chronology and population property."""
    _require_exact(forecast.get("season"), SEASON, "season")
    _require_exact(forecast.get("week"), WEEK, "week")
    _require_exact(forecast.get("seasonType"), "REG", "season type")
    engine = forecast.get("engine") or {}
    for key, expected in (
        ("engineId", ENGINE_ID),
        ("engineVersion", ENGINE_VERSION),
        ("modelBinarySha256", MODEL_BINARY_SHA256),
        ("modelManifestSha256", MODEL_MANIFEST_SHA256),
        ("featureContractSha256", FEATURE_CONTRACT_SHA256),
    ):
        _require_exact(engine.get(key), expected, f"engine.{key}")
    simulator = forecast.get("simulator") or {}
    for key, expected in (
        ("simulatorId", SIMULATOR_ID),
        ("simulatorVersion", SIMULATOR_VERSION),
        ("simulationCount", DRAW_COUNT),
        ("completedSimulations", DRAW_COUNT),
    ):
        _require_exact(simulator.get(key), expected, f"simulator.{key}")
    features = forecast.get("features") or {}
    _require_exact(features.get("featureCount"), 197, "feature count")
    missing = features.get("missingFeatures") or []
    _require_exact(features.get("missingFeatureCount"), len(missing), "missing feature accounting")
    _require_exact((features.get("readiness") or {}).get("isReady"), True, "feature readiness")
    for key, expected in (
        ("status", "RESEARCH_SHADOW"),
        ("researchShadowOnly", True),
        ("executionAllowed", False),
        ("modelPromotionAllowed", False),
    ):
        _require_exact(forecast.get(key), expected, key)
    source = utc(str(forecast["sourceCutoffUtc"]))
    cutoff = utc(str(forecast["forecastCutoffUtc"]))
    available = utc(str(forecast["availableAsOfUtc"]))
    kickoff = utc(str(forecast["scheduledStartUtc"]))
    published = utc(published_utc)
    if not source <= cutoff <= available < kickoff:
        raise ValueError("Forecast chronology differs")
    if published >= kickoff:
        raise ValueError("Eligibility publication is not pregame")
    if forecast.get("snapshotType") == "FINAL_PREGAME" and available > kickoff - timedelta(minutes=15):
        raise ValueError("FINAL_PREGAME missed its cutoff")
    probabilities = [float(forecast[key]) for key in (
        "awayWinProbability", "homeWinProbability", "tieProbability"
    )]
    if any(value < 0 or value > 1 for value in probabilities) or abs(sum(probabilities) - 1) > 1e-12:
        raise ValueError("Three-way probability mass differs")
    return _population_summary(forecast)


def build_document(
    forecast: Mapping[str, Any], *, bundle_reference: Mapping[str, Any],
    authorization_reference: Mapping[str, Any], published_utc: str,
) -> dict[str, Any]:
    population = validate_forecast(forecast, published_utc=published_utc)
    event_id = str(forecast["eventId"])
    frozen = {
        "forecastId": forecast["forecastId"],
        "eventId": event_id,
        "season": SEASON,
        "week": WEEK,
        "snapshotType": forecast["snapshotType"],
        "snapshotVersion": forecast["snapshotVersion"],
        "engine": deepcopy(forecast["engine"]),
        "simulator": deepcopy(forecast["simulator"]),
        "features": deepcopy(forecast["features"]),
        "homeWinProbability": forecast["homeWinProbability"],
        "awayWinProbability": forecast["awayWinProbability"],
        "tieProbability": forecast["tieProbability"],
        "expectedHomeScore": forecast["expectedHomeScore"],
        "expectedAwayScore": forecast["expectedAwayScore"],
        "executionAllowed": False,
        "modelPromotionAllowed": False,
    }
    return {
        "schemaVersion": "AISP_RESEARCH_SUPPLEMENT_V1",
        "artifactVersion": VERSION,
        "supplementId": f"nfl-week2-paper-eligibility:{EXPERIMENT_ID}:{event_id}:{forecast['forecastId'].split(':')[-1]}:v1",
        "kind": KIND,
        "sport": "NFL",
        "governance": deepcopy(GOVERNANCE),
        "binding": {
            "eventId": event_id,
            "engineId": ENGINE_ID,
            "forecastId": forecast["forecastId"],
            "modelArtifactSha256": MODEL_BINARY_SHA256,
        },
        "sourceCutoffUtc": forecast["sourceCutoffUtc"],
        "publishedUtc": published_utc,
        "simulation": {"kind": "NONE", "count": 0},
        "summaries": {
            "producerDisposition": "ELIGIBLE_EVIDENCE_FOR_AUTHORIZED_VIRTUAL_RESEARCH_WITH_LIMITATIONS",
            "authorization": {
                "experimentId": EXPERIMENT_ID,
                "experimentName": EXPERIMENT_NAME,
                "policyVersion": POLICY_VERSION,
                "stakingVersion": STAKING_VERSION,
                "mode": "VIRTUAL_RESEARCH_ONLY",
                "consumerVirtualExperimentAuthorized": True,
                "realMoneyAuthorized": False,
                "realMoneyExecutionAllowed": False,
                "virtualInitialBankrollUsd": 1000,
                "kellyFraction": 0.25,
                "positionCapFraction": 0.005,
                "initialPositionCapUsd": 5,
                "sameGameCapFraction": 0.01,
                "dailyCapFraction": 0.02,
                "minimumAdjustedEdgeFraction": 0.02,
                "maxDailyNflPregameQuotes": 1,
                "tieTreatment": "STAKE_REFUNDED_PUSH",
                "marketScope": ["MONEYLINE"],
                "scopeOfThisEvidence": [event_id],
                "authorizationEvidence": dict(authorization_reference),
            },
            "frozenConfiguration": frozen,
            "forecastPopulationBinding": population,
            "forecastBundle": dict(bundle_reference),
            "forecastClocks": {
                "sourceCutoffUtc": forecast["sourceCutoffUtc"],
                "forecastCutoffUtc": forecast["forecastCutoffUtc"],
                "availableAsOfUtc": forecast["availableAsOfUtc"],
                "scheduledStartUtc": forecast["scheduledStartUtc"],
                "eligibilityPublishedUtc": published_utc,
            },
            "probabilitySemantics": {
                "units": "FRACTION_0_TO_1",
                "settlementMustBeExplicit": True,
                "tieMeaning": "EQUAL_MODELED_FINAL_SCORES",
                "tieSettlementForThisExperiment": "STAKE_REFUNDED_PUSH",
                "awayMoneyline": {"pWin": forecast["awayWinProbability"], "pPush": forecast["tieProbability"], "pLoss": forecast["homeWinProbability"]},
                "homeMoneyline": {"pWin": forecast["homeWinProbability"], "pPush": forecast["tieProbability"], "pLoss": forecast["awayWinProbability"]},
            },
            "modeledLineSemantics": {
                "classification": "MODELED_REFERENCE_SCENARIOS_ONLY",
                "mayPopulateSportsbookMoneylineSpreadOrTotalFields": False,
                "actualMarketPricesRequireSeparatelyPersistedProviderEvidence": True,
                "providerSportsbookObservationTimeAndFreshnessMayBeInferred": False,
                "lineQueriesAreNotQuotes": True,
            },
            "successorRule": (
                "This supplement admits only its exact immutable forecastId. A later CURRENT or "
                "FINAL_PREGAME revision is eligible only after this batch publisher verifies that "
                "exact successor against the same week, season, model, feature, chronology, mass, "
                "draw-count and research-only gates and publishes a distinct supplement."
            ),
        },
        "producer": {
            "providerRequests": 0,
            "forecastExecutions": 0,
            "aispWrites": 0,
            "forecastRegenerated": False,
        },
    }


def validate_document(document: Mapping[str, Any]) -> None:
    _require_exact(document.get("schemaVersion"), "AISP_RESEARCH_SUPPLEMENT_V1", "schema")
    _require_exact(document.get("artifactVersion"), VERSION, "artifact version")
    _require_exact(document.get("kind"), KIND, "kind")
    _require_exact(document.get("sport"), "NFL", "sport")
    _require_exact(document.get("governance"), GOVERNANCE, "governance")
    _require_exact(document.get("simulation"), {"kind": "NONE", "count": 0}, "simulation")
    binding = document["binding"]
    frozen = document["summaries"]["frozenConfiguration"]
    auth = document["summaries"]["authorization"]
    _require_exact(binding["eventId"], frozen["eventId"], "event binding")
    _require_exact(binding["forecastId"], frozen["forecastId"], "forecast binding")
    _require_exact(binding["engineId"], ENGINE_ID, "engine binding")
    _require_exact(binding["modelArtifactSha256"], MODEL_BINARY_SHA256, "model binding")
    for key, expected in (
        ("experimentId", EXPERIMENT_ID), ("policyVersion", POLICY_VERSION),
        ("stakingVersion", STAKING_VERSION), ("mode", "VIRTUAL_RESEARCH_ONLY"),
        ("consumerVirtualExperimentAuthorized", True), ("realMoneyAuthorized", False),
        ("virtualInitialBankrollUsd", 1000), ("kellyFraction", 0.25),
        ("positionCapFraction", 0.005), ("initialPositionCapUsd", 5),
        ("sameGameCapFraction", 0.01), ("dailyCapFraction", 0.02),
        ("minimumAdjustedEdgeFraction", 0.02), ("maxDailyNflPregameQuotes", 1),
        ("tieTreatment", "STAKE_REFUNDED_PUSH"),
    ):
        _require_exact(auth.get(key), expected, f"authorization.{key}")
    _require_exact(auth.get("scopeOfThisEvidence"), [binding["eventId"]], "authorization scope")
    _require_exact(document["summaries"]["probabilitySemantics"].get("settlementMustBeExplicit"), True, "settlement")
    _require_exact(document["summaries"]["modeledLineSemantics"].get("mayPopulateSportsbookMoneylineSpreadOrTotalFields"), False, "market semantics")


def _manifest(document: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    raw = canonical_json_bytes(document)
    identity = {
        "schemaVersion": "AISP_RESEARCH_SUPPLEMENT_MANIFEST_V1",
        "contractVersion": "AISP_RESEARCH_SUPPLEMENT_V1",
        "supplementId": document["supplementId"],
        "kind": KIND,
        "sport": "NFL",
        "governance": deepcopy(GOVERNANCE),
        "artifacts": [{"file": "supplement.json", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}],
    }
    address = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    return address, {**identity, "supplementSha256": address}


def verify_package(directory: Path) -> dict[str, Any]:
    if {path.name for path in directory.iterdir()} != {"manifest.json", "supplement.json"}:
        raise ValueError("Supplement inventory differs")
    manifest_raw = (directory / "manifest.json").read_bytes()
    document_raw = (directory / "supplement.json").read_bytes()
    manifest = json.loads(manifest_raw)
    document = json.loads(document_raw)
    if manifest_raw != canonical_json_bytes(manifest) or document_raw != canonical_json_bytes(document):
        raise ValueError("Package is not canonical UTF-8 JSON")
    address = str(manifest.pop("supplementSha256"))
    if address != directory.name or hashlib.sha256(canonical_json_bytes(manifest)).hexdigest() != address:
        raise ValueError("Package address differs")
    if manifest["artifacts"] != [{"file": "supplement.json", "sha256": hashlib.sha256(document_raw).hexdigest(), "bytes": len(document_raw)}]:
        raise ValueError("Supplement physical bytes differ")
    for key in ("supplementId", "kind", "sport", "governance"):
        _require_exact(document[key], manifest[key], f"manifest {key}")
    validate_document(document)
    return {"address": address, "document": document, "manifest": physical(directory / "manifest.json"), "supplement": physical(directory / "supplement.json")}


def _atomic_canonical_json(path: Path, value: object) -> dict[str, Any]:
    raw = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    return physical(path)


def _publish_complete_package(directory: Path, document: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    """Publish a complete immutable directory before a discovery index can name it."""
    directory = Path(directory)
    if directory.exists():
        verified = verify_package(directory)
        if verified["document"] != document:
            raise ValueError(f"Existing exact supplement differs: {directory}")
        return
    parent = directory.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging_root = parent / f".staging-{uuid.uuid4().hex}"
    staging = staging_root / directory.name
    staging.mkdir(parents=True, exist_ok=False)
    try:
        immutable_json(staging / "supplement.json", document)
        immutable_json(staging / "manifest.json", manifest)
        verify_package(staging)
        try:
            os.replace(staging, directory)
        except OSError:
            if not directory.exists():
                raise
        verified = verify_package(directory)
        if verified["document"] != document:
            raise ValueError(f"Published exact supplement differs: {directory}")
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)


def publish_week2_successors(
    *,
    exchange_root: Path,
    forecast_ids: Sequence[str],
    output_root: Path = DEFAULT_SUCCESSOR_OUTPUT_ROOT,
    authorization_source_path: Path = DEFAULT_AUTHORIZATION_SOURCE_PATH,
    published_utc: str | None = None,
) -> dict[str, Any]:
    """Publish exact eligibility for newly published Week 2 forecast objects.

    The forecast must already be present in exactly one bundle named by the
    current authoritative locator. Package directories are complete and
    verified before the mutable discovery index is replaced. An identical
    replay verifies and reuses the package without touching the index.
    """
    exchange_root = Path(exchange_root).resolve()
    output_root = Path(output_root).resolve()
    authorization_source_path = Path(authorization_source_path).resolve()
    requested = list(dict.fromkeys(map(str, forecast_ids)))
    if not requested:
        return {
            "schemaVersion": "ASP_NFL_WEEK2_SUCCESSOR_ELIGIBILITY_RUN_V1",
            "requestedForecastCount": 0,
            "supplementsPublished": 0,
            "supplementsReused": 0,
            "indexUpdated": False,
            "packages": [],
        }
    authorization_reference = physical(authorization_source_path)
    locator_path = exchange_root / "aisp-daily-forecast-bundles/nfl-2026-research-shadow-index.json"
    locator = json.loads(locator_path.read_bytes())
    current_addresses = list(map(str, locator.get("currentBundleSha256s") or []))
    found: dict[str, tuple[Mapping[str, Any], dict[str, Any]]] = {}
    for address in current_addresses:
        verified = verify_sports_forecast_bundle(exchange_root, address)
        bundle_path = exchange_root / "aisp-daily-forecast-bundles/sha256" / address / "bundle.json"
        bundle_reference = physical(bundle_path)
        for forecast in verified.record["forecasts"]:
            forecast_id = str(forecast["forecastId"])
            if forecast_id not in requested:
                continue
            if forecast_id in found:
                raise ValueError(f"Forecast resolves in more than one current bundle: {forecast_id}")
            found[forecast_id] = (forecast, bundle_reference)
    missing = sorted(set(requested) - set(found))
    if missing:
        raise ValueError(f"New forecast is absent from current authority: {missing}")

    index_path = exchange_root / "nfl-labs-supplements/nfl-labs-supplement-index.json"
    if index_path.exists():
        prior_raw = index_path.read_bytes()
        prior = json.loads(prior_raw)
        if prior.get("schemaVersion") != INDEX_SCHEMA:
            raise ValueError("Existing NFL supplement index contract differs")
    else:
        prior_raw = None
        prior = {"schemaVersion": INDEX_SCHEMA, "currentSupplementSha256s": []}
    existing_addresses = set(map(str, prior.get("currentSupplementSha256s") or []))
    existing_by_forecast: dict[str, dict[str, Any]] = {}
    for address in sorted(existing_addresses):
        directory = exchange_root / "nfl-labs-supplements/sha256" / address
        if not directory.is_dir():
            raise ValueError(f"Indexed supplement package is unavailable: {address}")
        verified = verify_package(directory)
        document = verified["document"]
        if document.get("artifactVersion") == VERSION and document.get("kind") == KIND:
            forecast_id = str(document["binding"]["forecastId"])
            if forecast_id in existing_by_forecast:
                raise ValueError(f"Multiple indexed eligibility packages bind {forecast_id}")
            existing_by_forecast[forecast_id] = verified

    publication_clock = published_utc or utc_text(datetime.now(timezone.utc))
    rows: list[dict[str, Any]] = []
    newly_published: list[str] = []
    for forecast_id in requested:
        forecast, bundle_reference = found[forecast_id]
        existing = existing_by_forecast.get(forecast_id)
        if existing is None:
            document = build_document(
                forecast,
                bundle_reference=bundle_reference,
                authorization_reference=authorization_reference,
                published_utc=publication_clock,
            )
            validate_document(document)
            address, manifest = _manifest(document)
            exchange_directory = exchange_root / "nfl-labs-supplements/sha256" / address
            local_directory = output_root / "supplements/sha256" / address
            _publish_complete_package(exchange_directory, document, manifest)
            _publish_complete_package(local_directory, document, manifest)
            disposition = "PUBLISHED_NEW_EXACT_SUCCESSOR"
            newly_published.append(address)
        else:
            document = existing["document"]
            expected = build_document(
                forecast,
                bundle_reference=bundle_reference,
                authorization_reference=authorization_reference,
                published_utc=document["publishedUtc"],
            )
            if document != expected:
                raise ValueError(f"Existing exact successor eligibility differs: {forecast_id}")
            address = existing["address"]
            exchange_directory = exchange_root / "nfl-labs-supplements/sha256" / address
            disposition = "IDEMPOTENT_REUSE"
        verified = verify_package(exchange_directory)
        rows.append({
            "eventId": forecast["eventId"],
            "forecastId": forecast_id,
            "snapshotType": forecast["snapshotType"],
            "snapshotVersion": forecast["snapshotVersion"],
            "supplementAddress": address,
            "exchangeDirectory": str(exchange_directory),
            "publicationDisposition": disposition,
            "manifest": verified["manifest"],
            "supplement": verified["supplement"],
        })

    merged = sorted(existing_addresses | {row["supplementAddress"] for row in rows})
    index_updated = bool(newly_published)
    if index_updated:
        successor_index = {
            "schemaVersion": INDEX_SCHEMA,
            "currentSupplementSha256s": merged,
            "updatedAtUtc": publication_clock,
        }
        _atomic_canonical_json(index_path, successor_index)
    elif prior_raw is not None and index_path.read_bytes() != prior_raw:
        raise ValueError("Idempotent successor replay changed the discovery index")
    for row in rows:
        if row["supplementAddress"] not in json.loads(index_path.read_bytes())["currentSupplementSha256s"]:
            raise ValueError("Discovery index omitted a verified successor")
    return {
        "schemaVersion": "ASP_NFL_WEEK2_SUCCESSOR_ELIGIBILITY_RUN_V1",
        "requestedForecastCount": len(requested),
        "supplementsPublished": len(newly_published),
        "supplementsReused": len(requested) - len(newly_published),
        "indexUpdated": index_updated,
        "consumerImportCadenceMinutes": 5,
        "packages": rows,
        "providerRequests": 0,
        "aispWrites": 0,
        "sportsbookRequests": 0,
    }


def publish_week2(
    *, exchange_root: Path, output_root: Path, readiness_path: Path,
    authorization_source_path: Path, published_utc: str | None = None,
) -> dict[str, Any]:
    """Publish/verify all 16 exact effective Week 2 forecast supplements."""
    exchange_root = Path(exchange_root).resolve()
    output_root = Path(output_root).resolve()
    readiness_path = Path(readiness_path).resolve()
    authorization_source_path = Path(authorization_source_path).resolve()
    published = published_utc or utc_text(datetime.now(timezone.utc))
    authorization_reference = physical(authorization_source_path)
    readiness = json.loads(readiness_path.read_bytes())
    forecasts = readiness.get("effectiveForecasts") or []
    if len(forecasts) != 16 or len({item["eventId"] for item in forecasts}) != 16:
        raise ValueError("Week 2 effective cohort is not exactly 16 distinct games")
    locator_path = exchange_root / "aisp-daily-forecast-bundles/nfl-2026-research-shadow-index.json"
    locator = json.loads(locator_path.read_bytes())
    current_addresses = set(locator.get("currentBundleSha256s") or [])
    supplement_index_path = exchange_root / "nfl-labs-supplements/nfl-labs-supplement-index.json"
    existing_addresses: set[str] = set()
    existing_by_forecast: dict[str, dict[str, Any]] = {}
    if supplement_index_path.exists():
        prior = json.loads(supplement_index_path.read_bytes())
        if prior.get("schemaVersion") != INDEX_SCHEMA:
            raise ValueError("Existing NFL supplement index contract differs")
        existing_addresses.update(map(str, prior.get("currentSupplementSha256s") or []))
        for address in sorted(existing_addresses):
            directory = exchange_root / "nfl-labs-supplements/sha256" / address
            if not directory.is_dir():
                continue
            verified = verify_package(directory)
            document = verified["document"]
            if document.get("artifactVersion") != VERSION or document.get("kind") != KIND:
                continue
            forecast_id = str(document["binding"]["forecastId"])
            if forecast_id in existing_by_forecast:
                raise ValueError(f"Multiple current eligibility packages bind {forecast_id}")
            existing_by_forecast[forecast_id] = verified
    package_rows: list[dict[str, Any]] = []
    for summary in sorted(forecasts, key=lambda row: (row["scheduledStartUtc"], row["eventId"])):
        bundle_address = str(summary["bundleAddress"])
        if bundle_address not in current_addresses:
            raise ValueError(f"Bound bundle is no longer current for {summary['eventId']}")
        verified_bundle = verify_sports_forecast_bundle(exchange_root, bundle_address)
        matches = [row for row in verified_bundle.record["forecasts"] if row["forecastId"] == summary["forecastId"]]
        if len(matches) != 1:
            raise ValueError(f"Forecast binding is absent or ambiguous for {summary['eventId']}")
        forecast = matches[0]
        _require_exact(forecast["eventId"], summary["eventId"], "ledger event")
        _require_exact(forecast["scheduledStartUtc"], summary["scheduledStartUtc"], "ledger kickoff")
        bundle_reference = physical(Path(summary["bundle"]["path"]))
        existing = existing_by_forecast.get(str(forecast["forecastId"]))
        if existing is not None:
            document = existing["document"]
            expected = build_document(
                forecast,
                bundle_reference=bundle_reference,
                authorization_reference=authorization_reference,
                published_utc=document["publishedUtc"],
            )
            if document != expected:
                raise ValueError(f"Existing exact-forecast eligibility differs for {forecast['eventId']}")
            address = existing["address"]
            exchange_directory = exchange_root / "nfl-labs-supplements/sha256" / address
            manifest = json.loads((exchange_directory / "manifest.json").read_bytes())
            disposition = "IDEMPOTENT_REUSE"
        else:
            document = build_document(
                forecast,
                bundle_reference=bundle_reference,
                authorization_reference=authorization_reference,
                published_utc=published,
            )
            validate_document(document)
            address, manifest = _manifest(document)
            exchange_directory = exchange_root / "nfl-labs-supplements/sha256" / address
            disposition = "PUBLISHED_NEW_EXACT_OBJECT"
        local_directory = output_root / "supplements/sha256" / address
        for directory in (exchange_directory, local_directory):
            immutable_json(directory / "supplement.json", document)
            immutable_json(directory / "manifest.json", manifest)
            verify_package(directory)
        package_rows.append({
            "eventId": forecast["eventId"],
            "orientation": f"{forecast['awayTeam']['abbreviation']}@{forecast['homeTeam']['abbreviation']}",
            "scheduledStartUtc": forecast["scheduledStartUtc"],
            "decisionWindowOpensUtc": utc_text(utc(forecast["scheduledStartUtc"]) - timedelta(minutes=30)),
            "decisionCutoffUtc": utc_text(utc(forecast["scheduledStartUtc"]) - timedelta(minutes=15)),
            "forecastId": forecast["forecastId"],
            "snapshotType": forecast["snapshotType"],
            "snapshotVersion": forecast["snapshotVersion"],
            "supplementAddress": address,
            "exchangeDirectory": str(exchange_directory),
            "manifest": physical(exchange_directory / "manifest.json"),
            "supplement": physical(exchange_directory / "supplement.json"),
            "publicationDisposition": disposition,
            "consumerAcknowledgement": "NOT_ESTABLISHED",
        })
    # Consumer discovery is mutable by design. Preserve any existing addresses
    # and add this batch; the immutable packages themselves never change.
    existing_addresses.update(row["supplementAddress"] for row in package_rows)
    index = {
        "schemaVersion": INDEX_SCHEMA,
        "currentSupplementSha256s": sorted(existing_addresses),
        "updatedAtUtc": published,
    }
    index_reference = _atomic_canonical_json(supplement_index_path, index)
    batch = {
        "schemaVersion": BATCH_SCHEMA,
        "season": SEASON,
        "week": WEEK,
        "publishedUtc": published,
        "eligibilityMode": "EXACT_CURRENT_OBJECT_SPECIFIC_WITH_CONTROLLED_SUCCESSOR_PUBLICATION",
        "gameCount": 16,
        "firstDecisionWindow": {"eventId": "2026_02_DET_BUF", "opensUtc": "2026-09-17T23:45:00Z", "decisionCutoffUtc": "2026-09-18T00:00:00Z", "kickoffUtc": "2026-09-18T00:15:00Z"},
        "modelIdentity": {"engineId": ENGINE_ID, "engineVersion": ENGINE_VERSION, "modelBinarySha256": MODEL_BINARY_SHA256, "modelManifestSha256": MODEL_MANIFEST_SHA256, "featureContractSha256": FEATURE_CONTRACT_SHA256, "simulatorId": SIMULATOR_ID, "simulatorVersion": SIMULATOR_VERSION, "drawCount": DRAW_COUNT},
        "policy": {"experimentId": EXPERIMENT_ID, "policyVersion": POLICY_VERSION, "stakingVersion": STAKING_VERSION, "virtualInitialBankrollUsd": 1000, "kellyFraction": 0.25, "positionCapFraction": 0.005, "initialPositionCapUsd": 5, "sameGameCapFraction": 0.01, "dailyCapFraction": 0.02, "minimumAdjustedEdgeFraction": 0.02, "maxDailyNflPregameQuotes": 1, "tieTreatment": "STAKE_REFUNDED_PUSH", "realMoneyAuthorized": False},
        "owner": {"system": "AISP existing orchestrator", "currentCadence": "DAILY_05:30_SCHEDULER_TIME", "finalPregameCadence": "EVERY_5_MINUTES_EVENT_GATED_TO_T_MINUS_30_THROUGH_T_MINUS_15", "producerLock": "outputs/nfl-2026-prospective-shadow-v1/nfl-m1-publication.lock", "reuseBehavior": "Unchanged eligible feature vectors reuse the immutable CURRENT forecast; FINAL_PREGAME is only created when the verified vector changes.", "activationQualification": "Code and the 2026-09-13 job receipt establish the owner/cadence. Current process registration has not been independently observed in this producer-only publication."},
        "modeledLineSemantics": {"classification": "MODELED_REFERENCE_SCENARIOS_ONLY", "mayPopulateSportsbookFields": False, "actualMarketEvidenceRequired": True, "mayInferProviderSportsbookObservationOrFreshness": False},
        "consumerPathForDetBuf": ["Import the indexed exact CURRENT v8 forecast if not already registered.", "Import its exact eligibility supplement before 2026-09-17T23:45:00Z.", "At the existing decision window, collect and persist the separately authorized fresh two-sided quote with sportsbook, observed time and settlement.", "Evaluate the exact forecast/eligibility/quote binding under AISP_NFL_PAPER_POLICY_V1 before 2026-09-18T00:00:00Z.", "Create a virtual position only if every existing policy gate passes; a FINAL_PREGAME successor requires its own exact eligibility supplement."],
        "packages": package_rows,
        "references": {"sourceReadiness": physical(readiness_path), "authorizationSource": authorization_reference, "forecastLocator": physical(locator_path), "consumerDiscoveryIndex": index_reference},
        "counts": {"eligibleGames": 16, "supplementsPublished": sum(row["publicationDisposition"] == "PUBLISHED_NEW_EXACT_OBJECT" for row in package_rows), "supplementsReused": sum(row["publicationDisposition"] == "IDEMPOTENT_REUSE" for row in package_rows), "providerRequests": 0, "forecastExecutions": 0, "aispWrites": 0, "quotesRequested": 0, "positionsCreated": 0},
        "consumerAcknowledgement": "NOT_ESTABLISHED",
    }
    batch_raw = canonical_json_bytes(batch)
    batch_digest = hashlib.sha256(batch_raw).hexdigest()
    batch_dir = exchange_root / "nfl-week2-paper-eligibility/sha256" / batch_digest
    immutable_json(batch_dir / "operational-readiness.json", batch)
    immutable_json(output_root / "batch/sha256" / batch_digest / "operational-readiness.json", batch)
    handoff_lines = [
        "# CLAUDE_HANDOFF: NFL Week 2 paper eligibility",
        "",
        f"Published `{published}`. This is producer eligibility evidence for the already authorized `{EXPERIMENT_ID}` virtual research experiment. It grants no real-money, model-promotion, provider-call, or producer-execution authority.",
        "",
        "## Import",
        "",
        f"- Discovery index: `{supplement_index_path}`",
        f"- Supplement root: `{exchange_root / 'nfl-labs-supplements/sha256'}`",
        f"- Contract: `AISP_RESEARCH_SUPPLEMENT_V1` / `{VERSION}` / `{KIND}`",
        "- Import each address below with the existing generic supplement importer after its exact forecast has been registered. The consumer should reject a mismatched event, engine, forecast, model artifact, physical hash, canonical encoding, or authority flag.",
        "- Eligibility is exact-current-object-specific. A later CURRENT or FINAL_PREGAME revision requires a newly verified, separately addressed supplement from this publisher.",
        "",
        "## Policy and probabilities",
        "",
        "Virtual bankroll is $1,000; quarter Kelly is 0.25; position cap is 0.5%/$5; same-game cap is 1%; daily cap is 2%; minimum adjusted edge is 0.02; one daily NFL pregame quote; research only. Equal modeled final scores remain the raw tie mass and settle as a stake-refunded push for this experiment.",
        "",
        "The forecast's moneyline, spread, and total query grids are modeled reference scenarios. They are not sportsbook quotes and cannot populate sportsbook fields. Actual prices require separately persisted provider, sportsbook, observation-time, settlement, and freshness evidence.",
        "",
        "## DET at BUF path",
        "",
        "Import CURRENT v8 and its exact supplement before the 2026-09-17 23:45Z window. The existing consumer owner may then obtain the separately authorized fresh quote, evaluate it, and create a virtual position only if all policy gates pass before 00:00Z. A later FINAL_PREGAME object is unusable until its distinct eligibility supplement exists.",
        "",
        "## Exact bindings",
        "",
        "| Event | Game | Snapshot | Forecast | Supplement | Window opens | Cutoff |",
        "|---|---|---:|---|---|---|---|",
    ]
    handoff_lines.extend(
        f"| {row['eventId']} | {row['orientation']} | {row['snapshotType']} v{row['snapshotVersion']} | `{row['forecastId']}` | `{row['supplementAddress']}` | {row['decisionWindowOpensUtc']} | {row['decisionCutoffUtc']} |"
        for row in package_rows
    )
    handoff_lines.extend([
        "",
        "## Verification",
        "",
        f"`{Path('.venv/Scripts/python.exe')} scripts/verify_nfl_week2_paper_eligibility.py \"{batch_dir / 'operational-readiness.json'}\"`",
        "",
        "Consumer acknowledgement is not established by publication.",
        "",
    ])
    handoff_raw = "\n".join(handoff_lines).encode("utf-8")
    exchange_handoff = immutable_bytes(batch_dir / "CLAUDE_HANDOFF.md", handoff_raw)
    immutable_bytes(output_root / "batch/sha256" / batch_digest / "CLAUDE_HANDOFF.md", handoff_raw)
    delivery_path = batch_dir / "delivery-receipt.json"
    if delivery_path.exists():
        delivery = json.loads(delivery_path.read_bytes())
    else:
        delivery = {
            "schemaVersion": "ASP_NFL_WEEK2_PAPER_ELIGIBILITY_DELIVERY_V1",
            "publicationStartedUtc": published,
            "publicationCompletedUtc": utc_text(datetime.now(timezone.utc)),
            "batchAddress": batch_digest,
            "batchReceipt": physical(batch_dir / "operational-readiness.json"),
            "claudeHandoff": exchange_handoff,
            "consumerDiscoveryIndex": index_reference,
            "gameCount": 16,
            "supplementAddresses": [row["supplementAddress"] for row in package_rows],
            "providerRequests": 0,
            "forecastExecutions": 0,
            "aispWrites": 0,
            "consumerAcknowledgement": "NOT_ESTABLISHED",
        }
        immutable_json(delivery_path, delivery)
    immutable_json(output_root / "batch/sha256" / batch_digest / "delivery-receipt.json", delivery)
    return {
        "schemaVersion": "ASP_NFL_WEEK2_PAPER_ELIGIBILITY_DELIVERY_V1",
        "publishedUtc": published,
        "batchAddress": batch_digest,
        "batchReceipt": physical(batch_dir / "operational-readiness.json"),
        "claudeHandoff": exchange_handoff,
        "deliveryReceipt": physical(delivery_path),
        "consumerIndex": index_reference,
        "gameCount": 16,
        "supplementAddresses": [row["supplementAddress"] for row in package_rows],
        "firstDecisionWindow": batch["firstDecisionWindow"],
        "providerRequests": 0,
        "forecastExecutions": 0,
        "aispWrites": 0,
        "consumerAcknowledgement": "NOT_ESTABLISHED",
    }
