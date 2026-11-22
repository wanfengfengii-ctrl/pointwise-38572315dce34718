from fractions import Fraction

from models.law import ClassLaw, FrozenLaw, LawOrigin, validate_law, validate_origin
from trials.offspring import validate_offspring, validate_parent_kind


def encode_fraction(value: Fraction) -> list[int]:
    if not isinstance(value, Fraction):
        raise ValueError('expected an exact Fraction')
    return [value.numerator, value.denominator]


def decode_fraction(value: object) -> Fraction:
    if (
        not isinstance(value, list) or len(value) != 2
        or any(type(item) is not int for item in value) or value[1] <= 0
    ):
        raise ValueError('expected an integer fraction pair with a positive denominator')
    return Fraction(*value)


def require_fields(value: object, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f'invalid {label} fields')
    return value


def encode_origin(origin: LawOrigin) -> dict:
    validate_origin(origin)
    return {
        'cohort_id': origin.cohort_id,
        'revision_id': origin.revision_id,
        'cohort_digest': origin.cohort_digest,
    }


def decode_origin(value: object) -> LawOrigin:
    fields = require_fields(value, {'cohort_id', 'revision_id', 'cohort_digest'}, 'origin')
    origin = LawOrigin(**fields)
    validate_origin(origin)
    return origin


def encode_law(law: FrozenLaw) -> dict:
    validate_law(law)
    return {
        'model_id': law.model_id,
        'origin': encode_origin(law.origin),
        'classes': [
            {
                'parent_kind': row.parent_kind,
                'sample_size': row.sample_size,
                'frequencies': [[list(combination), encode_fraction(mass)] for combination, mass in row.frequencies],
            }
            for row in law.classes
        ],
    }


def _decode_class(value: object) -> ClassLaw:
    fields = require_fields(value, {'parent_kind', 'sample_size', 'frequencies'}, 'class law')
    kind = validate_parent_kind(fields['parent_kind'])
    entries = fields['frequencies']
    if not isinstance(entries, list):
        raise ValueError('frequencies must be a list')
    frequencies = []
    for entry in entries:
        if not isinstance(entry, list) or len(entry) != 2 or not isinstance(entry[0], list):
            raise ValueError('invalid frequency entry')
        combination = validate_offspring(kind, entry[0])
        if tuple(entry[0]) != combination:
            raise ValueError('offspring combination is out of canonical order')
        frequencies.append((combination, decode_fraction(entry[1])))
    return ClassLaw(kind, fields['sample_size'], tuple(frequencies))


def decode_law(value: object) -> FrozenLaw:
    fields = require_fields(value, {'model_id', 'origin', 'classes'}, 'law')
    classes = fields['classes']
    if not isinstance(classes, list) or len(classes) != 2:
        raise ValueError('model must contain two class laws')
    law = FrozenLaw(
        fields['model_id'], decode_origin(fields['origin']),
        (_decode_class(classes[0]), _decode_class(classes[1])),
    )
    validate_law(law)
    return law
