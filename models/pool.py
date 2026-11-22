"""V2 pooled documents: summary evidence encoding and selection merging.

A pooled document carries only cohort origins and aggregate counts. Inspection
identities, original observations, and any per-inspection link tokens (including
per-inspection hashes) stay in the source database. Each evidence cell tallies
the source inspections that share one parent kind and one per-cohort vector of
effective offspring values, so the night shift can judge conflicts and verify
exact merged counts for every legal cohort selection.
"""
from dataclasses import dataclass
from hmac import compare_digest
import json

from models.codec import decode_origin, encode_origin, require_fields
from models.exchange import _body_digest, _canonical, _unique_object
from models.frequency import MissingClassError
from models.law import LawOrigin, validate_origin
from trials.batches import validate_identity
from trials.offspring import Offspring, ParentKind, supported_offspring, validate_parent_kind


@dataclass(frozen=True, slots=True)
class PoolCell:
    """Aggregate count of source inspections sharing one per-cohort value vector."""
    parent_kind: ParentKind
    values: tuple[Offspring | None, ...]
    count: int


@dataclass(frozen=True, slots=True)
class PoolDocument:
    origins: tuple[LawOrigin, ...]
    cells: tuple[PoolCell, ...]
    text: str


def validate_cohort_selection(cohort_ids: object, minimum: int) -> tuple[str, ...]:
    if isinstance(cohort_ids, (str, bytes)) or not isinstance(cohort_ids, (list, tuple)):
        raise ValueError('cohort selection must be a list or tuple of cohort IDs')
    identities = tuple(validate_identity(identity, 'cohort ID') for identity in cohort_ids)
    if len(identities) < minimum:
        raise ValueError(f'cohort selection must list at least {minimum} cohort IDs')
    if len(set(identities)) != len(identities):
        raise ValueError('cohort selection must list distinct cohort IDs')
    return identities


def _validate_origins(origins: tuple[LawOrigin, ...]) -> None:
    if len(origins) < 2:
        raise ValueError('a pool document must list at least two cohort origins')
    cohort_ids = []
    for origin in origins:
        validate_origin(origin)
        cohort_ids.append(origin.cohort_id)
    if len(set(cohort_ids)) != len(cohort_ids):
        raise ValueError('a pool document must list each cohort origin once')
    if cohort_ids != sorted(cohort_ids):
        raise ValueError('pool origins must be ordered by cohort ID')


def _validate_cells(cells: tuple[PoolCell, ...], width: int) -> None:
    seen = set()
    for cell in cells:
        if not isinstance(cell, PoolCell):
            raise ValueError('invalid pool evidence cell')
        kind = validate_parent_kind(cell.parent_kind)
        if not isinstance(cell.values, tuple) or len(cell.values) != width:
            raise ValueError('pool cell values must match the origin count')
        if all(value is None for value in cell.values):
            raise ValueError('pool cell must reference at least one cohort')
        for value in cell.values:
            if value is not None and value not in supported_offspring(kind):
                raise ValueError(f'invalid offspring {value!r} for parent {kind}')
        if type(cell.count) is not int or not 0 < cell.count < 2**63:
            raise ValueError('pool cell count must be a positive SQLite integer')
        key = (kind, cell.values)
        if key in seen:
            raise ValueError('duplicate pool evidence cell')
        seen.add(key)


def build_pool_cells(cohorts: tuple) -> tuple[PoolCell, ...]:
    """Aggregate frozen members into per-vector counts; identities stay at the source."""
    width = len(cohorts)
    kinds: dict[str, ParentKind] = {}
    vectors: dict[str, list] = {}
    for position, cohort in enumerate(cohorts):
        for member in cohort.members:
            identity = member.observation.inspection_id
            if identity not in vectors:
                kinds[identity] = member.observation.parent_kind
                vectors[identity] = [None] * width
            vectors[identity][position] = member.offspring
    tallies: dict[tuple, int] = {}
    for identity, values in vectors.items():
        key = (kinds[identity], tuple(values))
        tallies[key] = tallies.get(key, 0) + 1
    cells = tuple(
        PoolCell(kind, values, count)
        for (kind, values), count in sorted(
            tallies.items(),
            key=lambda item: (item[0][0], tuple(
                (0, '') if value is None else (1, ''.join(value))
                for value in item[0][1]
            )),
        )
    )
    _validate_cells(cells, width)
    return cells


def encode_pool_document(origins: tuple[LawOrigin, ...], cells: tuple[PoolCell, ...]) -> str:
    origins = tuple(origins)
    cells = tuple(cells)
    _validate_origins(origins)
    _validate_cells(cells, len(origins))
    body = {
        'origins': [encode_origin(origin) for origin in origins],
        'evidence': {
            'cells': [
                {
                    'kind': cell.parent_kind,
                    'values': [None if value is None else ''.join(value) for value in cell.values],
                    'count': cell.count,
                }
                for cell in cells
            ],
        },
    }
    return _canonical({'version': 2, 'body': body, 'body_sha256': _body_digest(body)})


def _decode_cell_value(kind: ParentKind, value: object) -> Offspring | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('pool cell values must be null or offspring strings')
    if value not in {''.join(combination) for combination in supported_offspring(kind)}:
        raise ValueError(f'invalid offspring string {value!r} for parent {kind}')
    return tuple(value)


def _decode_cells(value: object, width: int) -> tuple[PoolCell, ...]:
    fields = require_fields(value, {'cells'}, 'pool evidence')
    entries = fields['cells']
    if not isinstance(entries, list):
        raise ValueError('pool evidence cells must be a list')
    cells = []
    for entry in entries:
        cell_fields = require_fields(entry, {'kind', 'values', 'count'}, 'pool cell')
        kind = validate_parent_kind(cell_fields['kind'])
        values = cell_fields['values']
        if not isinstance(values, list):
            raise ValueError('pool cell values must be a list')
        cells.append(PoolCell(
            kind,
            tuple(_decode_cell_value(kind, item) for item in values),
            cell_fields['count'],
        ))
    cells = tuple(cells)
    _validate_cells(cells, width)
    return cells


def decode_pool_document(text: str) -> PoolDocument:
    if not isinstance(text, str):
        raise ValueError('pool document must be JSON text')
    value = json.loads(text, object_pairs_hook=_unique_object)
    fields = require_fields(value, {'version', 'body', 'body_sha256'}, 'pool document')
    if type(fields['version']) is not int or fields['version'] != 2:
        raise ValueError('unsupported pool document version')
    digest = fields['body_sha256']
    if (
        not isinstance(digest, str) or not digest.isascii()
        or not compare_digest(digest, _body_digest(fields['body']))
    ):
        raise ValueError('pool document body digest mismatch')
    body = require_fields(fields['body'], {'origins', 'evidence'}, 'pool body')
    origins = body['origins']
    if not isinstance(origins, list):
        raise ValueError('pool origins must be a list')
    decoded_origins = tuple(decode_origin(item) for item in origins)
    _validate_origins(decoded_origins)
    cells = _decode_cells(body['evidence'], len(decoded_origins))
    return PoolDocument(decoded_origins, cells, text)


def merge_selection(
    document: PoolDocument, cohort_ids: tuple[str, ...]
) -> tuple[tuple[LawOrigin, ...], tuple[int, int, int, int], tuple[int, int]]:
    """Merge the selected cohorts into exact per-class offspring counts.

    One source inspection counts once when its effective value agrees across the
    selected cohorts; disagreement inside the selection is a conflict, while
    divergence in unselected cohorts is ignored.
    """
    positions = {origin.cohort_id: index for index, origin in enumerate(document.origins)}
    selected = []
    for cohort_id in cohort_ids:
        if cohort_id not in positions:
            raise ValueError(f'cohort {cohort_id!r} is not part of the accepted pool')
        selected.append(positions[cohort_id])
    counts = {'A': [0] * 4, 'B': [0] * 2}
    for cell in document.cells:
        observed = {cell.values[index] for index in selected}
        observed.discard(None)
        if len(observed) > 1:
            raise ValueError('selected cohorts disagree on a pooled inspection outcome')
        if observed:
            combination = observed.pop()
            support = supported_offspring(cell.parent_kind)
            counts[cell.parent_kind][support.index(combination)] += cell.count
    if sum(counts['A']) == 0 or sum(counts['B']) == 0:
        raise MissingClassError('merged selection is missing a parent class')
    chosen = set(cohort_ids)
    origins = tuple(origin for origin in document.origins if origin.cohort_id in chosen)
    return origins, tuple(counts['A']), tuple(counts['B'])
