"""A synthetic integration fixture, never a current forecast/publication receipt."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from server.sports_current_statcast.mlb_v18_current_publication import CurrentV18Engine, current_template
from server.sports_current_statcast.mlb_v18_prospective_transform import ProspectiveFrameAuthority, wrap_prospective_pipeline
from server.sports_current_statcast.mlb_v18_whole_game_challenger import V18StateProbabilityProvider, simulate_prospective_game


def test_synthetic_current_engine_5000_legal_games_without_publication():
    engine = CurrentV18Engine()
    contract = engine.contract
    original = pd.read_parquet(contract["artifacts"]["matchedOof"]["path"], filters=[("foldNumber", "=", 5)]).head(32)
    raw = pd.read_parquet(contract["artifacts"]["rawDevelopment"]["path"],
        filters=[("canonicalPaId", "in", original.canonicalPaId.tolist())], columns=contract["rawFeatureColumns"])
    raw = raw.set_index("canonicalPaId", drop=False).loc[original.canonicalPaId, contract["rawFeatureColumns"]]
    assert len(raw) == 32 and raw.game_date.max() <= "2026-08-06"
    # Numeric values belong to a Development reload fixture. These intentionally
    # synthetic event/player combinations are NOT current-source evidence.
    now = datetime.now(timezone.utc)
    kickoff = now + timedelta(hours=4)
    event = "SYNTHETIC_CURRENT_ENGINE_FIXTURE_NOT_A_REAL_GAME"
    authority = ProspectiveFrameAuthority(event, kickoff.date().isoformat(),
        (now-timedelta(minutes=1)).isoformat(), kickoff.isoformat(),
        contract["artifacts"]["rawDevelopment"]["sha256"], now.isoformat(), "UTC")
    pipeline = wrap_prospective_pipeline(engine.pipeline, authority)
    fixture = raw.copy()
    fixture["game_date"] = authority.game_date
    fixture["canonicalGameId"] = event
    rows = fixture.to_dict("records")
    # Repeated slots and staff members are permitted only in this unpublished
    # deterministic software fixture, never as a substitute for a real lineup.
    away, home = rows[:9], rows[9:18]
    away_starter, home_starter = rows[18], rows[19]
    state = {"context_inning": 1, "context_top_bottom": 0, "context_outs_before": 0,
             "context_base_mask_before": 0, "context_batting_score_diff_before": 0}
    with threadpool_limits(limits=4):
        one = current_template(source_order=pipeline.ordered_features, batter_row=away[0],
                               pitcher_row=home_starter, state=state)
        assert one.shape == (1, 246)
        assert one.pitcherCanonicalPlayerId.iloc[0] == home_starter["pitcherCanonicalPlayerId"]
        treated = pipeline.preprocessor.transform_frame(one)
        assert treated.shape == (1, 273)
        assert pipeline.predict_proba(one).shape == (1, 8)
        provider = V18StateProbabilityProvider(pipeline, away, home, away_starter, home_starter,
            [rows[20]], [rows[21]], template_composer=current_template)
        arguments = {"game_id": event, "provider": provider, "transition_model": engine.transition,
                     "master_seed": 20260910, "regulation": 9, "trace_count": 1}
        population = simulate_prospective_game(**arguments, n_sims=5000)
        a = simulate_prospective_game(**arguments, n_sims=64)
        b = simulate_prospective_game(**arguments, n_sims=64)
    assert population["simulationCount"] == 5000
    assert population["nonterminationCount"] == population["illegalStateCount"] == 0
    for key in ("homeRuns", "awayRuns", "innings", "paCounts"):
        assert len(population[key]) == 5000
        assert np.array_equal(a[key], b[key])
    assert a["traces"] == b["traces"]
    assert np.all(population["homeRuns"] != population["awayRuns"])
    assert np.all(population["homeRuns"] >= 0) and np.all(population["awayRuns"] >= 0)
    assert population["homeWinProbability"] == float(np.mean(population["homeRuns"] > population["awayRuns"]))
    assert population["meanTotalRuns"] == float(np.mean(population["homeRuns"] + population["awayRuns"]))
    assert population["traces"][0] and all(1 <= row["battingOrderPosition"] <= 9 for row in population["traces"][0])
    # Only an in-memory simulation result was created: no forecast serializer,
    # publication method, provider, AISP mutation or real output writer called.
