from dataclasses import dataclass
from fractions import Fraction

from models.law import FrozenLaw
from trials.offspring import ParentKind, validate_parent_kind


@dataclass(frozen=True, slots=True)
class ClearanceProbabilities:
    a: Fraction
    b: Fraction

    def for_kind(self, kind: ParentKind) -> Fraction:
        return self.a if validate_parent_kind(kind) == 'A' else self.b


def eventual_clearance(law: FrozenLaw) -> ClearanceProbabilities:
    """Find the least fixed point of the two offspring generating functions."""
    a_law, b_law = law.classes
    b_empty = b_law.probability(())
    b_single_a = b_law.probability(('A',))

    # Substituting qB = b_empty + b_single_a * qA leaves a quadratic in qA.
    # Its fixed-point equation factors as (qA - 1) * (quadratic * qA - constant) = 0.
    constant = a_law.probability(()) + a_law.probability(('B',)) * b_empty
    quadratic = a_law.probability(('A', 'B')) * b_single_a
    if quadratic:
        q_a = min(Fraction(1), constant / quadratic)
    elif constant:
        q_a = Fraction(1)
    else:
        # Every qA solves the equation. The least one gives actual clearance.
        q_a = Fraction(0)
    return ClearanceProbabilities(q_a, b_empty + b_single_a * q_a)


def population_clearance(probabilities: ClearanceProbabilities, population: tuple[int, int]) -> Fraction:
    count_a, count_b = population
    if any(type(count) is not int or count < 0 for count in population):
        raise ValueError('population counts must be nonnegative integers')
    return probabilities.a ** count_a * probabilities.b ** count_b
