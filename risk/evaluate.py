from dataclasses import dataclass
from fractions import Fraction
import sqlite3

from models.law import LawOrigin
from risk.accept import read_accepted_model
from risk.clearance import eventual_clearance, population_clearance
from risk.rounds import round_distribution, validate_round
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
        distribution = round_distribution(model.law, initial_kind, round_number)
        joint = sum((
            mass * population_clearance(clearances, population)
            for population, mass in distribution.items()
            if population[0] > 0 and population[1] > 0
        ), Fraction(0))
        conditional = joint / clearance
    return RiskResult(
        model.accepted_id, model.law.model_id, model.law.origin,
        initial_kind, round_number, clearance, conditional,
    )
