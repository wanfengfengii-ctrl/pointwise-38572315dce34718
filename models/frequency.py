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
