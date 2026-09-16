"""V19 research inference assets. No sources, deployment or publication side effects.

History counts are strictly prior-date; same-day games never update another
game's inputs. Absence from the bounded archive is not called career no-history.
"""
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import adjusted_rand_score

from server.sports_modeling.metrics import PA_CLASS_ORDER

K = len(PA_CLASS_ORDER)
DOMAINS = {'batter': 'batterCanonicalPlayerId', 'pitcher': 'pitcherCanonicalPlayerId',
           'team_offense': 'battingTeamId', 'team_defense': 'fieldingTeamId'}


def predict_estimator(estimator, values):
    from sklearn.ensemble import ExtraTreesClassifier
    from .stage3_model_laboratory import _aligned_probabilities
    if isinstance(estimator, ExtraTreesClassifier):
        # sklearn's parallel accumulation may sum trees in a different order.
        # Training is parallel; inference uses permanent tree order for bitwise reload.
        x = np.asarray(values, dtype=np.float32)
        result = np.zeros((len(x), K))
        for tree in estimator.estimators_:
            result += tree.predict_proba(x, check_input=False)
        return result / len(estimator.estimators_)
    return _aligned_probabilities(estimator, values)


def hand_groups(frame, domain):
    if domain == 'batter':
        left = frame['matchup_batter_bats_left'].to_numpy()
        switch = frame['matchup_batter_bats_switch'].to_numpy()
        unknown = frame['matchup_batter_hand_missing'].to_numpy()
        return np.where(unknown == 1, 3, np.where(switch == 1, 2, np.where(left == 1, 1, 0)))
    if domain == 'pitcher':
        return np.where(frame['matchup_pitcher_hand_missing'].to_numpy() == 1, 2,
                        np.where(frame['matchup_pitcher_throws_left'].to_numpy() == 1, 1, 0))
    return np.zeros(len(frame), dtype=int)


def prior_counts(history, query, entity_column):
    """Outcome data may exist in history only; current/future dates cannot contribute."""
    if history.canonicalPaId.duplicated().any():
        raise ValueError('Duplicate history observation identity')
    current = np.zeros((len(query), K), dtype=np.float64)
    previous = np.zeros((len(query), 3, K), dtype=np.float64)
    qdates = pd.to_datetime(query.game_date).to_numpy(dtype='datetime64[D]').astype('int64')
    qyears = pd.to_datetime(query.game_date).dt.year.to_numpy()
    hist = history[[entity_column, 'game_date', 'observedClassIndex']].copy()
    hist['_date'] = pd.to_datetime(hist.game_date).to_numpy(dtype='datetime64[D]').astype('int64')
    hist['_year'] = pd.to_datetime(hist.game_date).dt.year
    lookup = dict(tuple(hist.groupby(entity_column, sort=False)))
    for entity, positions in query.groupby(entity_column, sort=False, dropna=False).indices.items():
        source = lookup.get(entity)
        if source is None:
            continue
        source = source.sort_values('_date', kind='stable')
        dates = source._date.to_numpy()
        counts = np.eye(K)[source.observedClassIndex.to_numpy(dtype=int)]
        cumulative = np.vstack([np.zeros((1, K)), np.cumsum(counts, axis=0)])
        years = source._year.to_numpy()
        positions = np.asarray(positions)
        for year in np.unique(qyears[positions]):
            take = positions[qyears[positions] == year]
            start = int(np.datetime64(f'{year}-01-01', 'D').astype('int64'))
            first = np.searchsorted(dates, start, side='left')
            ends = np.searchsorted(dates, qdates[take], side='left')
            current[take] = cumulative[ends] - cumulative[first]
            for lag in range(1, 4):
                previous[take, lag-1] = counts[years == year-lag].sum(axis=0)
    return current, previous


@dataclass
class SemanticPriors:
    parameters: dict = field(default_factory=dict)
    fitted_end: str = ''
    feature_names: list = field(default_factory=list)
    uncertainty_names: list = field(default_factory=list)

    def fit(self, history):
        self.fitted_end = str(history.game_date.max())
        # Fixed identity sample only bounds hyperparameter computation, not global fits.
        hashes = pd.util.hash_pandas_object(history.canonicalPaId, index=False).to_numpy()
        sample = history.iloc[np.argsort(hashes, kind='stable')[:60000]].reset_index(drop=True)
        y = sample.observedClassIndex.to_numpy(dtype=int)
        multiseason = pd.to_datetime(history.game_date).dt.year.nunique() > 1
        for domain, entity in DOMAINS.items():
            groups = hand_groups(history, domain)
            league = np.bincount(history.observedClassIndex, minlength=K).astype(float) + .5
            league /= league.sum()
            populations = {}
            for group in range(4):
                labels = history.loc[groups == group, 'observedClassIndex'].to_numpy(dtype=int)
                # Hierarchical league shrinkage, not a median substitute for a feature.
                counts = np.bincount(labels, minlength=K) + K * league
                populations[group] = counts / counts.sum()
            base = np.vstack([populations[int(g)] for g in hand_groups(sample, domain)])
            current, previous = prior_counts(history, sample, entity)
            def loss(theta):
                alpha = np.exp(theta[0])
                decay = theta[1] if multiseason else 0.
                carry = np.einsum('nlk,l->nk', previous, decay ** np.arange(1, 4))
                counts = current + carry
                p = (counts + alpha * base) / (counts.sum(axis=1, keepdims=True) + alpha)
                return float(-np.log(np.maximum(p[np.arange(len(y)), y], 1e-15)).mean())
            result = minimize(loss, np.array([np.log(100.), .5 if multiseason else 0.]),
                              bounds=[(np.log(2.), np.log(10000.)), (0., 1.) if multiseason else (0., 0.)],
                              method='L-BFGS-B', options={'maxiter': 50, 'ftol': 1e-10})
            if not result.success:
                raise RuntimeError(f'Prior fit failed {domain}: {result.message}')
            self.parameters[domain] = {'alpha': float(np.exp(result.x[0])), 'decay': float(result.x[1]),
                'decayStatus': 'TRAINING_PREFIX_EB_WITH_PRE_DATE_ENTITY_COUNTS' if multiseason else 'UNIDENTIFIABLE_SINGLE_SEASON_NO_CARRYOVER',
                'populations': populations, 'objective': float(result.fun), 'sampleRows': len(sample),
                'trainingRows': len(history), 'optimizerIterations': int(result.nit)}
        self.feature_names = [name for d in DOMAINS for name in
            [*[f'v19_{d}_p_{c}' for c in PA_CLASS_ORDER], f'v19_{d}_log_exposure',
             f'v19_{d}_archive_no_observation', f'v19_{d}_low_exposure']]
        self.uncertainty_names = [f'v19_{d}_posterior_dispersion_only' for d in DOMAINS]
        return self

    def transform(self, history, query):
        columns, uncertainty = {}, {}
        for domain, entity in DOMAINS.items():
            params = self.parameters[domain]
            current, previous = prior_counts(history, query, entity)
            carry = np.einsum('nlk,l->nk', previous, params['decay'] ** np.arange(1, 4))
            counts = current + carry
            n = counts.sum(axis=1)
            base = np.vstack([params['populations'][int(g)] for g in hand_groups(query, domain)])
            mean = (counts + params['alpha'] * base) / (n[:, None] + params['alpha'])
            for index, target in enumerate(PA_CLASS_ORDER):
                columns[f'v19_{domain}_p_{target}'] = mean[:, index]
            columns[f'v19_{domain}_log_exposure'] = np.log1p(n)
            columns[f'v19_{domain}_archive_no_observation'] = (current.sum(axis=1) + previous.sum(axis=(1, 2)) == 0).astype(float)
            columns[f'v19_{domain}_low_exposure'] = (n < params['alpha']).astype(float)
            uncertainty[f'v19_{domain}_posterior_dispersion_only'] = np.sum(mean * (1-mean), axis=1) / (n + params['alpha'] + 1)
        return pd.DataFrame(columns, index=query.index), pd.DataFrame(uncertainty, index=query.index)


CLUSTER_COORDINATES = {
    'BATTER': tuple('v19_batter_p_'+c for c in PA_CLASS_ORDER[:-1]),
    'STARTER_PROPENSITY': tuple('v19_pitcher_p_'+c for c in PA_CLASS_ORDER[:-1]),
    'RELIEVER_PROPENSITY': tuple('v19_pitcher_p_'+c for c in PA_CLASS_ORDER[:-1]),
    'TEAM_OFFENSE': tuple('v19_team_offense_p_'+c for c in PA_CLASS_ORDER[:-1]),
    'TEAM_DEFENSE': tuple('v19_team_defense_p_'+c for c in PA_CLASS_ORDER[:-1]),
    'REST_TRAVEL': ('batting_travel_distance_miles', 'fielding_travel_distance_miles',
                    'batting_days_since_previous_game', 'fielding_days_since_previous_game',
                    'batting_games_last_7_days', 'fielding_games_last_7_days'),
    'MATCHUP': ('matchup_batter_bats_left', 'matchup_batter_bats_switch',
                'matchup_pitcher_throws_left', 'matchup_platoon_advantage', 'month_sin', 'month_cos'),
}


@dataclass
class FoldClusters:
    models: dict = field(default_factory=dict)
    reports: list = field(default_factory=list)
    fitted_end: str = ''

    @staticmethod
    def coordinates(frame, domain):
        x = frame[list(CLUSTER_COORDINATES[domain])].to_numpy(dtype=float)
        supported = np.isfinite(x).all(axis=1)
        if domain.endswith('PROPENSITY'):
            role = pd.to_numeric(frame.pitcher_gs_per_g, errors='coerce').to_numpy()
            supported &= np.isfinite(role) & ((role >= .5) if domain.startswith('STARTER') else (role < .5))
        return x, supported

    def fit(self, frame, seed):
        self.fitted_end = str(frame.game_date.max())
        hashes = pd.util.hash_pandas_object(frame.canonicalPaId, index=False).to_numpy()
        for domain in CLUSTER_COORDINATES:
            values, supported = self.coordinates(frame, domain)
            pos = np.flatnonzero(supported)
            if len(pos) < 1000:
                self.reports.append({'domain': domain, 'status': 'INSUFFICIENT_SUPPORTED_COORDINATES', 'rows': len(pos)})
                continue
            pos = pos[np.argsort(hashes[pos], kind='stable')[:30000]]
            scaler = StandardScaler().fit(values[pos])
            estimator = KMeans(n_clusters=3, random_state=seed, n_init=3).fit(scaler.transform(values[pos]))
            order = np.array(sorted(range(3), key=lambda k: tuple(estimator.cluster_centers_[k])))
            self.models[domain] = (scaler, estimator, order)
            dates = frame.game_date.astype(str).to_numpy()
            unique = sorted(np.unique(dates))
            early = pos[dates[pos] <= unique[max(0, len(unique)*2//3-1)]]
            later = pos[dates[pos] > unique[max(0, len(unique)*2//3-1)]]
            ari = None
            if len(early) >= 1000 and len(later) >= 500:
                subscale = StandardScaler().fit(values[early])
                submodel = KMeans(n_clusters=3, random_state=seed, n_init=3).fit(subscale.transform(values[early]))
                ari = float(adjusted_rand_score(estimator.predict(scaler.transform(values[later])),
                                               submodel.predict(subscale.transform(values[later]))))
            labels = estimator.predict(scaler.transform(values[pos]))
            self.reports.append({'domain': domain, 'status': 'FITTED_TRAINING_ONLY', 'fitRows': len(pos),
                'featureOrder': list(CLUSTER_COORDINATES[domain]), 'fittedEnd': self.fitted_end,
                'subprefixStabilityARI': ari, 'clusterCounts': np.bincount(labels, minlength=3).tolist(),
                'centersOriginalUnits': scaler.inverse_transform(estimator.cluster_centers_[order]).tolist(),
                'architectureSelectionOnValidation': False})
        return self

    def transform(self, frame):
        result, labels = {}, {}
        for domain in CLUSTER_COORDINATES:
            x, supported = self.coordinates(frame, domain)
            label = np.full(len(frame), -1)
            memberships = np.zeros((len(frame), 3))
            if domain in self.models and supported.any():
                scaler, estimator, order = self.models[domain]
                distance = estimator.transform(scaler.transform(x[supported]))[:, order]
                logits = -.5 * distance**2
                logits -= logits.max(axis=1, keepdims=True)
                weight = np.exp(logits)
                weight /= weight.sum(axis=1, keepdims=True)
                memberships[supported] = weight
                label[supported] = weight.argmax(axis=1)
            for k in range(3):
                result[f'cluster_{domain}_{k}'] = memberships[:, k]
            result[f'cluster_{domain}_unavailable'] = (label < 0).astype(float)
            labels[f'cluster_{domain}'] = label
        return pd.DataFrame(result, index=frame.index), pd.DataFrame(labels, index=frame.index)


@dataclass
class CandidatePipeline:
    frozen_preprocessor: Any
    semantic: SemanticPriors
    clusters: FoldClusters
    estimator: Any
    variant: str
    ordered_features: list
    regime_order: list
    target_order: tuple = tuple(PA_CLASS_ORDER)

    def matrix(self, rows, history):
        from .mlb_v19_evaluation import regime_masks
        if history.empty or any(name not in history or history[name].isna().any() for name in DOMAINS.values()):
            raise ValueError('SOURCE_FAILURE_MISSING_HISTORY_OR_ENTITY_IDENTITY')
        if pd.to_datetime(rows.game_date).max() > pd.to_datetime(history.game_date).max() + pd.Timedelta(days=1):
            raise ValueError('SOURCE_GAP_HISTORY_NOT_CURRENT_THROUGH_PRIOR_DATE')
        treated = self.frozen_preprocessor.transform_frame(rows)
        base = self.frozen_preprocessor.encoder.transform(treated)
        semantic, uncertainty = self.semantic.transform(history, rows)
        # uncertainty is intentionally excluded, never silently a score-mean flag.
        del uncertainty
        parts = [base, semantic[self.semantic.feature_names].to_numpy()]
        if self.variant in ('REGIME_HGB', 'REGIME_CLUSTER_HGB'):
            masks, _ = regime_masks(rows)
            parts.append(np.column_stack([masks[name] for name in self.regime_order]).astype(float))
        if self.variant == 'REGIME_CLUSTER_HGB':
            combined = pd.concat([rows.reset_index(drop=True), semantic.reset_index(drop=True)], axis=1)
            features, _ = self.clusters.transform(combined)
            parts.append(features.to_numpy())
        x = np.column_stack(parts)
        if (x.shape[1] != len(self.ordered_features) or np.isinf(x).any()
                or not np.isfinite(semantic.to_numpy()).all()):
            raise ValueError('Ordered feature contract or semantic coverage differs')
        return x

    def predict_proba(self, rows, history, *, uncertainty_only_override=None):
        # Override exists solely to verify the computational separation contract.
        del uncertainty_only_override
        return predict_estimator(self.estimator, self.matrix(rows, history))
