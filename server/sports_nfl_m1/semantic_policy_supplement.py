"""Non-numerical clarification of the executable feature-treatment policy."""
from __future__ import annotations

import json
from pathlib import Path

from .semantic_lab import immutable_json, digest, OUTPUT


CONTEXT = {
    "season": ("NFL season year associated with event (postseason January belongs to prior season)", "NFL season year", "integer1999-2024 in Development; current schedule year allowed", "not applicable"),
    "week": ("Official schedule week number including postseason weeks", "schedule week", "positive integer1-22 within retained Development", "not applicable"),
    "game_type": ("Official regular-season/postseason round code", "category", "REG,WC,DIV,CON,SB; unknown explicit", "not applicable"),
    "game_month": ("Calendar month of scheduled game date", "month", "integer1-12", "not applicable"),
    "game_weekday": ("Calendar weekday of game date: Sunday0 through Saturday6", "weekday index", "integer0-6", "not applicable"),
    "neutral_site": ("Schedule location equals Neutral", "binary indicator", "0,1; unavailable native missing", "not applicable"),
    "division_game": ("Schedule marks participants in the same division", "binary indicator", "0,1; unavailable native missing", "not applicable"),
    "roof": ("Recorded venue roof/open-closed state; pregame release timing unproven", "roof-status category", "source categories; excluded", "not applicable"),
    "surface": ("Venue playing-surface category", "surface category", "source surface categories plus UNKNOWN", "not applicable"),
    "days_since_previous_game": ("Elapsed calendar days since this team's latest strictly prior completed game in source history", "days", "nonnegative integer; missing before first observed history", "one previous observed team game"),
    "short_week": ("Prior completed game was fewer than6calendar days before scheduled target game", "binary indicator", "0,1; unknown when previous-game date absent", "known prior-date game"),
    "bye_or_long_rest": ("Prior completed game was at least10calendar days before target, including offseason long rests", "binary indicator", "0,1; unknown when previous-game date absent", "known prior-date game"),
    "prior_games": ("Completed team games on strictly earlier calendar dates across all available seasons", "completed team games", "nonnegative integer; observed0 retained; unknown count fails", "raw exact game count (not rate)"),
    "prior_season_games": ("Completed team games earlier in target's CURRENT NFL season (despite legacy column name)", "current-season completed team games", "nonnegative integer; preseason0retained; unknown count fails", "raw exact current-season game count"),
    "source_era_missing": ("Legacy flag prior_games equals0; indicates no observed team history, NOT proof an ingestion outage occurred", "binary no-observed-history flag", "0,1", "prior_games count"),
}

FAMILY_SOURCES = {
    "CORE_TEAM_STRENGTH_CANDIDATES": "nflverse prior completed team-game/PBP sufficient statistics; exact additional materialization absent",
    "QUARTERBACK": "timestamped pregame starter/depth identity and historical player exposure; actual-target-starter authority absent",
    "ROSTER_AND_USAGE": "vintage-stamped roster/depth plus prior snaps/usage; retrospective full-season snapshots insufficient",
    "REST_TRAVEL_AND_CALENDAR": "pregame schedule and versioned venue/timezone coordinates; additional join/materialization absent",
    "VENUE_AND_WEATHER": "stadium metadata or archived issued weather forecasts at decision time; observed game weather is not forecast evidence",
    "ADVANCED_TRACKING_AND_PARTICIPATION": "prior-game nflverse participation/NGS plus permitted tracking/charting evidence; feature-specific exposure not materialized",
    "RECENT_CHARTING": "permitted prior-game FTN charting with dated release; not implemented as candidate inputs",
    "CURRENT_SEASON": "versioned local schedule/roster/depth publication availability; not substantive model features",
}

METRIC_DEFINITIONS = {
    "points_for": ("Team's final scored points, including overtime", "one completed game"),
    "points_against": ("Opponent's final scored points, including overtime", "one completed game"),
    "offensive_epa_per_play": ("Mean source EPA over offensive plays typed pass or run", "nonmissing EPA on pass/run plays"),
    "pass_epa_per_play": ("Mean source EPA over plays typed pass", "nonmissing EPA on pass plays; not all independently classified dropbacks"),
    "rush_epa_per_play": ("Mean source EPA over plays typed run", "nonmissing EPA on run plays"),
    "defensive_epa_per_play": ("Opponent mean EPA on pass/run plays allowed by the team", "opponent nonmissing EPA on pass/run plays"),
    "defensive_pass_epa_per_play": ("Opponent mean pass-play EPA allowed", "opponent nonmissing EPA on pass plays"),
    "defensive_rush_epa_per_play": ("Opponent mean run-play EPA allowed", "opponent nonmissing EPA on run plays"),
    "success_rate": ("Mean source success flag on offensive pass/run plays", "pass/run plays with observed success flag"),
    "defensive_success_rate": ("Opponent source success rate allowed on pass/run plays", "opponent pass/run plays with observed success flag"),
    "explosive_pass_rate": ("Share of pass plays gaining at least20yards", "pass plays with observed yards_gained"),
    "explosive_rush_rate": ("Share of run plays gaining at least10yards", "run plays with observed yards_gained"),
    "defensive_explosive_pass_allowed_rate": ("Opponent share of pass plays gaining at least20yards", "opponent pass plays with observed yards_gained"),
    "defensive_explosive_rush_allowed_rate": ("Opponent share of run plays gaining at least10yards", "opponent run plays with observed yards_gained"),
    "early_down_success_rate": ("Mean source success flag on first/second-down pass/run plays", "down1/2 pass/run plays with observed success flag"),
    "third_down_conversion_rate": ("Mean source third_down_converted flag on rows with down3", "down3rows with observed converted flag; source contract not redesigned"),
    "fourth_down_conversion_rate": ("Mean source fourth_down_converted flag on rows with down4", "down4rows with observed converted flag; source contract not redesigned"),
    "red_zone_td_play_rate": ("Share of pass/run plays from opponent20yard line or closer with touchdown flag", "pass/run plays with yardline_100<=20 and observed touchdown flag; NOT red-zone drives"),
    "turnover_rate": ("Mean maximum of interception/fumble_lost flags over possession-team PBP rows (missing flags source-coalesced0)", "all possession-team play rows in canonical source"),
    "sack_rate": ("Mean sack flag on source qb_dropback=1rows", "qb_dropback=1rows with observed sack flag"),
    "penalty_rate": ("Mean source penalty flag over possession-team PBP rows", "all possession-team rows with observed penalty flag"),
    "seconds_per_play": ("Mean current-minus-next game clock over pass/run rows, source-order sequence, accepted elapsed0to120seconds", "pass/run rows whose next-row elapsed time is between0and120seconds"),
}


def enrich_policy(source: Path, output: Path = OUTPUT):
    original = json.loads(source.read_text())
    policy = json.loads(json.dumps(original))
    policy["contract"] = "NFL_FEATURE_TREATMENT_SPECIFICATION_V1_1"
    policy["predecessorPath"] = str(source)
    policy["predecessorSha256"] = digest(source)
    policy["supplementPurpose"] = "Exact semantic metadata clarification; numerical transformations and fitted authorities unchanged"
    for row in policy["rows"]:
        name = row["feature"]
        stem = name.split("_", 1)[1] if name.startswith(("home_", "away_")) else name
        for window in ("season_to_date", "last_4", "last_8", "last_16"):
            if stem.endswith("_" + window) and stem[:-(len(window)+1)] in METRIC_DEFINITIONS:
                definition, denominator = METRIC_DEFINITIONS[stem[:-(len(window)+1)]]
                row.update(definition=definition + "; historical window=" + window,
                           footballMeaning=definition, underlyingPerGameOpportunityDenominator=denominator,
                           exposureDenominator="Estimator exposure: valid game-average count, recency weighted. Underlying rate denominator: " + denominator,
                           sourceDefinitionLocation="server/sports_nfl/canonical.py:_specs team_game_query; estimator uses fact_nfl_team_game without changing definitions",
                           sparseHistory="4effective-game continuous normal-normal approximate pooling; no fabricated event exposures")
                break
        if stem in CONTEXT:
            definition, units, domain, exposure = CONTEXT[stem]
            row.update(definition=definition, footballMeaning=definition, units=units, validDomain=domain, exposureDenominator=exposure,
                       seasonReset="recompute exact count within target season" if stem == "prior_season_games" else "raw schedule/calendar semantics; no fitted imputation",
                       sparseHistory="preserve observed0counts; native missing for unavailable prior date; explicit unknown category", historicalLiveParity="same source convention and native-missingness; no threshold change")
        if "lagged_" in name:
            meanings = {
                "lagged_qb_epa": ("Prior passing-personnel mixture's pooled EPA/play minus team's last16passing EPA estimate; not a named-starter effect", "EPA per pass play", "real signed"),
                "lagged_qb_uncertainty": ("Square root of weighted within-player posterior variance plus between-player EPA dispersion", "EPA per pass play standard deviation", "nonnegative real"),
                "lagged_passer_entropy": ("Shannon entropy of prior4team-game passer usage weights, natural logarithm", "nats", "nonnegative real;0single supported passer; unknown separate"),
                "lagged_low_exposure_mass": ("Mixture probability weight on previously observed passers with fewer than100effective career EPA plays", "probability mass", "[0,1]"),
                "lagged_historical_team_change_mass": ("Mixture mass on passers already observed on multiple teams before event; not target-day trade/starter status", "probability mass", "[0,1]"),
                "lagged_passer_unknown": ("No strictly prior team passing-personnel observations; does not identify actual rookie starter", "binary indicator", "0,1"),
            }
            if stem in meanings:
                definition, units, domain = meanings[stem]
                row.update(definition=definition, footballMeaning=definition, units=units, validDomain=domain,
                           missingnessReason="No prior passing-personnel history or unavailable PBP; target-game expected starter unknown by design",
                           historicalRows=6991, weeks1to4Rows="See source policy registered coverage and matched results; feature-specific count retained in fitted branch receipts",
                           rationale="Only prior-game observations identify possible passing personnel; no postgame participant leakage or invented injuries",
                           priorHierarchy="C2 league prior -> player posterior; C3 simple prior-exposure/experience peer center -> player posterior; mixture retains uncertainty")
        if row["disposition"].startswith("EXCLUDED_UNSUPPORTED"):
            family = row.get("family", "UNSPECIFIED")
            source = FAMILY_SOURCES.get(family, "Additional authoritative feature-specific pregame source required")
            units = ("canonical player identity" if name.endswith("_id") else "count" if any(v in name for v in ("count", "starts", "addition", "departure")) else "hours" if "hours" in name else "miles" if "miles" in name else "degrees Fahrenheit" if "temperature" in name else "miles per hour" if "wind_mph" in name else "EPA per play" if "epa" in name else "share/rate" if any(v in name for v in ("rate", "share")) else "declared football quantity; exact physical schema not yet registered")
            row.update(footballMeaning=row["definition"], units=units, entityGrain="candidate team/player-pregame; exact subgrain must be registered before activation",
                       validDomain="UNREGISTERED; cannot be activated until units/domain and validation rules are frozen", source=source,
                       sourceIdentity="NO_REGISTERED_POINT_IN_TIME_INPUT_AUTHORITY_FOR_THIS_FEATURE", joinKeys=["canonical_game_id", "team_id", "player_id when applicable"],
                       availability="NOT_ESTABLISHED_FOR_MODEL_INPUT", releaseTiming="Missing pregame vintage or unimplemented prior-date feature materialization",
                       historicalCoverage="NOT_VALIDATED; presence of source archive is not point-in-time feature coverage", currentCoverage="NOT_CONSUMED",
                       missingnessReason=row["reason"], structuralZero="Unknown/source-unavailable never converted to observed0; feature excluded",
                       exposureDenominator="NOT_REGISTERED; no inferred exposure", seasonReset="NOT_EXECUTABLE; exclude until feature-specific prior is approved",
                       sparseHistory="NOT_EXECUTABLE; no median pseudo-evidence", rookieNewEntity="NOT_EXECUTABLE; no fabricated rookie/starter/healthy state",
                       sourceOutage="EXCLUDE; no healthy/no-injury/no-weather assumption", staleEvidence="EXCLUDE; no publication-time replacement of original evidence time",
                       notApplicable="EXCLUDED_INPUT", priorHierarchy="NOT_FITTED", sufficientStatistics="NOT_REGISTERED", reliability="NOT_COMPUTED",
                       recency="NOT_APPLIED", offseasonTreatment="NOT_APPLIED", uncertainty="NOT_COMPUTED", transformation="EXCLUDE",
                       rationale="Existing entitlement/source presence alone does not establish a semantically executable point-in-time model feature",
                       stateIndicators="NOT_CONSUMED; exclusion explicit", historicalLiveParity="Neither historical nor live candidate consumes this field")
    payload = __import__("server.audit_assurance.canonical", fromlist=["canonical_json_bytes"]).canonical_json_bytes(policy)
    sha = __import__("hashlib").sha256(payload).hexdigest()
    target = output / "policy-supplements" / "sha256" / sha / "feature-treatment-policy.json"
    immutable_json(target, policy)
    return {"path": str(target), "sha256": sha, "predecessorSha256": policy["predecessorSha256"], "rows": len(policy["rows"])}


if __name__ == "__main__":
    candidates = sorted((OUTPUT / "runs").glob("*/feature-treatment-policy.json"), key=lambda p: p.stat().st_mtime)
    print(json.dumps(enrich_policy(candidates[-1])))
