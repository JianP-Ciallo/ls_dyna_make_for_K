"""Pinned third-source physics and physical selectors, never source mesh tables."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .config import DEFAULT_UNIT_SYSTEM, ROOT

SOURCE_SHA256 = 'b4a0d8d363817e691152186fd073440c9e2dc70057b1f2e941ea6110c6b1df38'
INDEX_SHA256 = '4cf9dee2394d484319454d1129d605845b1a9f0e96c37d5bde6f863dc1078c1a'
INDEX_RELATIVE = Path('resources/reviews/source_rebuild/b120_spg_sale/source_index.json')
MATERIAL_RELATIVE = Path('resources/materials/source_rebuild/b120_spg_sale')
STRUCTURAL_RELATIVE = Path('resources/model_library/structural/source_rebuild/b120_spg_sale')
RESOURCE_TYPE = 'source_keyword_bundle'


def source_index():
    raw = (ROOT/INDEX_RELATIVE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != INDEX_SHA256:
        raise ValueError('Third-source index differs from its approved fingerprint')
    return json.loads(raw)


def resource_relative_path(record):
    root = MATERIAL_RELATIVE if record['resource_kind'] == 'materials' else STRUCTURAL_RELATIVE
    return root/(record['id']+'.json')


def validate_resource(record):
    if not isinstance(record, Mapping): raise ValueError('source resource must be an object')
    expected = next((r for r in source_index()['resources'] if r['id'] == record.get('id')), None)
    if expected is None: raise ValueError('unknown third-source resource identity')
    for k, v in expected.items():
        if k != 'source_cards' and record.get(k) != v:
            raise ValueError(f'third-source {k} differs from its pinned definition')
    if record.get('type') != RESOURCE_TYPE or record.get('resource_type') != RESOURCE_TYPE:
        raise ValueError('source resource type must be source_keyword_bundle')
    if record.get('unit_system') != DEFAULT_UNIT_SYSTEM:
        raise ValueError('third-source confirmed SI units must be preserved')
    if record.get('validation_status') != 'source_reference' or record.get('requires_project_review') is not True:
        raise ValueError('source identity must not be promoted to engineering validation')
    provenance = record.get('provenance', {})
    if not isinstance(provenance, Mapping) or provenance.get('source_sha256') != SOURCE_SHA256 or provenance.get('source_unit_system') != DEFAULT_UNIT_SYSTEM:
        raise ValueError('third-source provenance mismatch')
    cards = record.get('source_cards')
    if not isinstance(cards, list) or len(cards) != len(expected['source_cards']):
        raise ValueError('third-source card closure is incomplete')
    for actual, original in zip(cards, expected['source_cards']):
        if not isinstance(actual, Mapping) or any(actual.get(k) != v for k, v in original.items()):
            raise ValueError('third-source card identity or hash differs')
        if record['reuse_policy'] == 'exact_original_card_payload':
            raw = actual.get('raw_text')
            if not isinstance(raw, str) or hashlib.sha256(raw.encode()).hexdigest() != original['raw_sha256']:
                raise ValueError('third-source raw physics card differs')
        elif set(actual) != set(original):
            raise ValueError('mesh recipes cannot contain old mesh/set payloads')
    return {'valid': True, 'resource_id': record['id'], 'resource_type': RESOURCE_TYPE,
            'material_type': RESOURCE_TYPE, 'source_sha256': SOURCE_SHA256,
            'effective_validation_status': 'source_reference', 'requires_project_review': True,
            'validation_scope': 'source card fidelity, confirmed SI and pinned physical selectors; no solver certification'}


def validate_bundle(records):
    expected = {r['id'] for r in source_index()['resources']}
    if len(records) != len(expected) or {r.get('id') for r in records} != expected:
        raise ValueError('complete 47-resource third-source bundle required')
    for r in records: validate_resource(r)
    if any(d not in expected for r in records for d in r['dependencies']):
        raise ValueError('third-source dependencies are not closed')


def load_bundle(root=ROOT):
    records = [json.loads((root/resource_relative_path(r)).read_text(encoding='utf-8')) for r in source_index()['resources']]
    validate_bundle(records)
    return records


def bundle_fingerprint():
    return INDEX_SHA256


def publish_resources(records, root=ROOT):
    validate_bundle(records)
    pending, paths = [], []
    for record in records:
        path = root/resource_relative_path(record); paths.append(str(path))
        if path.exists():
            if json.loads(path.read_text(encoding='utf-8')) != record:
                raise FileExistsError(f'Refusing to overwrite existing resource: {path}')
        else: pending.append((path, record))
    for path, record in pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8', newline='\n') as f:
            json.dump(record, f, ensure_ascii=False, indent=2); f.write('\n')
    return {'resource_count': len(records), 'created': len(pending), 'resource_paths': paths,
            'source_sha256': SOURCE_SHA256, 'bundle_fingerprint': bundle_fingerprint(),
            'validation_status': 'source_reference', 'external_dependencies_missing': ['MT41 implementations for MID2/MID5']}


def register_source(path, root=ROOT):
    path = Path(path); digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''): digest.update(chunk)
    if digest.hexdigest() != SOURCE_SHA256:
        raise ValueError('source file differs from the approved third-source fingerprint')
    index = source_index()
    wanted = {c['source_line_start']: c for r in index['resources'] for c in r['source_cards']}
    payloads = {}; active = None; chunks = []
    with path.open(encoding='ascii', newline='') as f:
        for number, line in enumerate(f, 1):
            if number in wanted:
                active = wanted[number]; chunks = []
            if active is not None:
                chunks.append(line)
                if number == active['source_line_end']:
                    raw = ''.join(chunks)
                    if hashlib.sha256(raw.encode()).hexdigest() != active['raw_sha256']:
                        raise ValueError('original source card bytes do not match the pinned index')
                    payloads[active['source_line_start']] = raw; active = None
    records = []
    for pin in index['resources']:
        r = deepcopy(pin)
        if r['reuse_policy'] == 'exact_original_card_payload':
            for card in r['source_cards']: card['raw_text'] = payloads[card['source_line_start']]
        r.update({'type': RESOURCE_TYPE, 'resource_type': RESOURCE_TYPE, 'schema_version': 'source_keyword_bundle@1',
            'name': r['id'], 'display_name': 'B120 SPG S-ALE / '+r['id'].removeprefix('b120_spg_sale_b4a0d8d36381_'),
            'category': r['resource_kind'], 'unit_system': DEFAULT_UNIT_SYSTEM, 'version': '1.0',
            'validation_status': 'source_reference', 'requires_project_review': True,
            'source': 'B-120-C5-50-6kg-SPG-SALE-total.k', 'notes': 'Original physical fields and blanks retained; mesh selectors rebound by space.',
            'unit_conversion': {'applied': False, 'factor': 1, 'reason': 'User-confirmed SI; original values retained'},
            'provenance': {'source_sha256': SOURCE_SHA256, 'source_name': path.name,
                'source_unit_system': DEFAULT_UNIT_SYSTEM, 'unit_confirmation': 'User confirmed SI on 2026-09-26'},
            'external_dependencies': ['MT=41 implementation not provided'] if r['original_ids'].get('mt') == 41 else []})
        records.append(r)
    return publish_resources(records, root)
