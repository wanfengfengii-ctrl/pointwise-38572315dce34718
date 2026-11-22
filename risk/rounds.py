from collections import defaultdict
from fractions import Fraction
from functools import cache

from models.law import FrozenLaw
from trials.offspring import ParentKind, validate_parent_kind

Population = tuple[int, int]


def validate_round(round_number: int) -> int:
    if type(round_number) is not int or not 1 <= round_number <= 6:
        raise ValueError('round must be an integer from 1 to 6')
    return round_number


def round_distribution(
    law: FrozenLaw, initial_kind: ParentKind, round_number: int
) -> dict[Population, Fraction]:
    initial_kind = validate_parent_kind(initial_kind)
    validate_round(round_number)
    transitions = {
        row.parent_kind: tuple(
            ((combination.count('A'), combination.count('B')), probability)
            for combination, probability in row.frequencies if probability
        )
        for row in law.classes
    }

    @cache
    def offspring_from(count_a: int, count_b: int) -> dict[Population, Fraction]:
        if count_a == count_b == 0:
            return {(0, 0): Fraction(1)}
        if count_a:
            others = offspring_from(count_a - 1, count_b)
            kind = 'A'
        else:
            others = offspring_from(count_a, count_b - 1)
            kind = 'B'
        result = defaultdict(Fraction)
        for (a, b), mass in others.items():
            for (add_a, add_b), probability in transitions[kind]:
                result[a + add_a, b + add_b] += mass * probability
        return dict(result)

    first = (1, 0) if initial_kind == 'A' else (0, 1)
    distribution = {first: Fraction(1)}
    for _ in range(round_number):
        next_round = defaultdict(Fraction)
        for parents, parent_mass in distribution.items():
            for children, conditional_mass in offspring_from(*parents).items():
                next_round[children] += parent_mass * conditional_mass
        distribution = dict(next_round)
    return dict(sorted(distribution.items()))
