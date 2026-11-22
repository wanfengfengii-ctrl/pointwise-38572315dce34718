from typing import Literal, cast

ParentKind = Literal['A', 'B']
Offspring = tuple[ParentKind, ...]

_A_SUPPORT: tuple[Offspring, ...] = ((), ('A',), ('B',), ('A', 'B'))
_B_SUPPORT: tuple[Offspring, ...] = ((), ('A',))


def validate_parent_kind(kind: str) -> ParentKind:
    if not isinstance(kind, str) or kind not in ('A', 'B'):
        raise ValueError('parent kind must be A or B')
    return cast(ParentKind, kind)


def supported_offspring(kind: ParentKind) -> tuple[Offspring, ...]:
    return _A_SUPPORT if validate_parent_kind(kind) == 'A' else _B_SUPPORT


def validate_offspring(kind: ParentKind, offspring: Offspring | list[ParentKind]) -> Offspring:
    support = supported_offspring(kind)
    if not isinstance(offspring, (tuple, list)):
        raise ValueError('offspring must be a complete list or tuple')
    combination = tuple(sorted(validate_parent_kind(child) for child in offspring))
    if combination not in support:
        raise ValueError(f'invalid offspring {combination!r} for parent {kind}')
    return combination
