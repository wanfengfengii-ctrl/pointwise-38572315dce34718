from collections import Counter
from fractions import Fraction

from cohort.freeze import FrozenCohort
from models.law import ClassLaw
from trials.offspring import Offspring, supported_offspring


class MissingClassError(ValueError):
    """The frozen cohort contains no completed observation for a parent kind."""


def count_frequencies(cohort: FrozenCohort) -> tuple[ClassLaw, ClassLaw]:
    counts: dict[str, Counter[Offspring]] = {'A': Counter(), 'B': Counter()}
    for member in cohort.members:
        counts[member.observation.parent_kind][member.offspring] += 1

    def class_law(kind):
        observed = counts[kind]
        sample_size = sum(observed.values())
        if sample_size == 0:
            raise MissingClassError(f'no completed {kind} inspections in cohort {cohort.cohort_id}')
        probabilities = tuple(
            (combination, Fraction(observed[combination], sample_size))
            for combination in supported_offspring(kind)
        )
        return ClassLaw(kind, sample_size, probabilities)

    return class_law('A'), class_law('B')


def laws_from_counts(counts_a: tuple[int, ...], counts_b: tuple[int, ...]) -> tuple[ClassLaw, ClassLaw]:
    """Rebuild exact class laws from merged per-combination observation counts."""
    laws = []
    for kind, counts in (('A', counts_a), ('B', counts_b)):
        support = supported_offspring(kind)
        total = sum(counts)
        if len(counts) != len(support) or total <= 0:
            raise ValueError(f'invalid merged observation counts for {kind}')
        laws.append(ClassLaw(kind, total, tuple(
            (combination, Fraction(count, total))
            for combination, count in zip(support, counts)
        )))
    return laws[0], laws[1]
