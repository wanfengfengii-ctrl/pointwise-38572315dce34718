import sqlite3

from reports.store import PoolReport, PoolReportStore, SignedReport, SignedReportStore
from risk.evaluate import evaluate, evaluate_pool
from trials.offspring import ParentKind


def issue(
    connection: sqlite3.Connection, accepted_id: int, initial_kind: ParentKind, round_number: int
) -> SignedReport:
    result = evaluate(connection, accepted_id, initial_kind, round_number)
    return SignedReportStore(connection).commit(result)


def issue_pool(
    connection: sqlite3.Connection,
    accepted_id: str,
    cohort_ids: list[str] | tuple[str, ...],
    initial_kind: ParentKind,
    round_number: int,
) -> PoolReport:
    """Sign a report for a non-empty selection of cohorts from an accepted pool."""
    evaluation = evaluate_pool(connection, accepted_id, cohort_ids, initial_kind, round_number)
    return PoolReportStore(connection).commit(evaluation)
