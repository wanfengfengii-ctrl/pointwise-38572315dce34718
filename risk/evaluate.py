from dataclasses import dataclass
from fractions import Fraction
import sqlite3

from models.frequency import laws_from_counts
from models.law import LawOrigin
from models.pool import merge_selection, validate_cohort_selection
from risk.accept import read_accepted_model, read_accepted_pool
from risk.clearance import classes_clearance, eventual_clearance, population_clearance
from risk.rounds import classes_round_distribution, validate_round
from trials.offspring import ParentKind, validate_parent_kind


@dataclass(frozen=True, slots=True)
class RiskResult:
    accepted_id: int
    model_id: str
    origin: LawOrigin
    initial_kind: ParentKind
    round_number: int
    clearance: Fraction
    conditional_cooccurrence: Fraction | None


@dataclass(frozen=True, slots=True)
class PoolEvaluation:
    accepted_id: str
    origins: tuple[LawOrigin, ...]
    initial_kind: ParentKind
    round_number: int
    counts_a: tuple[int, int, int, int]
    counts_b: tuple[int, int]
    clearance: Fraction
    conditional_cooccurrence: Fraction | None


def evaluate(
    connection: sqlite3.Connection, accepted_id: int, initial_kind: ParentKind, round_number: int
) -> RiskResult:
    initial_kind = validate_parent_kind(initial_kind)
    round_number = validate_round(round_number)
    model = read_accepted_model(connection, accepted_id)
    clearances = eventual_clearance(model.law)
    clearance = clearances.for_kind(initial_kind)
    conditional = None
    if clearance:
        joint = _cooccurrence(clearances, model.law.classes, initial_kind, round_number)
        conditional = joint / clearance
    return RiskResult(
        model.accepted_id, model.law.model_id, model.law.origin,
        initial_kind, round_number, clearance, conditional,
    )


def _cooccurrence(clearances, classes, initial_kind: ParentKind, round_number: int) -> Fraction:
    distribution = classes_round_distribution(classes, initial_kind, round_number)
    joint = sum((
        mass * population_clearance(clearances, population)
        for population, mass in distribution.items()
        if population[0] > 0 and population[1] > 0
    ), Fraction(0))
    return joint


def evaluate_pool(
    connection: sqlite3.Connection,
    accepted_id: str,
    cohort_ids: list[str] | tuple[str, ...],
    initial_kind: ParentKind,
    round_number: int,
) -> PoolEvaluation:
    """Evaluate a pooled selection with the same exact risk calculus as V1."""
    initial_kind = validate_parent_kind(initial_kind)
    round_number = validate_round(round_number)
    identities = validate_cohort_selection(cohort_ids, 1)
    document = read_accepted_pool(connection, accepted_id)
    origins, counts_a, counts_b = merge_selection(document, identities)
    classes = laws_from_counts(counts_a, counts_b)
    clearances = classes_clearance(classes)
    clearance = clearances.for_kind(initial_kind)
    conditional = None
    if clearance:
        joint = _cooccurrence(clearances, classes, initial_kind, round_number)
        conditional = joint / clearance
    return PoolEvaluation(
        accepted_id, origins, initial_kind, round_number,
        counts_a, counts_b, clearance, conditional,
    )
