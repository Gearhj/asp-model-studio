"""Frozen V18 reproduction and a physically Development-only research cache.

No authority resolver that hashes mixed-OOT objects is used.  The restricted
reader services Arrow read-ahead with zero padding outside authorized byte
ranges: only the footer/header and explicitly eligible row-group column chunks
can reach the filesystem.  Mixed row groups are never read or hashed.
"""
from __future__ import annotations

import hashlib
import io
import json
import struct
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER
from .stage3_corrected_preprocessing_artifacts import _array_digest, load_research_pipeline
from .stage3_model_laboratory import _aligned_probabilities, _validate_probability_matrix

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / '.runtime/asp-model-studio/stage3-model-laboratory'
STUDY = RUNTIME / 'corrected-hgb-recovery-1/study.json'
COMPARISON_SHA = '12bfbc8c4a17a7ef45ec102ef3cb7ca8a9e03b395d0941eed51c98ec3bdf699d'
COMPARISON = ROOT / f'outputs/mlb-corrected-treatment/corrected-hgb-recovery-1-comparison-{COMPARISON_SHA}.json'
CONTEXT_ROOT = Path('C:/Users/james/asp-data-staging/mlb-current-statcast-context-gold-v2')
CONTEXT_SHA = '4c228116951a3505d6a5d955f00cd2b92b35b1ccb85c7c69d11d77828485320e'
COMPANION_ROOT = Path('C:/Users/james/asp-data-staging/mlb-current-statcast-gold-v1')
COMPANION_SHA = '98673b65dc5eab61e39b16d1313c27bbb2cf908c525f80db579cb07a5cfdab33'
OOF_SHA = 'b79a80398ef32a13589a8bb66f5e4e9c698b600195de5369886f7fc07f0dc215'
RF_OOF_SHA = 'b7aefeb898ba1673b66859381d195abdcac43105857ee108ec3081c8bd03ea83'
SAFE_LAST_DATE = '2026-08-06'
DEV_START, DEV_END = '2023-03-30', '2026-08-13'
PROBABILITY_COLUMNS = [f'probability_{name}' for name in PA_CLASS_ORDER]
IDENTITY_COLUMNS = ['canonicalPaId', 'canonicalGameId', 'game_id', 'game_date',
                    'season', 'batterCanonicalPlayerId', 'pitcherCanonicalPlayerId']


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def verified_json(path: Path, expected: str | None = None) -> dict:
    raw = path.read_bytes()
    if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f'Manifest checksum differs: {path}')
    return json.loads(raw)


class AuthorizedByteReader(io.RawIOBase):
    """Read only declared physical byte intervals; pad other read-ahead bytes."""
    def __init__(self, path: Path, ranges: Sequence[tuple[int, int]]):
        super().__init__()
        self.path = path
        self.size = path.stat().st_size
        self.ranges = sorted(ranges)
        self.position = 0
        self.stream = path.open('rb')
        self.physical_reads: list[tuple[int, int]] = []

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = 0) -> int:
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if self.position < 0:
            raise ValueError('Negative seek')
        return self.position

    def read(self, size: int = -1) -> bytes:
        start = self.position
        end = self.size if size < 0 else min(self.size, start + size)
        result = bytearray(max(0, end - start))
        for allowed_start, allowed_end in self.ranges:
            lo, hi = max(start, allowed_start), min(end, allowed_end)
            if lo < hi:
                self.stream.seek(lo)
                value = self.stream.read(hi - lo)
                if len(value) != hi - lo:
                    raise ValueError('Truncated authorized Parquet range')
                result[lo - start:hi - start] = value
                self.physical_reads.append((lo, hi))
        self.position = end
        return bytes(result)

    def close(self) -> None:
        self.stream.close()
        super().close()


def footer_metadata(path: Path) -> tuple[Any, int]:
    """Read exactly eight trailer bytes plus declared footer, never read-ahead."""
    size = path.stat().st_size
    with path.open('rb') as stream:
        stream.seek(size - 8)
        trailer = stream.read(8)
    if trailer[4:] != b'PAR1':
        raise ValueError('Not a supported Parquet object')
    footer_start = size - 8 - struct.unpack('<I', trailer[:4])[0]
    if footer_start < 4:
        raise ValueError('Invalid Parquet footer boundary')
    with AuthorizedByteReader(path, [(0, 4), (footer_start, size)]) as reader:
        metadata = pq.ParquetFile(reader, pre_buffer=False).metadata
    return metadata, footer_start


def row_group_date_bounds(metadata: Any, group: int, date_column: str) -> tuple[str, str]:
    row = metadata.row_group(group)
    matches = [row.column(i) for i in range(row.num_columns)
               if row.column(i).path_in_schema == date_column]
    if len(matches) != 1 or matches[0].statistics is None:
        raise ValueError('Date statistics required before any row-group payload read')
    stats = matches[0].statistics
    if not stats.has_min_max or stats.null_count != 0:
        raise ValueError('Complete date bounds required for physical seal')
    return str(stats.min), str(stats.max)


def read_safe_groups(path: Path, *, columns: Sequence[str] | None = None,
                     date_column: str = 'game_date', last_date: str = DEV_END,
                     first_date: str = DEV_START) -> tuple[pa.Table, dict]:
    metadata, footer_start = footer_metadata(path)
    accepted, rejected, ranges = [], [], [(0, 4), (footer_start, path.stat().st_size)]
    for index in range(metadata.num_row_groups):
        minimum, maximum = row_group_date_bounds(metadata, index, date_column)
        entry = {'rowGroup': index, 'rows': metadata.row_group(index).num_rows,
                 'minimumDate': minimum, 'maximumDate': maximum}
        if minimum < first_date or maximum > last_date:
            rejected.append({**entry, 'reason': 'ROW_GROUP_NOT_WHOLLY_WITHIN_AUTHORIZED_DATES'})
            continue
        accepted.append(entry)
        row = metadata.row_group(index)
        for column_index in range(row.num_columns):
            column = row.column(column_index)
            if columns is not None and column.path_in_schema not in columns:
                continue
            offsets = [column.data_page_offset]
            if column.has_dictionary_page:
                offsets.append(column.dictionary_page_offset)
            start = min(offsets)
            ranges.append((start, start + column.total_compressed_size))
    if not accepted:
        raise ValueError(f'No wholly authorized row groups in {path}')
    with AuthorizedByteReader(path, ranges) as reader:
        file = pq.ParquetFile(reader, pre_buffer=False)
        table = file.read_row_groups([row['rowGroup'] for row in accepted], columns=columns, use_threads=False)
        actual_ranges = list(reader.physical_reads)
    dates = table[date_column].to_pandas().astype(str)
    if not dates.between(first_date, last_date).all():
        raise ValueError('Physical boundary statistics disagreed with materialized dates')
    return table, {'path': str(path), 'acceptedRowGroups': accepted, 'rejectedRowGroups': rejected,
                   'wholeFileHashRead': False, 'physicalPayloadReadPolicy': 'ALLOWLISTED_COLUMN_CHUNK_BYTES_ONLY',
                   'physicalReadCalls': len(actual_ranges), 'physicalReadBytesIncludingRepeatedMetadata': sum(b-a for a,b in actual_ranges),
                   'finalOotPayloadBytesRead': 0}


def _addressed_path(root: Path, entry: dict) -> Path:
    path = (root / entry['relativePath']).resolve()
    if not path.is_relative_to(root.resolve()) or path.stat().st_size != entry['byteCount']:
        raise ValueError('Manifest path/byte count differs')
    return path


def load_raw_development(source_columns: Sequence[str]) -> tuple[pd.DataFrame, dict]:
    manifest = verified_json(CONTEXT_ROOT / f'publications/sha256/{CONTEXT_SHA}/manifest.json', CONTEXT_SHA)
    if manifest['sourceGold']['temporalContract']['finalOot'] != ['2026-08-14', '2026-08-27']:
        raise ValueError('Frozen V18 temporal authority differs')
    frames, scans = [], []
    for entry in manifest['partitions']:
        path = _addressed_path(CONTEXT_ROOT, entry)
        metadata, _ = footer_metadata(path)
        available = set(metadata.schema.to_arrow_schema().names)
        columns = list(dict.fromkeys([*IDENTITY_COLUMNS, 'outcome', 'datasetRole', *source_columns]))
        columns = [name for name in columns if name in available]
        table, scan = read_safe_groups(path, columns=columns)
        if not scan['rejectedRowGroups']:
            if sha_file(path) != entry['sha256']:
                raise ValueError('Wholly Development source checksum differs')
            scan['wholeFileHashRead'] = True
        scan['manifestDeclaredFileSha256'] = entry['sha256']
        scans.append(scan)
        frames.append(table.to_pandas())
    frame = pd.concat(frames, ignore_index=True)
    frame = frame[frame.game_date.astype(str) <= SAFE_LAST_DATE].copy()
    if frame.canonicalPaId.duplicated().any() or set(frame.datasetRole) != {'DEVELOPMENT_SELECTION'}:
        raise ValueError('Development raw identity or role differs')
    companion = verified_json(COMPANION_ROOT / f'sufficient-statistics/publications/sha256/{COMPANION_SHA}/manifest.json', COMPANION_SHA)
    missing = [name for name in source_columns if name not in frame]
    supplements, companion_records = [], []
    for entry in companion['partitions']:
        if entry['partitionRole'] != 'DEVELOPMENT_SELECTION':
            continue  # Do not open even the sealed key-only object.
        if entry['maximumDate'] > DEV_END or entry['finalOotKeyRowCount']:
            raise ValueError('Companion role/date contract differs')
        path = _addressed_path(COMPANION_ROOT, entry)
        if sha_file(path) != entry['sha256']:
            raise ValueError('Development companion checksum differs')
        table, scan = read_safe_groups(path, columns=['canonicalPaId', 'game_date', *missing])
        supplements.append(table.to_pandas())
        companion_records.append({'sha256': entry['sha256'], **scan})
    supp = pd.concat(supplements, ignore_index=True).set_index('canonicalPaId', verify_integrity=True)
    aligned = supp.reindex(frame.canonicalPaId)
    if aligned.game_date.isna().any() or not np.array_equal(aligned.game_date.astype(str), frame.game_date.astype(str)):
        raise ValueError('Companion PA/date identity does not match exact source rows')
    aligned.index = frame.index
    for column in missing:
        frame[column] = aligned[column]
    return frame, {'contextManifestSha256': CONTEXT_SHA, 'companionManifestSha256': COMPANION_SHA,
                   'contextScans': scans, 'companionScans': companion_records,
                   'completeDateCutoff': SAFE_LAST_DATE, 'rawRows': len(frame), 'games': int(frame.canonicalGameId.nunique()),
                   'excludedMixedRowGroupDevelopmentRows': 6960,
                   'mixedRowGroupPolicy': 'EXCLUDE_ENTIRE_GROUP_AND_PARTIAL_BOUNDARY_DATE_2026_08_07',
                   'finalOotPayloadBytesRead': 0, 'finalOotPayloadRowsRead': 0}


def load_oof(sha256: str, family: str) -> pd.DataFrame:
    path = RUNTIME / f'objects/oof/sha256/{sha256}.parquet'
    metadata, _ = footer_metadata(path)
    contract = json.loads(metadata.metadata[b'asp_oof_contract'])
    if (contract['scope'] != 'FIVE_FOLD_OOF_DEVELOPMENT_ONLY' or contract['modelFamily'] != family
            or contract['orderedClasses'] != list(PA_CLASS_ORDER) or contract['finalOotScored']
            or contract['finalOotTargetAccessed'] or sha_file(path) != sha256):
        raise ValueError('OOF authority/checksum differs')
    frame = pq.read_table(path).to_pandas()
    if frame.canonicalPaId.duplicated().any():
        raise ValueError('OOF PA identity must be unique')
    return frame


def _write_parquet(path: Path, frame: pd.DataFrame) -> dict:
    table = pa.Table.from_pandas(frame, preserve_index=False)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression='zstd')
    raw = sink.getvalue().to_pybytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f'Immutable cache conflict: {path}')
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'rows': len(frame)}


def reproduce_and_cache(output: Path, *, emit: Callable[..., None] | None = None) -> dict:
    """Reproduce raw accepted OOF probabilities exactly; never call fit."""
    emit = emit or (lambda *args, **kwargs: None)
    study, comparison = verified_json(STUDY), verified_json(COMPARISON)
    for payload, key in ((study, 'studyChecksum'), (comparison, 'resultChecksum')):
        checksum = hashlib.sha256(canonical_json_bytes({k: v for k, v in payload.items() if k != key})).hexdigest()
        if checksum != payload[key]:
            raise ValueError(f'Frozen {key} content differs')
    if study['targetOrder'] != list(PA_CLASS_ORDER) or comparison['resultChecksum'] != COMPARISON_SHA:
        raise ValueError('Frozen baseline identity differs')
    artifacts = comparison['treatmentExecution']['fittedFoldArtifacts']
    pipelines = [load_research_pipeline(row['localResearchArtifact']['model'], root=RUNTIME) for row in artifacts]
    source_columns = list(pipelines[0].ordered_features)
    if any(list(p.ordered_features) != source_columns or len(p.preprocessor.ordered_features) != 273 for p in pipelines):
        raise ValueError('Frozen 246-raw/273-treated fold schema differs')
    raw, source = load_raw_development(source_columns)
    held = {row['canonicalPaId'] for row in study['rowEligibility']['heldObservations']}
    raw = raw[~raw.canonicalPaId.isin(held)].copy().reset_index(drop=True)
    raw['observedClassIndex'] = raw.outcome.map({name: i for i, name in enumerate(PA_CLASS_ORDER)}).astype('int8')
    raw['foldNumber'] = 0
    for fold in study['folds']:
        raw.loc[raw.game_date.astype(str).between(fold['validationStart'], fold['validationEnd']), 'foldNumber'] = fold['foldNumber']
    oof, rf = load_oof(OOF_SHA, 'histogram_gradient_boosting'), load_oof(RF_OOF_SHA, 'random_forest')
    common = raw[raw.foldNumber > 0].merge(oof, on=['canonicalPaId', 'canonicalGameId', 'foldNumber', 'observedClassIndex'], validate='one_to_one')
    if len(common) != int((raw.foldNumber > 0).sum()):
        raise ValueError('Exact V18 OOF join lost available eligible observations')
    common = common.merge(rf.rename(columns={name: 'rf_' + name for name in PROBABILITY_COLUMNS}),
                          on=['canonicalPaId', 'canonicalGameId', 'foldNumber', 'observedClassIndex'], validate='one_to_one')
    records, fold_checks = {}, []
    records['rawDevelopment'] = _write_parquet(output / 'raw-development.parquet', raw)
    records['matchedOof'] = _write_parquet(output / 'matched-oof.parquet', common[[*IDENTITY_COLUMNS, 'foldNumber', 'observedClassIndex', *PROBABILITY_COLUMNS, *['rf_' + c for c in PROBABILITY_COLUMNS]]])
    for fold, artifact, pipeline in zip(study['folds'], artifacts, pipelines, strict=True):
        number = int(fold['foldNumber'])
        valid = common[common.foldNumber == number].copy()
        inputs = valid.loc[:, source_columns]
        with threadpool_limits(limits=4):
            treated = pipeline.preprocessor.transform_frame(inputs)
            values = pipeline.preprocessor.encoder.transform(treated)
            actual = _validate_probability_matrix(_aligned_probabilities(pipeline.estimator, values), expected_rows=len(valid))
        expected = valid[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
        difference = np.abs(actual - expected)
        if not np.array_equal(actual, expected):
            raise ValueError(f'Frozen fold {number} raw OOF reproduction mismatch: {difference.max()}')
        digest = _array_digest(values)
        complete = len(valid) == artifact['localResearchArtifact']['validationRows']
        if complete and digest != artifact['localResearchArtifact']['transformedValidationSha256']:
            raise ValueError(f'Frozen fold {number} transformed matrix digest differs')
        meta = valid[[*IDENTITY_COLUMNS, 'foldNumber', 'observedClassIndex']].reset_index(drop=True)
        feature_frame = pd.concat([meta, treated.reset_index(drop=True)], axis=1)
        records[f'validationFold{number}'] = _write_parquet(output / f'validation-fold-{number}-treated.parquet', feature_frame)
        check = {'foldNumber': number, 'rows': len(valid), 'registeredEligibleRows': artifact['localResearchArtifact']['validationRows'],
                 'games': int(valid.canonicalGameId.nunique()), 'completeRegisteredFold': complete,
                 'rawPredictionBitwiseMismatchCount': int(np.count_nonzero(difference)), 'maximumAbsoluteDifference': float(difference.max()),
                 'transformedValidationSha256': digest, 'fullFoldTransformDigestVerified': complete,
                 'model': artifact['localResearchArtifact']['model'], 'modelParameters': pipeline.estimator.get_params(deep=False)}
        fold_checks.append(check)
        emit('BASELINE_FOLD_REPRODUCED', **check)
        if number == 1:
            train = raw[raw.game_date.astype(str).between(fold['trainStart'], fold['trainEnd'])].copy()
            with threadpool_limits(limits=4):
                train_values = pipeline.preprocessor.transform_frame(train.loc[:, source_columns])
            train_meta = train[[*IDENTITY_COLUMNS, 'foldNumber', 'observedClassIndex']].reset_index(drop=True)
            records[f'trainingFold{number}'] = _write_parquet(output / f'training-fold-{number}-treated.parquet', pd.concat([train_meta, train_values.reset_index(drop=True)], axis=1))
    missing_ids = set(oof.canonicalPaId) - set(common.canonicalPaId)
    result = {'schemaVersion': 'MLB_REGIME_BASELINE_REPRODUCTION_V1', 'status': 'BITWISE_EXACT_ON_PHYSICALLY_SAFE_COMMON_POPULATION',
              'comparisonChecksum': COMPARISON_SHA, 'v18OofSha256': OOF_SHA, 'rfDiversityOofSha256': RF_OOF_SHA,
              'targetOrder': list(PA_CLASS_ORDER), 'source': source, 'eligibleRawRows': len(raw),
              'registeredOofRows': len(oof), 'usableOofRows': len(common), 'usableOofGames': int(common.canonicalGameId.nunique()),
              'unavailableOofRows': len(missing_ids), 'unavailableOofReason': 'MIXED_SEALED_ROW_GROUP_OR_INCOMPLETE_BOUNDARY_DATE',
              'folds': fold_checks, 'artifacts': records, 'estimatorFits': 0, 'finalOotPayloadBytesRead': 0,
              'treatmentManifestSha256': study['authority']['treatmentManifestChecksum'],
              'modelFeatureSchemaChecksum': study['authority']['modelFeatureSchemaChecksum'],
              'rawFeatureColumns': source_columns, 'treatedFeatureColumns': list(pipelines[0].preprocessor.ordered_features),
              'teamIdentity': 'NOT_IN_GOLD_REQUIRES_SEPARATELY_AUTHENTICATED_SAFE_GAME_MAP',
              'researchStatus': 'RESEARCH_SHADOW', 'wageringAuthority': False}
    raw_result = canonical_json_bytes(result)
    digest = hashlib.sha256(raw_result).hexdigest()
    path = output / f'baseline-reproduction-{digest}.json'
    if not path.exists():
        with path.open('xb') as stream:
            stream.write(raw_result)
    return {'path': str(path.resolve()), 'sha256': digest, **result}
