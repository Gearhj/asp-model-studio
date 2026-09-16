"""Predeclared 2023-only MLB archetypes; no target-driven cluster selection.

Two historical prefixes choose the architecture using assignments on a later
2023 stability segment.  Only the winning architecture is then fitted on all
2023 observations.  Targets, player/team identifiers and realized PA states
are never clustering coordinates.  Missing domains receive no expert weight.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
import warnings

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import adjusted_rand_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import RobustScaler, StandardScaler
from threadpoolctl import threadpool_limits


SEED = 20260910
MAX_FIT_ROWS = 30000
MIN_PREFIX_ROWS = 1000
MIN_CLUSTER_MASS = 0.05
TRAIN_START = '2023-03-30'
TRAIN_END = '2023-10-01'
METHODS = ('PCA_DIAGONAL_GMM', 'ROBUST_KMEANS')
DOMAIN_FEATURES: dict[str, tuple[str, ...]] = {
    'BATTER': (
        'batter_so_per_pa__prior_v1__posterior_mean',
        'batter_bb_hbp_per_pa__prior_v1__posterior_mean',
        'batter_hr_per_pa__prior_v1__posterior_mean',
        'batter_slg', 'batter_last100_whiff_rate',
        'batter_so_per_pa__prior_v1__posterior_reliability',
        'batter_so_per_pa__prior_v1__posterior_std',
    ),
    'PITCHER': (
        'pitcher_so_per_bfp__prior_v1__posterior_mean',
        'pitcher_bb_per_bfp__prior_v1__posterior_mean',
        'pitcher_hr_per_bfp__prior_v1__posterior_mean',
        'pitcher_last250_fastball_usage', 'pitcher_last250_breaking_usage',
        'pitcher_last250_offspeed_usage', 'pitcher_last250_avg_fastball_velocity',
        'pitcher_gs_per_g', 'pitcher_so_per_bfp__prior_v1__posterior_reliability',
        'pitcher_so_per_bfp__prior_v1__posterior_std',
    ),
    'TEAM_REST_TRAVEL': (
        'batting_travel_distance_miles', 'fielding_travel_distance_miles',
        'batting_days_since_previous_game', 'fielding_days_since_previous_game',
        'batting_consecutive_game_days', 'fielding_consecutive_game_days',
        'batting_games_last_7_days', 'fielding_games_last_7_days',
    ),
    'MATCHUP_CONTEXT': (
        'matchup_batter_bats_left', 'matchup_batter_bats_switch',
        'matchup_pitcher_throws_left', 'matchup_platoon_advantage',
        'month_sin', 'month_cos', 'is_day_game', 'is_series_opener',
    ),
}


def _coordinates(frame: pd.DataFrame, features: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    """No imputation: an unavailable or nonfinite coordinate disables the domain."""
    values = np.full((len(frame), len(features)), np.nan, dtype=np.float64)
    for index, feature in enumerate(features):
        if feature in frame:
            values[:, index] = pd.to_numeric(frame[feature], errors='coerce').to_numpy(dtype=np.float64, na_value=np.nan)
    return values, np.isfinite(values).all(axis=1)


def _sample_positions(frame: pd.DataFrame, mask: np.ndarray) -> np.ndarray:
    positions = np.flatnonzero(mask)
    if not len(positions):
        return positions
    # A fixed key hash makes subsampling independent of row order and outcomes.
    keys = pd.util.hash_pandas_object(frame.iloc[positions]['canonicalPaId'].astype(str), index=False).to_numpy(dtype=np.uint64)
    order = np.argsort(keys, kind='stable')
    return positions[order[:MAX_FIT_ROWS]]


@dataclass
class DomainCluster:
    domain: str
    features: tuple[str, ...]
    method: str
    k: int
    scaler: Any
    pca: Any
    estimator: Any
    order: np.ndarray
    support_distance_p99: float
    soft_distance_temperature: float

    def _embedded(self, values: np.ndarray) -> np.ndarray:
        transformed = self.scaler.transform(values)
        return self.pca.transform(transformed) if self.pca is not None else transformed

    def _memberships_distances(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        embedded = self._embedded(values)
        if self.method == 'PCA_DIAGONAL_GMM':
            membership = self.estimator.predict_proba(embedded)
            delta = embedded[:, None, :] - self.estimator.means_[None, :, :]
            squared = (np.square(delta) / self.estimator.covariances_[None, :, :]).sum(axis=2)
        else:
            squared = np.square(self.estimator.transform(embedded))
            logits = -squared / (2.0 * self.soft_distance_temperature)
            logits -= logits.max(axis=1, keepdims=True)
            membership = np.exp(logits)
            membership /= membership.sum(axis=1, keepdims=True)
        return membership[:, self.order], np.sqrt(np.maximum(0.0, squared.min(axis=1)))

    def transform(self, frame: pd.DataFrame) -> dict[str, np.ndarray]:
        values, finite = _coordinates(frame, self.features)
        membership = np.zeros((len(frame), self.k), dtype=np.float64)
        support = np.zeros(len(frame), dtype=np.float64)
        labels = np.full(len(frame), -1, dtype=np.int64)
        if finite.any():
            observed, distance = self._memberships_distances(values[finite])
            if self.support_distance_p99 > 0:
                local_support = np.clip(2.0 - distance / self.support_distance_p99, 0.0, 1.0)
            else:
                local_support = (distance == 0.0).astype(np.float64)
            membership[finite] = observed
            support[finite] = local_support
            labels[finite] = observed.argmax(axis=1)
        return {'membership': membership, 'support': support, 'labels': labels}


@dataclass
class ClusterSystem:
    domains: dict[str, DomainCluster | None]
    features: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(DOMAIN_FEATURES))
    fitted_cutoff: str = TRAIN_END

    def transform(self, frame: pd.DataFrame) -> dict[str, dict[str, np.ndarray]]:
        result = {}
        with threadpool_limits(limits=4):
            for domain, model in self.domains.items():
                if model is None:
                    result[domain] = {'membership': np.zeros((len(frame), 0), dtype=np.float64),
                                      'support': np.zeros(len(frame), dtype=np.float64),
                                      'labels': np.full(len(frame), -1, dtype=np.int64)}
                else:
                    result[domain] = model.transform(frame)
        return result


def _fit_domain(frame: pd.DataFrame, positions: np.ndarray, *, domain: str, method: str,
                k: int, stage: str, emit: Callable[..., None], counts: dict[str, int]) -> tuple[DomainCluster, dict]:
    features = DOMAIN_FEATURES[domain]
    values, complete = _coordinates(frame.iloc[positions], features)
    if not complete.all():
        raise ValueError('The predeclared complete-domain training mask changed')
    scaler = StandardScaler() if method == 'PCA_DIAGONAL_GMM' else RobustScaler()
    counts['scalerFitStarts'] += 1
    transformed = scaler.fit_transform(values)
    counts['scalerFitCompletions'] += 1
    pca = None
    if method == 'PCA_DIAGONAL_GMM':
        pca = PCA(n_components=0.90, svd_solver='full')
        counts['pcaFitStarts'] += 1
        transformed = pca.fit_transform(transformed)
        counts['pcaFitCompletions'] += 1
        estimator = GaussianMixture(n_components=k, covariance_type='diag', reg_covar=0.05, n_init=1,
                                    random_state=SEED, max_iter=100)
    else:
        estimator = KMeans(n_clusters=k, n_init=3, random_state=SEED, max_iter=300)
    fit_identity = {'domain': domain, 'method': method, 'k': k, 'stage': stage, 'rows': len(positions),
                    'fitStartDate': str(frame.iloc[positions].game_date.min()),
                    'fitEndDate': str(frame.iloc[positions].game_date.max())}
    counts['actualClusteringFitStarts'] += 1
    emit('fit_start', **fit_identity)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always', ConvergenceWarning)
        with threadpool_limits(limits=4):
            estimator.fit(transformed)
    counts['completedClusteringFits'] += 1
    emit('fit_completed', **fit_identity)
    converged = bool(getattr(estimator, 'converged_', True)) and not any(issubclass(w.category, ConvergenceWarning) for w in caught)
    if method == 'PCA_DIAGONAL_GMM':
        membership = estimator.predict_proba(transformed)
        delta = transformed[:, None, :] - estimator.means_[None, :, :]
        nearest_squared = (np.square(delta) / estimator.covariances_[None, :, :]).sum(axis=2).min(axis=1)
        temperature = 1.0
    else:
        squared = np.square(estimator.transform(transformed))
        nearest_squared = squared.min(axis=1)
        positive = nearest_squared[nearest_squared > 0]
        temperature = float(np.median(positive)) if len(positive) else 1.0
        logits = -squared / (2.0 * temperature)
        logits -= logits.max(axis=1, keepdims=True)
        membership = np.exp(logits)
        membership /= membership.sum(axis=1, keepdims=True)
    # Semantic means, not PCA coordinates, determine permanent low-to-high labels.
    weighted_means = membership.T @ values / membership.sum(axis=0)[:, None]
    order = np.asarray(sorted(range(k), key=lambda index: tuple(weighted_means[index]) + (index,)), dtype=np.int64)
    model = DomainCluster(domain, features, method, k, scaler, pca, estimator, order,
                          float(np.quantile(np.sqrt(np.maximum(0.0, nearest_squared)), 0.99)), temperature)
    hard = membership.argmax(axis=1)
    hard_mass = np.bincount(hard, minlength=k) / len(hard)
    soft_mass = membership.mean(axis=0)
    return model, {**fit_identity, 'converged': converged, 'embeddingDimensions': transformed.shape[1],
                   'hardMass': hard_mass[order].tolist(), 'softMass': soft_mass[order].tolist(),
                   'minimumHardMass': float(hard_mass.min()), 'minimumSoftMass': float(soft_mass.min()),
                   'samplePaIdHash': int(pd.util.hash_pandas_object(frame.iloc[positions].canonicalPaId, index=False).sum()),
                   'warnings': [str(w.message) for w in caught]}


def _aligned_agreement(first: np.ndarray, second: np.ndarray, k: int) -> float:
    counts = np.zeros((k, k), dtype=np.int64)
    np.add.at(counts, (first, second), 1)
    rows, columns = linear_sum_assignment(-counts)
    return float(counts[rows, columns].sum() / len(first))


def _profiles(model: DomainCluster, frame: pd.DataFrame) -> list[dict]:
    values, finite = _coordinates(frame, model.features)
    transformed = model.transform(frame)
    membership = transformed['membership'][finite]
    values = values[finite]
    mean, deviation = values.mean(axis=0), values.std(axis=0)
    deviation[deviation == 0] = 1.0
    profiles = []
    for index in range(model.k):
        weights = membership[:, index]
        cluster_mean = weights @ values / weights.sum()
        standardized = (cluster_mean - mean) / deviation
        defining = sorted(range(len(model.features)), key=lambda i: (-abs(standardized[i]), i))[:3]
        assigned = transformed['labels'] == index
        rows = frame.loc[assigned]
        feature_rows = [{'feature': model.features[i], 'mean': float(cluster_mean[i]),
                         'standardizedDifference': float(standardized[i]),
                         'direction': 'HIGH' if standardized[i] >= 0 else 'LOW'} for i in defining]
        profile = {'clusterId': f'{model.domain}_{index}', 'domain': model.domain, 'label': index,
                   'populationSize': int(assigned.sum()), 'softPopulationSize': float(weights.sum()),
                   'effectiveSampleSize': float(weights.sum() ** 2 / np.square(weights).sum()),
                   'populationMass': float(assigned.mean()), 'games': int(rows.canonicalGameId.nunique()),
                   'seasons': sorted(rows.season.astype(int).unique().tolist()),
                   'featureMeans': dict(zip(model.features, cluster_mean.tolist())), 'definingFeatures': feature_rows,
                   'interpretation': '; '.join(f"{item['direction'].lower()} {item['feature']}" for item in feature_rows),
                   'supportDistanceP99': model.support_distance_p99,
                   'scopeLimitation': 'REST_TRAVEL_NOT_BULLPEN_AVAILABILITY' if model.domain == 'TEAM_REST_TRAVEL' else None}
        for role, column in (('Batters', 'batterCanonicalPlayerId'), ('Pitchers', 'pitcherCanonicalPlayerId')):
            profile[f'unique{role}'] = int(rows[column].nunique()) if column in rows else None
        profiles.append(profile)
    return profiles


def fit_clusters(train2023: pd.DataFrame, emit: Callable[..., None] | None = None) -> tuple[ClusterSystem, dict]:
    """Fit at most 36 small unsupervised models after global baseline parity."""
    emit = emit or (lambda *args, **kwargs: None)
    required = {'canonicalPaId', 'canonicalGameId', 'game_date', 'season'}
    if required - set(train2023):
        raise ValueError('Cluster training requires immutable PA/game/date/season identities')
    dates = train2023.game_date.astype(str)
    if train2023.empty or not dates.between(TRAIN_START, TRAIN_END).all() or set(train2023.season.astype(int)) != {2023}:
        raise ValueError('Only registered 2023 training may fit archetypes')
    if train2023.canonicalPaId.duplicated().any():
        raise ValueError('Cluster training PA identities are duplicated')
    counts = dict.fromkeys(['actualClusteringFitStarts', 'completedClusteringFits', 'scalerFitStarts',
                           'scalerFitCompletions', 'pcaFitStarts', 'pcaFitCompletions'], 0)
    domains, domain_metadata, all_profiles = {}, {}, []
    for domain, features in DOMAIN_FEATURES.items():
        _, finite = _coordinates(train2023, features)
        prefix_a = _sample_positions(train2023, finite & (dates <= '2023-04-30').to_numpy())
        prefix_b = _sample_positions(train2023, finite & (dates <= '2023-06-30').to_numpy())
        stability_positions = _sample_positions(train2023, finite & dates.between('2023-07-01', '2023-09-30').to_numpy())
        meta = {'features': list(features), 'completeDomainRows': int(finite.sum()),
                'missingDomainRows': int((~finite).sum()), 'missingFeatureColumns': sorted(set(features) - set(train2023)),
                'prefixARows': len(prefix_a), 'prefixBRows': len(prefix_b), 'stabilityRows': len(stability_positions),
                'candidateScores': []}
        if min(len(prefix_a), len(prefix_b), len(stability_positions)) < MIN_PREFIX_ROWS:
            domains[domain] = None
            domain_metadata[domain] = {**meta, 'status': 'UNAVAILABLE_INSUFFICIENT_COMPLETE_CHRONOLOGICAL_SUPPORT'}
            continue
        eligible = []
        for method in METHODS:
            for k in (2, 3):
                models, fits = [], []
                try:
                    for stage, positions in (('PREFIX_THROUGH_APRIL', prefix_a), ('PREFIX_THROUGH_JUNE', prefix_b)):
                        model, evidence = _fit_domain(train2023, positions, domain=domain, method=method,
                                                      k=k, stage=stage, emit=emit, counts=counts)
                        models.append(model)
                        fits.append(evidence)
                    a = models[0].transform(train2023.iloc[stability_positions])['labels']
                    b = models[1].transform(train2023.iloc[stability_positions])['labels']
                    ari = float(adjusted_rand_score(a, b))
                    minimum_mass = min(f['minimumHardMass'] for f in fits)
                    qualified = bool(all(f['converged'] for f in fits) and minimum_mass >= MIN_CLUSTER_MASS
                                     and len(np.unique(a)) == k and len(np.unique(b)) == k)
                    score = {'method': method, 'k': k, 'ari': ari, 'hungarianAgreement': _aligned_agreement(a, b, k),
                             'minimumTrainingMass': minimum_mass, 'qualified': qualified,
                             'status': 'ELIGIBLE' if qualified else 'INSUFFICIENT_MASS_CONVERGENCE_OR_DISTINCT_HOLDOUT_CLUSTERS',
                             'prefixFits': fits}
                    if qualified:
                        eligible.append(score)
                except (ValueError, np.linalg.LinAlgError) as exc:
                    score = {'method': method, 'k': k, 'qualified': False, 'status': 'FAILED_NO_RETRY',
                             'error': str(exc), 'prefixFits': fits}
                    emit('fit_failed', domain=domain, method=method, k=k, error=str(exc))
                meta['candidateScores'].append(score)
        if not eligible:
            domains[domain] = None
            domain_metadata[domain] = {**meta, 'status': 'UNAVAILABLE_NO_STABLE_SUPPORTED_ARCHITECTURE'}
            continue
        selected = sorted(eligible, key=lambda item: (-item['ari'], item['k'], METHODS.index(item['method'])))[0]
        positions = _sample_positions(train2023, finite)
        final, fit = _fit_domain(train2023, positions, domain=domain, method=selected['method'],
                                 k=selected['k'], stage='FINAL_FULL_2023', emit=emit, counts=counts)
        if not fit['converged'] or fit['minimumHardMass'] < MIN_CLUSTER_MASS:
            domains[domain] = None
            domain_metadata[domain] = {**meta, 'status': 'UNAVAILABLE_FINAL_TRAINING_MASS_OR_CONVERGENCE_FAILURE_NO_RETUNE',
                                       'selected': selected, 'finalFit': fit}
            continue
        domains[domain] = final
        profiles = _profiles(final, train2023)
        for profile in profiles:
            profile['stabilityAri'] = selected['ari']
            profile['stabilityHungarianAgreement'] = selected['hungarianAgreement']
            profile['method'] = selected['method']
        all_profiles.extend(profiles)
        domain_metadata[domain] = {**meta, 'status': 'FITTED_FROZEN_2023', 'selected': selected,
                                   'finalFit': fit, 'profiles': profiles}
    system = ClusterSystem(domains)
    metadata = {'schemaVersion': 'MLB_REGIME_CLUSTER_ARCHETYPES_V1', 'trainingStart': str(dates.min()),
                'trainingCutoff': TRAIN_END, 'trainingRows': len(train2023), 'domains': domain_metadata,
                'profiles': all_profiles, 'fitAccounting': counts, 'maximumClusteringFitStarts': 36,
                'predictiveEstimatorFits': 0, 'targetColumnsUsed': [], 'seed': SEED,
                'selectionRule': 'PRE_2024_ONLY_PREFIX_STABILITY_ARI_THEN_SMALLER_K_THEN_SOFT_GMM_TIEBREAK',
                'minimumCompleteRowsPerChronologicalSegment': MIN_PREFIX_ROWS,
                'minimumClusterTrainingHardMass': MIN_CLUSTER_MASS, 'maximumSampleRowsPerFit': MAX_FIT_ROWS,
                'supportRule': 'ONE_THROUGH_TRAIN_DISTANCE_P99_LINEAR_TO_ZERO_AT_2_TIMES_P99',
                'kmeansMembershipRule': 'SOFT_RBF_TEMPERATURE_EQUALS_TRAIN_MEDIAN_POSITIVE_NEAREST_SQUARED_DISTANCE',
                'missingRule': 'NO_IMPUTATION_ZERO_MEMBERSHIP_ZERO_SUPPORT_LABEL_MINUS_ONE',
                'labelOrder': 'LEXICOGRAPHIC_SOFT_WEIGHTED_RAW_SEMANTIC_FEATURE_MEANS_LOW_TO_HIGH',
                'finalOotPayloadRowsRead': 0, 'laterDevelopmentRowsUsedForClusterParameters': 0}
    return system, metadata
