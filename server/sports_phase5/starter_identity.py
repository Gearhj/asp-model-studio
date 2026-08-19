"""MLB starter-identity projection (MLB_STARTER_IDENTITY_PROJECTION_V1).

Predicts, for each team-game, which pitcher starts — using ONLY information available strictly
before the target game (prior-date rotation cadence, rest, and workload). This closes the last
critical participation oracle in the Phase 5 simulator: the whole-game simulator previously was
told the true starting pitcher.

Formulation: a within-team-game candidate-ranking logistic model. For each team-game a realistic
candidate pool (season-to-date starters ∪ recent starters) is scored for P(this candidate
starts); scores are softmax-normalized within the team-game and the top candidate is the
projected starter. The full distribution is retained for uncertainty diagnostics.

No target-game starter label, same-game usage, or future schedule/results are used as features.
This is a new research component; it does not retrain or modify D3/L1/S2/B1.
"""

from __future__ import annotations

import bisect
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

STARTER_CONTRACT_NAME = "MLB_STARTER_IDENTITY_PROJECTION_V1"
STARTER_SCHEMA_VERSION = "MLB_STARTER_IDENTITY_PROJECTION_V1"

# Candidate pool windows (days). Season-to-date starters plus a recent-start window.
RECENT_START_WINDOW_DAYS = 45
FEATURE_NAMES: tuple[str, ...] = (
    "rotation_turn_proximity",   # -abs(team_games_since_last_start - 5): rotation cadence (non-monotonic made linear)
    "days_turn_proximity",       # -abs(days_since_last_start - 5)
    "team_games_since_last_start",
    "starts_prior_30d",
    "starts_season_to_date",
    "days_since_last_appearance",
    "start_frequency",
    "rest_in_rotation_band",     # 1 if days_since_last_start in [4,6]
    "is_recent_starter",         # appeared in the prior 10 days
)
_CAP = 400  # cap for "days since" when the event never occurred


@dataclass(frozen=True)
class StarterGame:
    game_id: str
    team_id: str
    game_date: str
    season: int
    actual_starter: str
    candidates: tuple[str, ...]
    features: np.ndarray          # (n_candidates, n_features)
    label_index: int              # index of actual starter in candidates, or -1 if pool miss


def build_starter_games(
    starter_rows: Sequence[Mapping[str, Any]],   # {game_id, team_id, game_date(str YYYY-MM-DD), season, starter_id}
    appearance_rows: Sequence[Mapping[str, Any]],  # {team_id, game_date, pitcher_id}
) -> list[StarterGame]:
    """Build per-team-game candidate rows with strictly-prior-date features."""

    import datetime as _dt

    def _d(s: str) -> _dt.date:
        return _dt.date.fromisoformat(str(s)[:10])

    # Per team: chronological list of (date, starter). Per (team, pitcher): sorted start dates.
    team_start_seq: dict[str, list[tuple[_dt.date, str]]] = defaultdict(list)
    for r in starter_rows:
        team_start_seq[str(r["team_id"])].append((_d(r["game_date"]), str(r["starter_id"])))
    for team in team_start_seq:
        team_start_seq[team].sort(key=lambda x: x[0])

    pitcher_start_dates: dict[tuple[str, str], list[_dt.date]] = defaultdict(list)
    for team, seq in team_start_seq.items():
        for dt, pid in seq:
            pitcher_start_dates[(team, pid)].append(dt)
    for key in pitcher_start_dates:
        pitcher_start_dates[key].sort()

    # Per (team, pitcher): sorted appearance dates (start OR relief).
    pitcher_app_dates: dict[tuple[str, str], list[_dt.date]] = defaultdict(list)
    for r in appearance_rows:
        pitcher_app_dates[(str(r["team_id"]), str(r["pitcher_id"]))].append(_d(r["game_date"]))
    for key in pitcher_app_dates:
        pitcher_app_dates[key].sort()

    games: list[StarterGame] = []
    for r in starter_rows:
        team = str(r["team_id"])
        d = _d(r["game_date"])
        season = int(r["season"])
        actual = str(r["starter_id"])
        seq = team_start_seq[team]
        # team-game index (games strictly before d) and season-to-date team games
        dates = [x[0] for x in seq]
        i = bisect.bisect_left(dates, d)  # index of this game among team games
        # candidate pool: season-to-date starters ∪ prior-window starters
        cand: set[str] = set()
        for j in range(i):
            dj, pj = seq[j]
            if dj.year == d.year or dj >= d - _dt.timedelta(days=RECENT_START_WINDOW_DAYS):
                cand.add(pj)
        if not cand:
            continue
        candidates = tuple(sorted(cand))
        season_team_games = sum(1 for dj in dates[:i] if dj.year == d.year)
        feats = np.zeros((len(candidates), len(FEATURE_NAMES)), dtype=np.float64)
        for ci, c in enumerate(candidates):
            sd = pitcher_start_dates[(team, c)]
            k = bisect.bisect_left(sd, d)
            last_start = sd[k - 1] if k > 0 else None
            days_since_start = (d - last_start).days if last_start else _CAP
            # team-games since last start
            if last_start is not None:
                gi = bisect.bisect_left(dates, last_start)
                team_games_since = i - gi
            else:
                team_games_since = _CAP
            starts_30 = sum(1 for x in sd[:k] if x >= d - _dt.timedelta(days=30))
            starts_std = sum(1 for x in sd[:k] if x.year == d.year)
            ad = pitcher_app_dates[(team, c)]
            ak = bisect.bisect_left(ad, d)
            last_app = ad[ak - 1] if ak > 0 else None
            days_since_app = (d - last_app).days if last_app else _CAP
            freq = starts_std / season_team_games if season_team_games else 0.0
            rot_prox = -abs(team_games_since - 5) if team_games_since < _CAP else -20.0
            day_prox = -abs(days_since_start - 5) if days_since_start < _CAP else -20.0
            feats[ci] = [
                rot_prox, day_prox, min(team_games_since, _CAP), starts_30, starts_std,
                min(days_since_app, _CAP), freq,
                1.0 if 4 <= days_since_start <= 6 else 0.0,
                1.0 if days_since_app <= 10 else 0.0,
            ]
        label_index = candidates.index(actual) if actual in cand else -1
        games.append(StarterGame(game_id=str(r["game_id"]), team_id=team, game_date=str(r["game_date"]),
                                  season=season, actual_starter=actual, candidates=candidates,
                                  features=feats, label_index=label_index))
    return games


# --------------------------------------------------------------------------------------
# Baselines and model
# --------------------------------------------------------------------------------------
def baseline_scores(game: StarterGame, kind: str) -> np.ndarray:
    """Return a score per candidate for a simple baseline (higher = more likely to start)."""
    f = game.features
    tgss = f[:, FEATURE_NAMES.index("team_games_since_last_start")]
    rot_prox = f[:, FEATURE_NAMES.index("rotation_turn_proximity")]
    freq = f[:, FEATURE_NAMES.index("start_frequency")]
    if kind == "S0_MOST_OVERDUE":
        # next in rotation ≈ longest wait, but not far-overdue/absent (cap at 7 team-games)
        return np.where(tgss <= 7, tgss, -1.0)
    if kind == "S1_ROTATION_ORDER":
        # team-games-since-last-start closest to a 5-man rotation turn
        return rot_prox
    if kind == "S2_START_FREQUENCY":
        return freq
    raise ValueError(kind)


class StarterIdentityModel:
    """Within-team-game candidate-ranking logistic model (fit on development team-games)."""

    def __init__(self, coef: np.ndarray, intercept: float, mean: np.ndarray, scale: np.ndarray) -> None:
        self.coef = coef
        self.intercept = intercept
        self.mean = mean
        self.scale = scale

    @classmethod
    def fit(cls, games: Sequence[StarterGame]) -> "StarterIdentityModel":
        from sklearn.linear_model import LogisticRegression
        rows = []
        labels = []
        for g in games:
            if g.label_index < 0:
                continue  # pool miss: cannot train a positive; skip for fitting (kept for eval)
            rows.append(g.features)
            lab = np.zeros(len(g.candidates))
            lab[g.label_index] = 1.0
            labels.append(lab)
        X = np.vstack(rows)
        y = np.concatenate(labels)
        mean = X.mean(axis=0)
        scale = X.std(axis=0)
        scale[scale == 0] = 1.0
        Xs = (X - mean) / scale
        est = LogisticRegression(C=1.0, max_iter=2000, solver="lbfgs")
        est.fit(Xs, y)
        return cls(np.asarray(est.coef_[0], dtype=np.float64), float(est.intercept_[0]), mean, scale)

    def candidate_logits(self, game: StarterGame) -> np.ndarray:
        Xs = (game.features - self.mean) / self.scale
        return Xs @ self.coef + self.intercept

    def probabilities(self, game: StarterGame) -> np.ndarray:
        z = self.candidate_logits(game)
        z = z - z.max()
        e = np.exp(z)
        return e / e.sum()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "MLB_STARTER_IDENTITY_LOGISTIC_V1",
            "featureNames": list(FEATURE_NAMES),
            "coef": self.coef.tolist(), "intercept": self.intercept,
            "standardizationMean": self.mean.tolist(), "standardizationScale": self.scale.tolist(),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "StarterIdentityModel":
        return cls(np.asarray(d["coef"], float), float(d["intercept"]),
                   np.asarray(d["standardizationMean"], float), np.asarray(d["standardizationScale"], float))


def rank_metrics(games: Sequence[StarterGame], score_fn) -> dict[str, Any]:
    """Compute top-k accuracy, log loss, Brier, MRR, and coverage for a scoring function."""
    n = 0
    top1 = top2 = top3 = 0
    logloss_sum = 0.0
    brier_sum = 0.0
    mrr_sum = 0.0
    covered = 0
    cand_counts = []
    for g in games:
        n += 1
        cand_counts.append(len(g.candidates))
        if g.label_index < 0:
            # pool miss: model cannot select the true starter; counts against top-k and coverage
            probs = score_fn(g)
            # normalized probs still sum to 1 over wrong candidates -> full log-loss penalty
            logloss_sum += -math.log(1e-12)
            brier_sum += float(np.sum(probs ** 2)) + 1.0  # target vector all-zero on true starter
            continue
        covered += 1
        probs = score_fn(g)
        order = np.argsort(-probs)
        rank = int(np.where(order == g.label_index)[0][0])
        top1 += rank == 0
        top2 += rank <= 1
        top3 += rank <= 2
        mrr_sum += 1.0 / (rank + 1)
        p_true = float(np.clip(probs[g.label_index], 1e-12, 1.0))
        logloss_sum += -math.log(p_true)
        target = np.zeros(len(probs)); target[g.label_index] = 1.0
        brier_sum += float(np.sum((probs - target) ** 2))
    return {
        "teamGames": n,
        "candidatePoolCoverage": covered / n if n else 0.0,
        "top1Accuracy": top1 / n if n else 0.0,
        "top2Accuracy": top2 / n if n else 0.0,
        "top3Accuracy": top3 / n if n else 0.0,
        "top1AccuracyCovered": top1 / covered if covered else 0.0,
        "logLoss": logloss_sum / n if n else 0.0,
        "brier": brier_sum / n if n else 0.0,
        "mrr": mrr_sum / n if n else 0.0,
        "meanCandidateCount": float(np.mean(cand_counts)) if cand_counts else 0.0,
    }


def game_uncertainty(game: StarterGame, probs: np.ndarray) -> dict[str, float]:
    order = np.argsort(-probs)
    top1 = float(probs[order[0]])
    top2 = float(probs[order[1]]) if len(order) > 1 else 0.0
    ent = float(-np.sum(probs * np.log(np.clip(probs, 1e-12, 1.0))))
    return {"topProb": top1, "gapTop1Top2": top1 - top2, "entropy": ent, "candidateCount": len(game.candidates)}


__all__ = [
    "STARTER_CONTRACT_NAME", "STARTER_SCHEMA_VERSION", "FEATURE_NAMES", "RECENT_START_WINDOW_DAYS",
    "StarterGame", "build_starter_games", "baseline_scores", "StarterIdentityModel",
    "rank_metrics", "game_uncertainty",
]
