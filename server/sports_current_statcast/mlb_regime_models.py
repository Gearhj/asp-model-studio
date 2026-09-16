"""Frozen, bounded corrections to accepted V18 OOF probability forecasts.

This module does not load data, update the global model, or change its target.
All fit methods receive only caller-validated chronological training observations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import expit, logsumexp, softmax

from server.sports_modeling.metrics import validate_probability_matrix

PENALTY = .01
MAX_CLASS_ADJUSTMENT = .03
RESIDUAL_PSEUDO_COUNT = 10000.


def _bounded_correction(base: np.ndarray, delta: np.ndarray, *, mixing: float = 1.) -> tuple:
    """Return deployed probabilities and their active radial-cap coordinates."""
    p = validate_probability_matrix(base)
    d = np.asarray(delta, dtype=float).copy()
    if d.shape != p.shape or not np.isfinite(d).all():
        raise ValueError('Invalid probability correction')
    if not np.isfinite(mixing) or not 0 <= mixing <= 1:
        raise ValueError('Probability mixing must be between zero and one')
    d -= d.mean(axis=1, keepdims=True)
    d *= mixing
    largest = np.argmax(np.abs(d), axis=1)
    maximum = np.abs(d[np.arange(len(d)), largest])
    cap = MAX_CLASS_ADJUSTMENT / np.maximum(maximum, 1e-30)
    negative = d < 0
    safe = np.where(negative, (p - 1e-12) / np.maximum(-d, 1e-30), np.inf)
    floor_coordinate = np.argmin(safe, axis=1)
    floor = np.maximum(0., safe[np.arange(len(d)), floor_coordinate])
    scale = np.minimum(1., np.minimum(cap, floor))
    coordinate = np.where(floor < cap, floor_coordinate, largest)
    q = p + scale[:, None] * d
    return validate_probability_matrix(q), d, scale, coordinate


def simplex_correction(base: np.ndarray, delta: np.ndarray, *, mixing: float = 1.) -> np.ndarray:
    """Scale a zero-sum correction, retaining the simplex without renormalization."""
    return _bounded_correction(base, delta, mixing=mixing)[0]


def bounded_log_loss_gradient(
    base: np.ndarray, delta: np.ndarray, y: np.ndarray, *, mixing: float = 1.
) -> tuple[float, np.ndarray]:
    """Mean deployed log loss and per-row derivative with respect to raw delta.

    Away from cap ties, the active bound is s=a/abs(d_j), or its positivity-floor
    counterpart, so ds/dd_j=-s/d_j. Centering and fixed mixing are included in
    the returned derivative. At an exact tie we use one valid one-sided branch;
    at zero scale the deployed distribution is locally the unchanged baseline.
    """
    q, d, scale, coordinate = _bounded_correction(base, delta, mixing=mixing)
    rows = np.arange(len(q))
    target = q[rows, y]
    clipped = np.clip(target, 1e-15, 1.)
    slope = np.where(target > 1e-15, -1. / clipped, 0.)
    gradient = np.zeros_like(q)
    gradient[rows, y] = slope * scale
    active = (scale < 1.) & (scale > 0.)
    chosen = coordinate[active]
    active_rows = rows[active]
    gradient[active_rows, chosen] += (
        slope[active] * d[active_rows, y[active]] * -scale[active]
        / d[active_rows, chosen]
    )
    gradient = mixing * (gradient - gradient.mean(axis=1, keepdims=True))
    return float(-np.log(clipped).mean()), gradient


class MembershipBasis:
    """Named, training-centered soft memberships and predeclared products."""
    def fit(self, domains: dict[str, dict], frame: Any) -> 'MembershipBasis':
        self.names = sorted(domains)
        self.centers = {}
        self.widths = {}
        for name in self.names:
            m, s = domains[name]['membership'], domains[name]['support']
            self.widths[name] = m.shape[1]
            self.centers[name] = np.average(m, axis=0, weights=s) if s.sum() else np.zeros(m.shape[1])
        z = self._raw(domains, frame, interactions=True)
        self.scale = np.maximum(np.sqrt(np.mean(z*z, axis=0)), .05)
        self.base_width = sum(self.widths.values())
        return self

    def _raw(self, domains: dict[str, dict], frame: Any, *, interactions: bool) -> np.ndarray:
        chunks = [(domains[name]['membership'] - self.centers[name]) * domains[name]['support'][:, None]
                  for name in self.names]
        z = np.column_stack(chunks)
        if interactions and 'BATTER' in domains and 'PITCHER' in domains:
            a = (domains['BATTER']['membership'] - self.centers['BATTER']) * domains['BATTER']['support'][:, None]
            b = (domains['PITCHER']['membership'] - self.centers['PITCHER']) * domains['PITCHER']['support'][:, None]
            matchup = np.asarray(frame['matchup_platoon_advantage'], dtype=float)
            if not np.isfinite(matchup).all() or not np.isin(matchup, [0, 1]).all():
                raise ValueError('Governed platoon Boolean required')
            z = np.column_stack([z, (a[:, :, None]*b[:, None, :]).reshape(len(z), -1),
                                 a * (matchup[:, None] - .5), b * (matchup[:, None] - .5)])
        return z

    def transform(self, domains: dict[str, dict], frame: Any, *, interactions: bool = False) -> np.ndarray:
        if sorted(domains) != self.names or any(domains[n]['membership'].shape[1] != self.widths[n] for n in self.names):
            raise ValueError('Frozen cluster-coordinate schema mismatch')
        z = self._raw(domains, frame, interactions=interactions)
        return z / self.scale[:z.shape[1]]


@dataclass
class OffsetCorrection:
    coefficients: np.ndarray
    fit_receipt: dict

    @classmethod
    def fit(cls, z: np.ndarray, y: np.ndarray, base: np.ndarray, *, penalty: float = PENALTY) -> 'OffsetCorrection':
        p = validate_probability_matrix(base)
        offset, n, width = np.log(np.clip(p, 1e-15, 1)), len(y), z.shape[1]
        def objective(flat):
            beta = flat.reshape(width, 8)
            logits = offset + z @ beta
            q = softmax(logits, axis=1)
            q[np.all(z == 0, axis=1)] = p[np.all(z == 0, axis=1)]
            loss, correction_gradient = bounded_log_loss_gradient(p, q - p, y, mixing=.5)
            value = loss + .5*penalty*np.sum(beta*beta)
            logit_gradient = q * (correction_gradient - np.sum(correction_gradient*q, axis=1, keepdims=True))
            gradient = z.T @ logit_gradient / n + penalty*beta
            return value, gradient.ravel()
        fitted = minimize(objective, np.zeros(width*8), jac=True, method='L-BFGS-B',
                          options={'maxiter': 250, 'ftol': 1e-11, 'gtol': 1e-7})
        if not fitted.success:
            raise RuntimeError(f'Offset fit did not converge: {fitted.message}')
        return cls(fitted.x.reshape(width, 8), {'rows': n, 'covariates': width, 'l2Penalty': penalty,
                    'iterations': int(fitted.nit), 'objective': float(fitted.fun), 'converged': True,
                    'objectiveDistribution': 'DEPLOYED_HALF_MIX_WITH_RADIAL_CLASS_CAP_AND_SIMPLEX_FLOOR'})

    def predict(self, z: np.ndarray, base: np.ndarray) -> np.ndarray:
        q = softmax(np.log(np.clip(base, 1e-15, 1)) + z @ self.coefficients, axis=1)
        q[np.all(z == 0, axis=1)] = base[np.all(z == 0, axis=1)]
        return simplex_correction(base, q - base, mixing=.5)


def _effective_n(weights: np.ndarray) -> float:
    return float(weights.sum()**2 / np.maximum(np.square(weights).sum(), 1e-30))


def discover_failures(frame: Any, y: np.ndarray, base: np.ndarray, domains: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Use only discovery fold 1/2; outcomes never define runtime membership."""
    if not set(frame.foldNumber.unique()).issubset({1, 2}):
        raise ValueError('Failure discovery only accepts folds 1 and 2')
    residual = np.eye(8)[y] - base
    seasons = np.asarray(frame.season)
    records, qualified = [], []
    for domain, data in domains.items():
        for k in range(data['membership'].shape[1]):
            w = data['membership'][:, k] * data['support']
            seasonal, folds = [], []
            for season in sorted(set(seasons)):
                take = seasons == season
                weighted = w[take]
                seasonal.append({'season': int(season), 'effectivePAs': _effective_n(weighted),
                    'games': int(frame.loc[take & (w >= .1), 'canonicalGameId'].nunique()),
                    'residual': (weighted @ residual[take] / max(weighted.sum(), 1e-30)).tolist()})
            for fold in (1, 2):
                take = np.asarray(frame.foldNumber) == fold
                folds.append({'fold': fold, 'residual': (w[take] @ residual[take] / max(w[take].sum(), 1e-30)).tolist()})
            enough = len(seasonal) >= 2 and all(s['effectivePAs'] >= 1000 and s['games'] >= 100 for s in seasonal)
            for c in range(8):
                values = [s['residual'][c] for s in seasonal]
                signs = [np.sign(v) for v in values + [s['residual'][c] for s in folds]]
                eligible = enough and min(abs(v) for v in values) >= .003 and len(set(signs)) == 1 and signs[0] != 0
                record = {'clusterId': f'{domain}_{k}', 'domain': domain, 'component': k, 'classIndex': c,
                    'seasonalEvidence': seasonal, 'foldEvidence': folds, 'eligible': bool(eligible),
                    'weakestSeasonResidual': float(min(abs(v) for v in values)), 'effectivePAs': _effective_n(w),
                    'reason': 'PERSISTENT_PRE_EVENT_CLASS_BIAS' if eligible else 'INSUFFICIENT_SUPPORT_OR_NONPERSISTENT_BIAS'}
                records.append(record)
                if eligible:
                    qualified.append(record)
    chosen, seen = [], set()
    for record in sorted(qualified, key=lambda r: (-r['weakestSeasonResidual'], r['clusterId'], r['classIndex'])):
        if record['clusterId'] not in seen and len(chosen) < 4:
            seen.add(record['clusterId'])
            chosen.append(record)
    return records, chosen


@dataclass
class ResidualExperts:
    experts: list[dict]

    @classmethod
    def fit(cls, eligible: list[dict], domains: dict[str, dict], y: np.ndarray, base: np.ndarray) -> 'ResidualExperts':
        residual, experts = np.eye(8)[y] - base, []
        for rule in eligible:
            data = domains[rule['domain']]
            weights = data['membership'][:, rule['component']] * data['support']
            correction = weights @ residual / (weights.sum() + RESIDUAL_PSEUDO_COUNT)
            correction -= correction.mean()
            correction *= min(1., MAX_CLASS_ADJUSTMENT / max(np.abs(correction).max(), 1e-30))
            experts.append({**rule, 'correction': correction, 'fittingEffectivePAs': _effective_n(weights),
                            'weightSum': float(weights.sum()), 'shrinkage': float(weights.sum()/(weights.sum()+RESIDUAL_PSEUDO_COUNT))})
        return cls(experts)

    def weights(self, domains: dict[str, dict]) -> np.ndarray:
        n = len(next(iter(domains.values()))['support'])
        if not self.experts:
            return np.zeros((n, 0))
        return np.column_stack([domains[e['domain']]['membership'][:, e['component']] * domains[e['domain']]['support']
                                for e in self.experts])

    def branches(self, base: np.ndarray) -> np.ndarray:
        if not self.experts:
            return np.zeros((len(base), 0, 8))
        return np.stack([simplex_correction(base, np.broadcast_to(e['correction'], base.shape)) for e in self.experts], axis=1)

    def predict(self, domains: dict[str, dict], base: np.ndarray) -> np.ndarray:
        weights = self.weights(domains)
        if not self.experts:
            return base.copy()
        weights /= np.maximum(1., weights.sum(axis=1))[:, None]
        return simplex_correction(base, np.sum(weights[:, :, None]*(self.branches(base)-base[:, None, :]), axis=1), mixing=.5)


@dataclass
class SoftGate:
    """L2 shrinks coefficients to a support-proportional neutral gate, not zero mass."""
    coefficients: np.ndarray
    fit_receipt: dict

    @classmethod
    def fit(cls, z: np.ndarray, support: np.ndarray, experts: np.ndarray, y: np.ndarray, base: np.ndarray) -> 'SoftGate':
        x = np.column_stack([np.ones(len(z)), z])
        k = support.shape[1]
        if k == 0:
            return cls(np.zeros((x.shape[1], 0)), {'status': 'NO_QUALIFIED_EXPERTS', 'rows': len(y)})
        selected_delta = experts[np.arange(len(y)), :, y] - base[np.arange(len(y)), y, None]
        ptrue = base[np.arange(len(y)), y]
        def objective(flat):
            beta = flat.reshape(x.shape[1], k)
            logits = np.where(support > 0, x @ beta + np.log(np.maximum(support, 1e-30)), -np.inf)
            soft = softmax(np.column_stack([np.zeros(len(y)), logits]), axis=1)[:, 1:]
            d = np.sum(soft * selected_delta, axis=1)
            qtrue = np.clip(ptrue + .25*d, 1e-15, 1)
            loss = -np.log(qtrue).mean() + .5*PENALTY*np.square(beta).sum()
            logit_grad = -.25*soft*(selected_delta-d[:, None])/qtrue[:, None]
            return loss, (x.T @ logit_grad / len(y) + PENALTY*beta).ravel()
        fitted = minimize(objective, np.zeros(x.shape[1]*k), jac=True, method='L-BFGS-B',
                          options={'maxiter': 150, 'ftol': 1e-11, 'gtol': 1e-7})
        if not fitted.success:
            raise RuntimeError(f'Soft gate failed convergence: {fitted.message}')
        return cls(fitted.x.reshape(x.shape[1], k), {'status': 'FITTED', 'rows': len(y), 'iterations': int(fitted.nit),
                    'regularizationTarget': 'SUPPORT_PROPORTIONAL_NEUTRAL_GATE_WITH_GLOBAL_ANCHOR'})

    def predict(self, z: np.ndarray, support: np.ndarray, experts: np.ndarray, base: np.ndarray) -> np.ndarray:
        if support.shape[1] == 0:
            return base.copy()
        x = np.column_stack([np.ones(len(z)), z])
        logits = np.where(support > 0, x @ self.coefficients + np.log(np.maximum(support, 1e-30)), -np.inf)
        weights = softmax(np.column_stack([np.zeros(len(z)), logits]), axis=1)[:, 1:] * .25
        weights = np.where(support > 0, weights, 0.)
        return simplex_correction(base, np.sum(weights[:, :, None]*(experts-base[:, None, :]), axis=1))


@dataclass
class ConvexEnsemble:
    weights: np.ndarray
    fit_receipt: dict

    @classmethod
    def fit(cls, branches: np.ndarray, y: np.ndarray) -> 'ConvexEnsemble':
        # Columns: V18, genuinely different RF, qualified residual system.
        if branches.shape != (len(y), 3, 8):
            raise ValueError('Ensemble requires aligned V18, RF and residual probability branches')
        for branch in range(3):
            validate_probability_matrix(branches[:, branch])
        def objective(weights):
            mixed = np.einsum('nmc,m->nc', branches, weights)
            loss, correction_gradient = bounded_log_loss_gradient(branches[:, 0], mixed-branches[:, 0], y)
            prior = np.array([1., 0., 0.])
            gradient = np.einsum('nc,nmc->m', correction_gradient, branches) / len(y)
            return loss + .5*PENALTY*np.square(weights-prior).sum(), gradient + PENALTY*(weights-prior)
        fitted = minimize(objective, [1., 0., 0.], jac=True, method='SLSQP', bounds=[(.5, 1), (0, .5), (0, .5)],
                          constraints=[{'type': 'eq', 'fun': lambda w: w.sum()-1, 'jac': lambda w: np.ones(3)}],
                          options={'maxiter': 150, 'ftol': 1e-11})
        if not fitted.success:
            raise RuntimeError(f'Ensemble fit failed convergence: {fitted.message}')
        return cls(fitted.x, {'rows': len(y), 'iterations': int(fitted.nit), 'converged': True,
                    'objectiveDistribution': 'DEPLOYED_CAPPED_CONVEX_ENSEMBLE'})

    def predict(self, branches: np.ndarray) -> np.ndarray:
        mixed = np.einsum('nmc,m->nc', branches, self.weights)
        return simplex_correction(branches[:, 0], mixed-branches[:, 0])


def fit_temperature(y: np.ndarray, probabilities: np.ndarray) -> tuple[float, dict]:
    logs = np.log(np.clip(probabilities, 1e-15, 1))
    def loss(t):
        logits = logs / t
        return float(np.mean(logsumexp(logits, axis=1) - logits[np.arange(len(y)), y]))
    result = minimize_scalar(loss, bounds=(.75, 1.5), method='bounded', options={'xatol': 1e-7})
    if not result.success:
        raise RuntimeError('Chronological temperature fit failed')
    return float(result.x), {'rows': len(y), 'objective': float(result.fun), 'bounds': [.75, 1.5]}


def temperature_transform(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    return validate_probability_matrix(softmax(np.log(np.clip(probabilities, 1e-15, 1))/temperature, axis=1))
