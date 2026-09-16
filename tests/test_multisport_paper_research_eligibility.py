from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from server.sports_shared.paper_research_eligibility import (
    GOVERNANCE,
    canonical_json_bytes,
    publish_document,
    verify_package,
)


def workdir() -> Path:
    path = Path("outputs") / f"multisport-paper-focused-{uuid4().hex}"
    path.mkdir(parents=True)
    return path


def document(root: Path):
    evidence = root / "population.bin"
    evidence.write_bytes(b"paired draws")
    return {
        "schemaVersion": "AISP_RESEARCH_SUPPLEMENT_V1",
        "artifactVersion": "ASP_NBA_PAPER_RESEARCH_ELIGIBILITY_V1",
        "supplementId": "nba-paper:test:v1",
        "kind": "PAPER_RESEARCH_ELIGIBILITY",
        "sport": "NBA",
        "governance": GOVERNANCE,
        "binding": {"eventId": "g", "forecastId": "f"},
        "sourceCutoffUtc": "2026-01-01T00:00:00Z",
        "publishedUtc": "2026-01-02T00:00:00Z",
        "simulation": {"kind": "NONE", "count": 0},
        "summaries": {
            "authorization": {
                "experimentId": "x", "mode": "VIRTUAL_RESEARCH_ONLY",
                "policyVersion": "p", "consumerVirtualExperimentAuthorized": True,
                "realMoneyAuthorized": False,
                "virtualInitialBankrollUsd": 1000, "marketScope": ["MONEYLINE"],
                "kellyFraction": .25, "positionCapFraction": .005,
                "initialPositionCapUsd": 5, "sameGameCapFraction": .01,
                "dailyCapFraction": .02, "minimumAdjustedEdgeFraction": .02,
                "realMoneyExecutionAllowed": False, "wageringOutsideAispAllowed": False,
                "modelPromotionClaim": False,
                "quoteAuthority": "SPORTSGAMEODDS_RESEARCH_QUOTES_ONLY_UNDER_SEPARATE_CONSUMER_POLICY",
            },
            "frozenForecast": {"population": {"forecastId": "f", "drawCount": 10000}},
            "frozenConfiguration": {
                "forecastId": "f", "awayWinProbability": .4, "homeWinProbability": .6,
                "tieProbability": 0, "executionAllowed": False, "modelPromotionAllowed": False,
            },
            "probabilityChannels": {"controllingJoint": {"awayWin": .4, "homeWin": .6, "tie": 0}},
            "probabilitySemantics": {"settlementMustBeExplicit": True},
        },
        "producer": {"physicalReferences": [{"path": str(evidence.resolve()), "sha256": __import__('hashlib').sha256(evidence.read_bytes()).hexdigest(), "bytes": len(evidence.read_bytes())}]},
    }


def test_canonical_utf8_matches_consumer_contract():
    raw = canonical_json_bytes({"experimentName": "NBA virtual research — paper v1"})
    assert b"\\u2014" not in raw
    assert raw == '{"experimentName":"NBA virtual research — paper v1"}'.encode("utf-8")


def test_publish_is_immutable_and_address_is_not_manifest_hash():
    root = workdir()
    doc = document(root)
    receipt = publish_document(doc, exchange_family_root=root / "exchange", output_root=root / "output")
    package = root / "exchange/paper-eligibility/sha256" / receipt["supplementAddress"]
    verified = verify_package(package)
    assert verified["document"] == doc
    assert verified["address"] == receipt["supplementAddress"]
    assert verified["manifest"]["sha256"] != verified["address"]
    assert publish_document(doc, exchange_family_root=root / "exchange", output_root=root / "output")["supplementAddress"] == verified["address"]


def test_rejects_probability_or_population_drift():
    root = workdir()
    doc = document(root)
    doc["summaries"]["probabilityChannels"]["controllingJoint"]["tie"] = .01
    with pytest.raises(ValueError, match="probability mass"):
        publish_document(doc, exchange_family_root=root / "exchange", output_root=root / "output")
    doc = document(root)
    doc["summaries"]["frozenForecast"]["population"]["drawCount"] = 9999
    with pytest.raises(ValueError, match="population"):
        publish_document(doc, exchange_family_root=root / "exchange", output_root=root / "output")
