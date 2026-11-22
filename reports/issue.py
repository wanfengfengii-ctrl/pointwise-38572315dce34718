import sqlite3

from reports.store import SignedReport, SignedReportStore
from risk.evaluate import evaluate
from trials.offspring import ParentKind


def issue(
    connection: sqlite3.Connection, accepted_id: int, initial_kind: ParentKind, round_number: int
) -> SignedReport:
    result = evaluate(connection, accepted_id, initial_kind, round_number)
    return SignedReportStore(connection).commit(result)
