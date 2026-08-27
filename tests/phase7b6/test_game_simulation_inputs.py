"""Synthetic, source-free tests for the Phase 7B6 input boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from server.sports_gold import game_simulation_inputs as GI
from server.sports_silver.canonical_ids import canonical_team_id


def _identity_sha(values) -> str:
    normalized = sorted(set(map(str, values)))
    return hashlib.sha256(("\n".join(normalized) + "\n").encode()).hexdigest()


def _study(tmp_path: Path):
    rows = [
        ("FOLD_1", "2022-04-07", "pa-1", "game-1", "retrosheet:game:G1", "SINGLE"),
        ("FOLD_2", "2022-07-26", "pa-2", "game-2", "retrosheet:game:G2", "BIP_OUT"),
        ("FOLD_3", "2023-05-04", "pa-3", "game-3", "retrosheet:game:G3", "DOUBLE"),
        ("FOLD_4", "2023-08-20", "pa-4", "game-4", "retrosheet:game:G4", "STRIKEOUT"),
        ("FOLD_5", "2024-05-30", "pa-5", "game-5", "retrosheet:game:G5", "HOME_RUN"),
        ("HOLDOUT", "2024-09-16", "pa-6", "game-6", "retrosheet:game:G6", "TRIPLE"),
    ]
    frame = pd.DataFrame(
        [
            {
                "plate_appearance_id": pa,
                "canonicalGameId": game,
                "game_id": source,
                "game_date": date,
                "season": int(date[:4]),
                "outcome": label,
            }
            for _, date, pa, game, source, label in rows
        ]
    )
    folds = [
        {
            "foldId": cohort,
            "validationStart": date,
            "validationEnd": date,
            "validationRows": 1,
        }
        for cohort, date, *_ in rows[:5]
    ]
    hold = frame.iloc[-1:]
    request = {
        "folds": folds,
        "holdout": {
            "startDate": "2024-09-16",
            "endDate": "2024-09-16",
            "rowCount": 1,
            "gameCount": 1,
        },
        "holdoutIdentity": {
            "plateAppearanceIdInventorySha256": _identity_sha(hold.plate_appearance_id),
            "gameIdInventorySha256": _identity_sha(hold.game_id),
        },
    }
    request_bytes = json.dumps(
        request, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    root = tmp_path / hashlib.sha256(request_bytes).hexdigest()
    (root / "predictions").mkdir(parents=True)
    (root / "request.json").write_bytes(request_bytes)
    probability = np.full((5, 8), 1.0 / 8.0)
    np.savez_compressed(
        root / "predictions" / "walk-forward-oof.npz",
        rowIds=frame.iloc[:5].plate_appearance_id.to_numpy(dtype=str),
        labels=frame.iloc[:5].outcome.to_numpy(dtype=str),
        component__DIRECT_GOLD=probability,
        ensemble__E10=probability,
    )
    np.savez_compressed(
        root / "predictions" / "walk-forward-oof-reliability.npz",
        RECENT_14_DAY_STATE__observationCount=np.arange(5, dtype=float),
    )
    # Deliberately reproduces the persisted Phase 7B5 object-dtype holdout member.
    np.savez_compressed(
        root / "predictions" / "final-holdout.npz",
        rowIds=np.asarray(["pa-6"], dtype=object),
        labels=np.asarray(["TRIPLE"], dtype=str),
        component__DIRECT_GOLD=np.full((1, 8), 1.0 / 8.0),
        ensemble__E10=np.full((1, 8), 1.0 / 8.0),
    )
    np.savez_compressed(
        root / "predictions" / "final-holdout-reliability.npz",
        RECENT_14_DAY_STATE__observationCount=np.ones(1),
    )
    artifacts = {}
    for relative in GI._STUDY_INPUT_ARTIFACTS:
        body = (root / relative).read_bytes()
        artifacts[relative] = {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    (root / "manifest.json").write_text(
        json.dumps({"request": request, "artifacts": artifacts}, sort_keys=True),
        encoding="utf-8",
    )
    return root, frame


def test_prediction_loader_never_deserializes_holdout_object_row_ids(tmp_path):
    root, frame = _study(tmp_path)
    study = GI.verify_phase7b5_study(root, verify_all=False)
    cohorts = GI.load_prediction_cohorts(study, frame)

    assert tuple(cohorts) == (
        "FOLD_1",
        "FOLD_2",
        "FOLD_3",
        "FOLD_4",
        "FOLD_5",
        "HOLDOUT",
    )
    assert cohorts["HOLDOUT"].row_ids == ("pa-6",)
    assert cohorts["HOLDOUT"].labels == ("TRIPLE",)
    assert set(cohorts["HOLDOUT"].probability_matrices) == {"DIRECT_GOLD", "E10"}
    assert not cohorts["HOLDOUT"].probability_matrices["E10"].flags.writeable
    with np.load(root / "predictions" / "final-holdout.npz", allow_pickle=False) as package:
        with pytest.raises(ValueError, match="Object arrays"):
            package["rowIds"]


def test_study_byte_tamper_is_rejected(tmp_path):
    root, _ = _study(tmp_path)
    path = root / "predictions" / "final-holdout-reliability.npz"
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(GI.GameSimulationInputError, match="artifact bytes differ"):
        GI.verify_phase7b5_study(root, verify_all=False)


def _authority_frames():
    target = pd.DataFrame(
        [{"canonicalGameId": "game-a", "game_id": "retrosheet:game:AAA202404010"}]
    )
    lineup = []
    for side, prefix in (("away", "a"), ("home", "h")):
        for slot in range(1, 10):
            player = "two-way" if side == "home" and slot == 1 else f"{prefix}{slot}"
            lineup.append(
                {
                    "canonicalGameId": "game-a",
                    "retroGameId": "AAA202404010",
                    "playerCanonicalPlayerId": player,
                    "recordType": "start",
                    "season": "2024",
                    "homeAway": side,
                    "battingOrder": str(slot),
                    "fieldPosition": "10" if slot == 1 else "7",
                }
            )
        lineup.append(
            {
                "canonicalGameId": "game-a",
                "retroGameId": "AAA202404010",
                "playerCanonicalPlayerId": "two-way" if side == "home" else "away-sp",
                "recordType": "start",
                "season": "2024",
                "homeAway": side,
                "battingOrder": "0",
                "fieldPosition": "1",
            }
        )
    lineup.append(
        {
            **lineup[0],
            "playerCanonicalPlayerId": "actual-sub-not-pregame",
            "recordType": "sub",
        }
    )
    dim = pd.DataFrame(
        [
            {
                "canonicalGameId": "game-a",
                "mlbamGamePk": "123",
                "gameDate": "2024-04-01",
                "season": "2024",
                "homeTeam": "AAA",
                "awayTeam": "BBB",
                "gameType": "R",
                "retrosheetGameId": "AAA202404010",
                "gameNumber": "0",
                "reconciliationStatus": "MATCHED_EXACT",
            }
        ]
    )
    teams = pd.DataFrame(
        [
            {
                "canonicalGameId": "game-a",
                "retroGameId": "AAA202404010",
                "canonicalTeamId": canonical_team_id("BBB"),
                "homeAway": "away",
                "season": "2024",
                "gameDate": "2024-04-01",
                "gameNumber": "0",
                "parkId": "park-a",
                "runsScored": "3",
                "runsAllowed": "4",
            },
            {
                "canonicalGameId": "game-a",
                "retroGameId": "AAA202404010",
                "canonicalTeamId": canonical_team_id("AAA"),
                "homeAway": "home",
                "season": "2024",
                "gameDate": "2024-04-01",
                "gameNumber": "0",
                "parkId": "park-a",
                "runsScored": "4",
                "runsAllowed": "3",
            },
        ]
    )
    return target, pd.DataFrame(lineup), dim, teams


def test_pregame_authority_preserves_dual_role_and_excludes_substitutions():
    games, truth = GI.build_pregame_games(*_authority_frames())
    game = games["game-a"]

    assert game.prediction_game_id == "retrosheet:game:AAA202404010"
    assert game.home.batting_order[0] == "two-way"
    assert game.home.starting_pitcher_id == "two-way"
    assert "actual-sub-not-pregame" not in game.away.batting_order
    assert len(game.away.batting_order) == len(game.home.batting_order) == 9
    assert (truth["game-a"].away_runs, truth["game-a"].home_runs) == (3, 4)


def test_fd1_first_five_is_explicit_and_rejects_2025_before_open(tmp_path, monkeypatch):
    root = tmp_path / "play_transition"
    part = root / "season=2024" / "part.parquet"
    part.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "game_id": "retrosheet:game:AAA202404010",
                    "season": 2024,
                    "play_number": 40,
                    "inning": 5,
                    "top_bottom": 1,
                    "visiting_score_before": 2,
                    "home_score_before": 1,
                },
                {
                    "game_id": "retrosheet:game:AAA202404010",
                    "season": 2024,
                    "play_number": 41,
                    "inning": 6,
                    "top_bottom": 0,
                    "visiting_score_before": 2,
                    "home_score_before": 3,
                },
            ]
        ),
        part,
    )
    truth = GI.load_fd1_first_five_truth(
        root,
        {2024: [part]},
        ["retrosheet:game:AAA202404010"],
    )
    assert truth == {"retrosheet:game:AAA202404010": (2, 3)}

    opened = False

    def forbidden_open(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("no parquet may open")

    monkeypatch.setattr(GI.pq, "read_table", forbidden_open)
    with pytest.raises(GI.GameSimulationInputError, match="rejected before open"):
        GI.load_fd1_first_five_truth(root, {2025: [part]}, [])
    assert opened is False
