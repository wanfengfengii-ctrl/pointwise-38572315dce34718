from dataclasses import dataclass
from fractions import Fraction

from trials.offspring import Offspring, ParentKind, supported_offspring, validate_offspring, validate_parent_kind


@dataclass(frozen=True, slots=True)
class ClassLaw:
    parent_kind: ParentKind
    sample_size: int
    frequencies: tuple[tuple[Offspring, Fraction], ...]

    def probability(self, offspring: Offspring) -> Fraction:
        combination = validate_offspring(self.parent_kind, offspring)
        return dict(self.frequencies)[combination]


@dataclass(frozen=True, slots=True)
class LawOrigin:
    cohort_id: str
    revision_id: int
    cohort_digest: str


@dataclass(frozen=True, slots=True)
class FrozenLaw:
    model_id: str
    origin: LawOrigin
    classes: tuple[ClassLaw, ClassLaw]

    def for_kind(self, kind: ParentKind) -> ClassLaw:
        return self.classes[0] if validate_parent_kind(kind) == 'A' else self.classes[1]


def _valid_identity(value: str) -> bool:
    return isinstance(value, str) and bool(value.strip()) and '\x00' not in value


def validate_origin(origin: LawOrigin) -> None:
    if not isinstance(origin, LawOrigin) or not _valid_identity(origin.cohort_id):
        raise ValueError('invalid cohort origin')
    if type(origin.revision_id) is not int or not 0 < origin.revision_id < 2**63:
        raise ValueError('invalid origin revision')
    digest = origin.cohort_digest
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('invalid cohort digest')


def validate_law(law: FrozenLaw) -> None:
    if not isinstance(law, FrozenLaw) or not _valid_identity(law.model_id):
        raise ValueError('invalid model identity')
    validate_origin(law.origin)
    if not isinstance(law.classes, tuple) or len(law.classes) != 2:
        raise ValueError('model must contain two class laws')
    for kind, row in zip(('A', 'B'), law.classes):
        if not isinstance(row, ClassLaw) or row.parent_kind != kind:
            raise ValueError('class laws must appear in A, B order')
        if type(row.sample_size) is not int or not 0 < row.sample_size < 2**63:
            raise ValueError(f'invalid SQLite observation count for {kind}')
        support = supported_offspring(kind)
        if not isinstance(row.frequencies, tuple) or len(row.frequencies) != len(support):
            raise ValueError(f'incomplete offspring support for {kind}')
        total = Fraction(0)
        for expected, pair in zip(support, row.frequencies):
            if not isinstance(pair, tuple) or len(pair) != 2 or pair[0] != expected:
                raise ValueError(f'invalid offspring support or order for {kind}')
            probability = pair[1]
            if not isinstance(probability, Fraction) or not 0 <= probability <= 1:
                raise ValueError(f'invalid probability for {kind} {expected!r}')
            if (probability * row.sample_size).denominator != 1:
                raise ValueError(f'probability does not represent a whole observation count for {kind}')
            total += probability
        if total != 1:
            raise ValueError(f'probabilities for {kind} must sum to one')
