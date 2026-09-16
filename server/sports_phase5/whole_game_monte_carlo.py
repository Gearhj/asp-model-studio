"""Whole-game Monte Carlo engine (MLB_WHOLE_GAME_MONTE_CARLO_V1).

The smallest stochastic driver around the four proven Phase 5 components — the D3 PA-outcome
provider, the Phase 5B empirical base-out transition model, actual historical participants
(oracle mode), and the deterministic Phase 5A kernel semantics. It samples whole games and
returns game-level score distributions for a historical backtest.

Performance: a game's ``n`` simulations advance in lockstep, one plate appearance per step,
so the D3 logits are evaluated for all active simulations at once. The D3 multinomial-logistic
predictor is decomposed so each player's frozen cumulative B-state contributes a fixed
8-vector (precomputed once per game); only the cheap current-game context terms
(inning / half / outs / base / score differential) vary per PA. This reproduces the governed
D3 probabilities exactly while making a full-season backtest tractable.

ORACLE PARTICIPANT POLICY (documented limitation): participants are keyed to the batting
team's plate-appearance ordinal from the actual historical game — the k-th time a team bats it
faces the batter/pitcher it actually faced on its k-th PA (this replays the real batting order,
substitutions, and pitcher changes by PA ordinal). When a simulated game runs longer than the
actual game (e.g., sampled extra innings), the batting order continues from the starting lineup
and the last actual pitcher is retained. This is NOT a prospective participation decision; it
is an oracle upper-bound reference.

No win/run-line/total probabilities, no betting logic, no sportsbook data. This module produces
score distributions only; winner probability is a game-distribution diagnostic computed by the
evaluation layer, never a market comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

import numpy as np

from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_modeling.training import MultinomialCandidateModel
from server.sports_phase4.dynamic_contract import STATE_VALUE_COLUMNS
from server.sports_phase5 import base_out_transition as bt
from server.sports_phase5.game_initialization import RngLineage
from server.sports_phase5.pa_provider import D3ProbabilisticPAProvider, PlayerStateResolver

MONTE_CARLO_CONTRACT_NAME = "MLB_WHOLE_GAME_MONTE_CARLO_V1"
MONTE_CARLO_SCHEMA_VERSION = "MLB_WHOLE_GAME_MONTE_CARLO_V1"
PARTICIPANT_MODE = "HISTORICAL_PARTICIPANTS_ORACLE_MODE"

SECOND_BASE_MASK = 2  # runner on second (bit1); extra-inning automatic runner
DEFAULT_REGULATION = 9
MAX_INNINGS_WATCHDOG = 30
MAX_PA_PER_GAME_WATCHDOG = 200
MAX_TEAM_PA = 130  # padded participant sequence length (covers ~ 25 innings)


class MonteCarloError(RuntimeError):
    """Structural fault in the whole-game driver (never used to hide a legality defect)."""


@dataclass(frozen=True)
class SimulatedPAStateBatch:
    """Read-only simulated pre-PA state supplied to an arbitrary probability provider.

    Every array has shape ``(n_sims,)`` and is aligned by simulation index.  Terminal rows
    remain present (with ``active=False``) so the engine keeps its historical fixed-size RNG
    draw pattern.  ``batting_team_pa_ordinal`` is zero-based and selects the batting team's
    participant/context row for the pending plate appearance.
    """

    inning: np.ndarray
    is_top: np.ndarray
    outs_before: np.ndarray
    base_mask_before: np.ndarray
    away_score_before: np.ndarray
    home_score_before: np.ndarray
    batting_score_diff_before: np.ndarray
    batting_team_pa_ordinal: np.ndarray
    active: np.ndarray


class PAProbabilityProvider(Protocol):
    """Callable returning ``(n_sims, 8)`` probabilities in ``PA_CLASS_ORDER``."""

    def __call__(self, state: SimulatedPAStateBatch, /) -> np.ndarray:
        """Score one vectorized simulated plate-appearance state batch."""


# --------------------------------------------------------------------------------------
# Decomposed fast D3 logit evaluator
# --------------------------------------------------------------------------------------
class FastD3Fold:
    """Decomposes one D3 fold's multinomial-logistic predictor for vectorized scoring.

    Reproduces the governed D3 softmax exactly: the linear predictor is split into a fixed
    per-player cumulative-state contribution (precomputed once) plus cheap current-game context
    terms evaluated per plate appearance.
    """

    def __init__(self, model: MultinomialCandidateModel) -> None:
        coef = np.asarray(model.estimator.coef_, dtype=np.float64)   # (8,43)
        if coef.shape != (len(PA_CLASS_ORDER), 43):
            raise MonteCarloError("unexpected D3 coefficient shape")
        self.intercept = np.asarray(model.estimator.intercept_, dtype=np.float64)
        ns = model.preprocessor.numeric_state

        def _num(name: str) -> tuple[float, float, float]:
            s = ns[name]
            return float(s["imputationMean"]), float(s["standardizationMean"]), float(s["standardizationScale"])

        self.coef_inning = coef[:, 0]
        _, self.inning_mean, self.inning_scale = _num("context_inning")
        self.coef_tb = coef[:, 1:3]
        self.coef_outs = coef[:, 3:6]
        self.coef_base = coef[:, 6:14]
        self.coef_sd = coef[:, 14]
        _, self.sd_mean, self.sd_scale = _num("context_batting_score_diff_before")
        self.batter_coef = coef[:, 15:29]
        self.pitcher_coef = coef[:, 29:43]
        self.b_impute = np.empty(14); self.b_mean = np.empty(14); self.b_scale = np.empty(14)
        self.p_impute = np.empty(14); self.p_mean = np.empty(14); self.p_scale = np.empty(14)
        for i, name in enumerate(STATE_VALUE_COLUMNS):
            self.b_impute[i], self.b_mean[i], self.b_scale[i] = _num(f"batter_b_{name}")
            self.p_impute[i], self.p_mean[i], self.p_scale[i] = _num(f"pitcher_b_{name}")

    @classmethod
    def from_model(cls, model: MultinomialCandidateModel) -> "FastD3Fold":
        return cls(model)

    @staticmethod
    def _standardize(raw: np.ndarray, impute: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
        filled = np.where(np.isfinite(raw), raw, impute)
        return (filled - mean) / scale

    def batter_contrib(self, raw14: np.ndarray) -> np.ndarray:
        return self.batter_coef @ self._standardize(raw14, self.b_impute, self.b_mean, self.b_scale)

    def pitcher_contrib(self, raw14: np.ndarray) -> np.ndarray:
        return self.pitcher_coef @ self._standardize(raw14, self.p_impute, self.p_mean, self.p_scale)

    def context_base_logits(self, inning: np.ndarray, tb: np.ndarray, outs: np.ndarray,
                            base: np.ndarray, score_diff: np.ndarray) -> np.ndarray:
        """Vectorized context contribution to the logits, shape (N,8)."""
        inning_std = (inning.astype(np.float64) - self.inning_mean) / self.inning_scale
        sd_std = (score_diff.astype(np.float64) - self.sd_mean) / self.sd_scale
        # (N,8) = outer(inning_std, coef_inning)
        z = self.intercept[None, :] \
            + inning_std[:, None] * self.coef_inning[None, :] \
            + sd_std[:, None] * self.coef_sd[None, :] \
            + self.coef_tb.T[tb] \
            + self.coef_outs.T[outs] \
            + self.coef_base.T[base]
        return z


def _softmax_rows(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def _readonly_view(values: np.ndarray) -> np.ndarray:
    """Return an aligned read-only view without copying the simulator's state arrays."""

    view = values.view()
    view.setflags(write=False)
    return view


def _provider_probabilities(
    provider: PAProbabilityProvider,
    state: SimulatedPAStateBatch,
    n_sims: int,
) -> np.ndarray:
    """Invoke and fail-closed validate one governed-order provider matrix."""

    try:
        probabilities = np.asarray(provider(state), dtype=np.float64)
    except Exception as exc:
        raise MonteCarloError("PA probability provider failed") from exc
    expected = (n_sims, len(PA_CLASS_ORDER))
    if probabilities.shape != expected:
        raise MonteCarloError(
            f"PA probability provider returned shape {probabilities.shape}; expected {expected}"
        )
    if not np.isfinite(probabilities).all():
        raise MonteCarloError("PA probability provider returned non-finite values")
    if np.any(probabilities < 0.0):
        raise MonteCarloError("PA probability provider returned negative values")
    row_sums = probabilities.sum(axis=1)
    if not np.allclose(row_sums, 1.0, rtol=0.0, atol=1e-12):
        raise MonteCarloError("PA probability provider rows must sum to one")
    return probabilities


# --------------------------------------------------------------------------------------
# Vectorized transition sampler
# --------------------------------------------------------------------------------------
class FastTransitionSampler:
    """Precomputes per-cell cumulative transition distributions for vectorized sampling."""

    def __init__(self, model: bt.TransitionModel) -> None:
        self._cum: dict[int, np.ndarray] = {}
        self._trans: dict[int, np.ndarray] = {}
        for ci, outcome in enumerate(bt.PA_CLASSES):
            for outs in range(3):
                for base in range(8):
                    dist = model.distribution(outcome, outs, base)
                    ts = dist["transitions"]
                    probs = np.array([t["probability"] for t in ts], dtype=np.float64)
                    trans = np.array([[t["outsAdded"], t["baseMaskAfter"], t["runs"]] for t in ts], dtype=np.int64)
                    cell = ci * 24 + outs * 8 + base
                    self._cum[cell] = np.cumsum(probs)
                    self._trans[cell] = trans

    def sample(self, cells: np.ndarray, u: np.ndarray) -> np.ndarray:
        """Return (M,3) sampled transitions for cell indices ``cells`` and uniforms ``u``."""
        out = np.empty((cells.shape[0], 3), dtype=np.int64)
        for cell in np.unique(cells):
            mask = cells == cell
            cum = self._cum[int(cell)]
            idx = np.searchsorted(cum, u[mask], side="right")
            np.clip(idx, 0, len(cum) - 1, out=idx)
            out[mask] = self._trans[int(cell)][idx]
        return out


# --------------------------------------------------------------------------------------
# Per-game participant contribution sequences (oracle mode)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class GameContribs:
    """Precomputed per-team batter/pitcher D3 contribution sequences for one game."""

    away_batter: np.ndarray   # (MAX_TEAM_PA, 8)
    away_pitcher: np.ndarray  # (MAX_TEAM_PA, 8)
    home_batter: np.ndarray   # (MAX_TEAM_PA, 8)
    home_pitcher: np.ndarray  # (MAX_TEAM_PA, 8)
    regulation: int


def build_game_contribs(
    *,
    fold: FastD3Fold,
    resolver: PlayerStateResolver,
    game_date: str,
    regulation: int,
    away_pa_uuids: Sequence[tuple[str, str]],   # ordered (batter_uuid, pitcher_uuid) for away PAs
    home_pa_uuids: Sequence[tuple[str, str]],
    away_start_batter_uuids: Sequence[str],     # 9 starting-lineup batter uuids (rotation overflow)
    home_start_batter_uuids: Sequence[str],
) -> GameContribs:
    cache_b: dict[str, np.ndarray] = {}
    cache_p: dict[str, np.ndarray] = {}

    def bc(uuid: str) -> np.ndarray:
        if uuid not in cache_b:
            cache_b[uuid] = fold.batter_contrib(np.asarray(resolver.resolve(uuid, "BATTER", game_date), dtype=np.float64))
        return cache_b[uuid]

    def pc(uuid: str) -> np.ndarray:
        if uuid not in cache_p:
            cache_p[uuid] = fold.pitcher_contrib(np.asarray(resolver.resolve(uuid, "PITCHER", game_date), dtype=np.float64))
        return cache_p[uuid]

    def build(pa_uuids: Sequence[tuple[str, str]], start_batters: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
        n = len(pa_uuids)
        bat = np.empty((MAX_TEAM_PA, 8), dtype=np.float64)
        pit = np.empty((MAX_TEAM_PA, 8), dtype=np.float64)
        last_pitcher = pa_uuids[-1][1] if n else start_batters[0]
        for k in range(MAX_TEAM_PA):
            if k < n:
                bat[k] = bc(pa_uuids[k][0])
                pit[k] = pc(pa_uuids[k][1])
            else:
                bat[k] = bc(start_batters[k % len(start_batters)])
                pit[k] = pc(last_pitcher)
        return bat, pit

    ab, ap = build(list(away_pa_uuids), list(away_start_batter_uuids))
    hb, hp = build(list(home_pa_uuids), list(home_start_batter_uuids))
    return GameContribs(away_batter=ab, away_pitcher=ap, home_batter=hb, home_pitcher=hp, regulation=regulation)


# --------------------------------------------------------------------------------------
# Whole-game simulation (vectorized over n simulations)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class GameSimResult:
    game_id: str
    n_sims: int
    away_runs: np.ndarray     # (n_sims,)
    home_runs: np.ndarray
    innings: np.ndarray
    pa_counts: np.ndarray
    home_win: np.ndarray      # bool (n_sims,)  ties impossible under MLB rules
    nonterminated: int
    illegal_states: int
    first_five_away_runs: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.int64)
    )
    first_five_home_runs: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.int64)
    )

    @property
    def first_five_complete(self) -> np.ndarray:
        """Mask of simulations with a captured score after the bottom of the fifth."""

        if (
            self.first_five_away_runs.shape != (self.n_sims,)
            or self.first_five_home_runs.shape != (self.n_sims,)
        ):
            return np.zeros(self.n_sims, dtype=bool)
        return (self.first_five_away_runs >= 0) & (self.first_five_home_runs >= 0)

    def summary(self) -> dict[str, Any]:
        away = self.away_runs.astype(np.float64)
        home = self.home_runs.astype(np.float64)
        total = away + home
        diff = home - away
        first_five_complete = self.first_five_complete
        if (
            self.first_five_away_runs.shape == (self.n_sims,)
            and self.first_five_home_runs.shape == (self.n_sims,)
        ):
            first_five_away = self.first_five_away_runs[first_five_complete].astype(np.float64)
            first_five_home = self.first_five_home_runs[first_five_complete].astype(np.float64)
        else:
            first_five_away = np.empty(0, dtype=np.float64)
            first_five_home = np.empty(0, dtype=np.float64)
        first_five_total = first_five_away + first_five_home
        first_five_diff = first_five_home - first_five_away
        qs = [5, 10, 25, 50, 75, 90, 95]

        def q(a: np.ndarray) -> dict[str, float]:
            return {f"p{p}": float(np.percentile(a, p)) for p in qs}

        first_five_count = int(first_five_complete.sum())
        if first_five_count:
            first_five_summary: dict[str, Any] = {
                "firstFiveMeanAwayRuns": float(first_five_away.mean()),
                "firstFiveMeanHomeRuns": float(first_five_home.mean()),
                "firstFiveMeanTotalRuns": float(first_five_total.mean()),
                "firstFiveMeanRunDiff": float(first_five_diff.mean()),
                "firstFiveHomeWinProb": float((first_five_diff > 0).mean()),
                "firstFiveAwayWinProb": float((first_five_diff < 0).mean()),
                "firstFiveTieProb": float((first_five_diff == 0).mean()),
                "firstFiveAwayQuantiles": q(first_five_away),
                "firstFiveHomeQuantiles": q(first_five_home),
                "firstFiveTotalQuantiles": q(first_five_total),
            }
        else:
            first_five_summary = {
                "firstFiveMeanAwayRuns": None,
                "firstFiveMeanHomeRuns": None,
                "firstFiveMeanTotalRuns": None,
                "firstFiveMeanRunDiff": None,
                "firstFiveHomeWinProb": None,
                "firstFiveAwayWinProb": None,
                "firstFiveTieProb": None,
                "firstFiveAwayQuantiles": {},
                "firstFiveHomeQuantiles": {},
                "firstFiveTotalQuantiles": {},
            }
        return {
            "gameId": self.game_id,
            "nSims": self.n_sims,
            "meanAwayRuns": float(away.mean()),
            "meanHomeRuns": float(home.mean()),
            "medianAwayRuns": float(np.median(away)),
            "medianHomeRuns": float(np.median(home)),
            "meanTotalRuns": float(total.mean()),
            "meanRunDiff": float(diff.mean()),
            "homeWinProb": float(self.home_win.mean()),
            "awayWinProb": float(1.0 - self.home_win.mean()),
            "meanInnings": float(self.innings.mean()),
            "extraInningRate": float((self.innings > self.regulation()).mean()),
            "awayQuantiles": q(away),
            "homeQuantiles": q(home),
            "totalQuantiles": q(total),
            "firstFiveCompletedSimulations": first_five_count,
            "firstFiveCompletionRate": float(first_five_count / self.n_sims),
            **first_five_summary,
            "nonterminated": self.nonterminated,
            "illegalStates": self.illegal_states,
        }

    def regulation(self) -> int:
        return DEFAULT_REGULATION


def simulate_game(
    *,
    game_id: str,
    contribs: GameContribs,
    fold: FastD3Fold | None,
    transition_sampler: FastTransitionSampler,
    rng_lineage: RngLineage,
    n_sims: int,
    check_legality: bool = False,
    fixed_probs: np.ndarray | None = None,
    probability_provider: PAProbabilityProvider | None = None,
) -> GameSimResult:
    """Simulate ``n_sims`` whole games in lockstep and return score distributions.

    Exactly one probability mode is required.  ``fold`` preserves the governed decomposed-D3
    path.  ``fixed_probs`` (an 8-vector) preserves the G0 league-average baseline.
    ``probability_provider`` receives the current vectorized simulated state and supplies one
    governed-order probability row per simulation.  All modes use the same fixed-size PA and
    transition RNG draws.
    """

    mode_count = sum(
        mode is not None for mode in (fold, fixed_probs, probability_provider)
    )
    if mode_count != 1:
        raise MonteCarloError(
            "simulate_game requires exactly one of fold, fixed_probs, or probability_provider"
        )
    fixed_cum = None if fixed_probs is None else np.cumsum(np.asarray(fixed_probs, dtype=np.float64))
    reg = contribs.regulation
    pa_rng = rng_lineage.pa_rng()
    tr_rng = rng_lineage.transition_rng()

    inning = np.ones(n_sims, dtype=np.int64)
    top = np.ones(n_sims, dtype=bool)          # True = top (away batting)
    outs = np.zeros(n_sims, dtype=np.int64)
    base = np.zeros(n_sims, dtype=np.int64)
    away_score = np.zeros(n_sims, dtype=np.int64)
    home_score = np.zeros(n_sims, dtype=np.int64)
    away_pa = np.zeros(n_sims, dtype=np.int64)
    home_pa = np.zeros(n_sims, dtype=np.int64)
    n_pa = np.zeros(n_sims, dtype=np.int64)
    terminal = np.zeros(n_sims, dtype=bool)
    first_five_away = np.full(n_sims, -1, dtype=np.int64)
    first_five_home = np.full(n_sims, -1, dtype=np.int64)
    illegal = 0

    step = 0
    while not terminal.all():
        step += 1
        if step > MAX_PA_PER_GAME_WATCHDOG:
            break
        active = ~terminal
        # Sample PA class (fixed-size draw for reproducibility regardless of active mask).
        u_cls = pa_rng.random(n_sims)
        if fixed_cum is not None:
            cls_idx = np.searchsorted(fixed_cum, u_cls, side="right")
        elif probability_provider is not None:
            batting_score_diff = np.where(
                top, away_score - home_score, home_score - away_score
            )
            batting_team_pa = np.where(top, away_pa, home_pa)
            state = SimulatedPAStateBatch(
                inning=_readonly_view(inning),
                is_top=_readonly_view(top),
                outs_before=_readonly_view(outs),
                base_mask_before=_readonly_view(base),
                away_score_before=_readonly_view(away_score),
                home_score_before=_readonly_view(home_score),
                batting_score_diff_before=_readonly_view(batting_score_diff),
                batting_team_pa_ordinal=_readonly_view(batting_team_pa),
                active=_readonly_view(active),
            )
            probabilities = _provider_probabilities(
                probability_provider, state, n_sims
            )
            cumulative = np.cumsum(probabilities, axis=1)
            cls_idx = (cumulative < u_cls[:, None]).sum(axis=1)
        else:
            # Participant contributions keyed to batting-team PA ordinal (capped index).
            a_idx = np.clip(away_pa, 0, MAX_TEAM_PA - 1)
            h_idx = np.clip(home_pa, 0, MAX_TEAM_PA - 1)
            batter_c = np.where(top[:, None], contribs.away_batter[a_idx], contribs.home_batter[h_idx])
            pitcher_c = np.where(top[:, None], contribs.away_pitcher[a_idx], contribs.home_pitcher[h_idx])
            score_diff = np.where(top, away_score - home_score, home_score - away_score)
            tb = np.where(top, 0, 1)
            z = fold.context_base_logits(inning, tb, outs, base, score_diff) + batter_c + pitcher_c
            probs = _softmax_rows(z)
            cum = np.cumsum(probs, axis=1)
            cls_idx = (cum < u_cls[:, None]).sum(axis=1)
        np.clip(cls_idx, 0, len(PA_CLASS_ORDER) - 1, out=cls_idx)

        # Sample transition.
        u_tr = tr_rng.random(n_sims)
        cells = cls_idx * 24 + outs * 8 + base
        trans = transition_sampler.sample(cells, u_tr)  # (n,3)
        outs_added = trans[:, 0]
        base_after = trans[:, 1]
        runs = trans[:, 2]

        if check_legality:
            for i in np.nonzero(active)[0]:
                if not bt.is_legal(int(outs[i]), int(base[i]), (int(outs_added[i]), int(base_after[i]), int(runs[i]))):
                    illegal += 1

        # Apply runs to the batting team (active only).
        away_score = away_score + np.where(active & top, runs, 0)
        home_score = home_score + np.where(active & ~top, runs, 0)
        outs_after = outs + outs_added
        n_pa = n_pa + active.astype(np.int64)
        away_pa = away_pa + (active & top).astype(np.int64)
        home_pa = home_pa + (active & ~top).astype(np.int64)

        # Walk-off: bottom half, regulation-or-later, home takes the lead -> immediate win.
        walk_off = active & (~top) & (inning >= reg) & (home_score > away_score)

        ends = active & (~walk_off) & (outs_after >= 3)
        cont = active & (~walk_off) & (outs_after < 3)
        base = np.where(cont, base_after, base)
        outs = np.where(cont, outs_after, outs)

        # Snapshot the score when each simulation finishes the bottom of the fifth.  The
        # walk-off arm only matters for nonstandard five-inning regulation; normal MLB games
        # capture on the third out.  -1 remains an explicit incomplete/watchdog sentinel.
        bottom_five_finished = (
            active & (~top) & (inning == 5) & (walk_off | ends)
        )
        capture_first_five = bottom_five_finished & (first_five_away < 0)
        first_five_away = np.where(
            capture_first_five, away_score, first_five_away
        )
        first_five_home = np.where(
            capture_first_five, home_score, first_five_home
        )

        # Terminal after a completed half-inning.
        end_bottom_decided = ends & (~top) & (inning >= reg) & (away_score != home_score)
        end_top_home_leads = ends & top & (inning >= reg) & (home_score > away_score)
        become_terminal = walk_off | end_bottom_decided | end_top_home_leads

        # Half-inning switch for ends that do not terminate.
        switch = ends & (~become_terminal)
        was_top = switch & top
        was_bottom = switch & (~top)
        inning = np.where(was_bottom, inning + 1, inning)
        top = np.where(was_top, False, top)
        top = np.where(was_bottom, True, top)
        outs = np.where(switch, 0, outs)
        base = np.where(switch, 0, base)
        # Extra-inning automatic runner on second at each half start beyond regulation.
        extra_start = switch & (inning > reg)
        base = np.where(extra_start, SECOND_BASE_MASK, base)

        terminal = terminal | become_terminal
        # Watchdog: force-terminate absurd games.
        watchdog = active & (n_pa > MAX_PA_PER_GAME_WATCHDOG - 1)
        terminal = terminal | watchdog

    nonterminated = int((~terminal).sum())
    home_win = home_score > away_score
    return GameSimResult(
        game_id=game_id, n_sims=n_sims,
        away_runs=away_score.copy(), home_runs=home_score.copy(),
        innings=inning.copy(), pa_counts=n_pa.copy(), home_win=home_win,
        nonterminated=nonterminated, illegal_states=illegal,
        first_five_away_runs=first_five_away.copy(),
        first_five_home_runs=first_five_home.copy(),
    )


__all__ = [
    "MONTE_CARLO_CONTRACT_NAME",
    "MONTE_CARLO_SCHEMA_VERSION",
    "PARTICIPANT_MODE",
    "DEFAULT_REGULATION",
    "MonteCarloError",
    "SimulatedPAStateBatch",
    "PAProbabilityProvider",
    "FastD3Fold",
    "FastTransitionSampler",
    "GameContribs",
    "GameSimResult",
    "build_game_contribs",
    "simulate_game",
]
