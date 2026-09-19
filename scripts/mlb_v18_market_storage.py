"""Private, local-only evidence I/O. No database, provider, fitting or publication API."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

PROTOCOL_SHA = 'f75aeccd8f0e472b399d1f470c29d6a443d77078f7c69333023292019d956bf7'
RULE_SHA = '5f8157d80178cfd219922904b4df1af7fe35274c59c8c612ee102e69c727c326'
SCHEMA_SHA = 'f8a7458b8a908ca21d05130a9ed0fdb25d7c84907e6f3e828e95bac728f88594'


def stamp(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Clock has no timezone')
    return parsed.astimezone(timezone.utc)


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                       allow_nan=False) + '\n').encode('utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_ref(path):
    data = Path(path).read_bytes()
    return {'path': str(Path(path).resolve()), 'sha256': sha(data), 'bytes': len(data)}


def write_once(path, data):
    """An interrupted write is invisible; an existing immutable object is never replaced."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('IMMUTABLE_REPLACEMENT_ATTEMPT: ' + str(path))
        return
    pending = path.with_name(path.name + '.' + str(os.getpid()) + '.pending')
    with pending.open('xb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    # On Windows rename refuses an existing destination.
    pending.rename(path)


def write_pointer(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + '.' + str(os.getpid()) + '.pending')
    with pending.open('xb') as handle:
        handle.write(encode(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(pending, path)


def load_ledger(path):
    """Read only complete lines. The writer's incomplete final line is not a receipt."""
    path = Path(path)
    data = path.read_bytes() if path.exists() else b''
    lines = data.splitlines(keepends=True)
    if lines and not lines[-1].endswith(b'\n'):
        lines.pop()
    previous, records, prefix = None, [], b''
    for i, line in enumerate(lines, 1):
        item = json.loads(line)
        if item.get('seq') != i or item.get('prevLineSha256') != previous:
            raise ValueError('CONSUMER_LEDGER_CHAIN_MISMATCH')
        if item.get('protocolSha256') != PROTOCOL_SHA:
            raise ValueError('CONSUMER_LEDGER_PROTOCOL_MISMATCH')
        body = line.rstrip(b'\r\n')
        previous = sha(body)
        prefix += line
        records.append((item, {'path': str(path.resolve()), 'sha256': previous,
                               'bytes': len(body), 'locator': 'attempt-ledger.jsonl#seq=' + str(i)}))
    return records, prefix


class RetainedRefs:
    """Verify narrowly permitted prediction/evidence references; never follow source history links."""
    def __init__(self, consumer, runtime, ledger_records=(), extra_roots=()):
        self.consumer = Path(consumer).resolve()
        self.runtime = Path(runtime).resolve()
        self.pipeline = self.runtime / 'outputs/mlb-v18-current-state-pipeline-v1'
        self.extra_roots = [Path(p).resolve() for p in extra_roots]
        self.ledger = {str(i['seq']): (i, r) for i, r in ledger_records}
        self.cache = {}
        self.phase_metadata = None
        self.recoveries = []

    def __call__(self, ref):
        if not isinstance(ref, dict) or not {'path', 'sha256', 'bytes'} <= ref.keys():
            raise ValueError('MISSING_PHYSICAL_REFERENCE')
        locator = ref.get('locator') or ''
        supplied = Path(ref['path'])
        path = (supplied if supplied.is_absolute() else self.consumer / supplied).resolve()
        if self.phase_metadata and path == Path(self.phase_metadata['path']).resolve():
            item = self.phase_metadata
            raw_root = self.runtime.parent / 'ai-sports-predictor/data/raw/mlb_stats_api'
            if not path.is_relative_to(raw_root) or '/2026/09/' not in path.as_posix():
                raise ValueError('PHASE_SOURCE_OUTSIDE_PERMITTED_SEPTEMBER_METADATA')
            if any(ref[k] != item[k] for k in ('sha256', 'bytes')):
                raise ValueError('PHASE_SOURCE_REFERENCE_DISAGREES_WITH_SEALED_METADATA')
            # Hash-only byte verification. Do not parse raw schedule outcome fields.
            physical = file_ref(path)
            if any(physical[k] != ref[k] for k in ('sha256', 'bytes')):
                raise ValueError('PHASE_SOURCE_PHYSICAL_HASH_MISMATCH')
            return item
        if '#seq=' in locator:
            item, expected = self.ledger[locator.rsplit('#seq=', 1)[1]]
            if path != self.consumer / 'attempt-ledger.jsonl' or any(ref[k] != expected[k] for k in ('sha256', 'bytes')):
                raise ValueError('LEDGER_LINE_REFERENCE_MISMATCH')
            return item
        allowed_consumer = path.parent == self.consumer and path.suffix == '.json'
        allowed_extra = any(path.is_relative_to(p) for p in self.extra_roots)
        allowed_prediction = path.is_relative_to(self.pipeline / 'objects/sha256') and path.name in {
            'forecast.json', 'manifest.json', 'pregame-evidence.json', 'execution-inputs.json',
            'feature-snapshot.json', 'representative-path.json'}
        allowed_governance = path == self.runtime / 'server/artifacts/governance/mlb-final-oot-quarantine-v1.json'
        model_root = self.runtime / 'outputs/mlb-v18-whole-game-challenger/sha256/a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27/executable'
        allowed_model = path.parent == model_root and path.name in {'v18-pa-fold5.joblib', 'transition-fold4.json'}
        allowed_observer = path.is_relative_to(self.runtime / 'outputs/mlb-v18-unattended-v1/objects/sha256') and path.name == 'incremental-publication.json'
        frozen_suffix = '/server/app/research_exports/frozen/mlb_v18_market_prospective_v1/'
        allowed_frozen = path.is_relative_to(self.runtime.parent / 'ai-sports-predictor') and frozen_suffix in path.as_posix() and (
            (path.name == 'protocol.json' and ref['sha256'] == PROTOCOL_SHA and ref['bytes'] == 2595) or
            (path.name == 'PACKET_SCHEMA.json' and ref['sha256'] == SCHEMA_SHA and ref['bytes'] == 7033))
        # Exchange refs can be object-specific renamed manifests/prediction evidence only.
        exchange = self.runtime.parent / 'asp-model-exchange'
        allowed_exchange = path.is_relative_to(exchange) and (
            path.name in {'aisp-handoff.json', 'manifest.json', 'pregame-evidence.json', 'incremental-publication.json'}
            or bool(re.fullmatch(r'(?:object-)?[0-9a-f]{64}[-.]manifest\.json', path.name)))
        if not (allowed_consumer or allowed_prediction or allowed_governance or allowed_exchange or allowed_extra or allowed_model or allowed_observer or allowed_frozen):
            raise ValueError('REFERENCE_OUTSIDE_READ_SCOPE: ' + str(path))
        if allowed_frozen and not path.exists():
            original = str(path)
            path = self.runtime / 'outputs/mlb-v18-market-prospective-v1/objects/sha256' / PROTOCOL_SHA / path.name
            self.recoveries.append({'originalRef': dict(ref), 'verifiedIdenticalLocation': str(path),
                                    'meaning': 'EXACT_FROZEN_DOCUMENT_BYTES_ONLY_NO_FORECAST_OR_INPUT_SUBSTITUTION'})
        cache_key = (str(path), ref['sha256'], ref['bytes'])
        stat = path.stat()
        cached = self.cache.get(cache_key)
        if not cached or cached[0] != (stat.st_mtime_ns, stat.st_size):
            data = path.read_bytes()
            if len(data) != ref['bytes'] or sha(data) != ref['sha256']:
                raise ValueError('PHYSICAL_REFERENCE_MISMATCH: ' + str(path))
            value = dict(ref) if allowed_model else json.loads(data)
            self.cache[cache_key] = ((stat.st_mtime_ns, stat.st_size), value)
        else:
            value = cached[1]
        if locator.startswith('/'):
            for part in locator.split('/')[1:]:
                part = part.replace('~1', '/').replace('~0', '~')
                value = value[int(part)] if isinstance(value, list) else value[part]
        return value


def schema_errors(value, schema, root=None, where='$'):
    """Complete evaluator for the keywords present in the byte-frozen packet schema."""
    root = root or schema
    if '$ref' in schema:
        target = root
        for part in schema['$ref'].split('/')[1:]:
            target = target[part]
        return schema_errors(value, target, root, where)
    if 'anyOf' in schema:
        return [] if any(not schema_errors(value, s, root, where) for s in schema['anyOf']) else [where + ': anyOf']
    errors = []
    kinds = {'object': lambda x: isinstance(x, dict), 'array': lambda x: isinstance(x, list),
             'string': lambda x: isinstance(x, str), 'null': lambda x: x is None,
             'boolean': lambda x: isinstance(x, bool), 'integer': lambda x: isinstance(x, int) and not isinstance(x, bool),
             'number': lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)}
    types = schema.get('type', list(kinds))
    types = [types] if isinstance(types, str) else types
    if not any(kinds[t](value) for t in types):
        return [where + ': type']
    if 'const' in schema and value != schema['const']:
        errors.append(where + ': const')
    if 'enum' in schema and value not in schema['enum']:
        errors.append(where + ': enum')
    if isinstance(value, dict):
        errors.extend(where + ': missing ' + k for k in schema.get('required', []) if k not in value)
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False:
            errors.extend(where + ': unexpected ' + k for k in value if k not in props)
        for k, child in value.items():
            if k in props:
                errors.extend(schema_errors(child, props[k], root, where + '.' + k))
    elif isinstance(value, list) and 'items' in schema:
        for i, child in enumerate(value):
            errors.extend(schema_errors(child, schema['items'], root, where + '[' + str(i) + ']'))
    elif isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or ('pattern' in schema and not re.search(schema['pattern'], value)):
            errors.append(where + ': string constraint')
        if schema.get('format') == 'date-time':
            try:
                stamp(value)
            except (ValueError, TypeError):
                errors.append(where + ': zoned date-time')
    elif isinstance(value, (float, int)) and not isinstance(value, bool):
        import math
        if not math.isfinite(value) or value < schema.get('minimum', float('-inf')) or value > schema.get('maximum', float('inf')) or value <= schema.get('exclusiveMinimum', float('-inf')):
            errors.append(where + ': numeric constraint')
    return errors
