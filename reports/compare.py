from dataclasses import dataclass
from fractions import Fraction
import sqlite3

from reports.history import read
from reports.store import SignedReport


@dataclass(frozen=True, slots=True)
class ReportComparison:
    older: SignedReport
    newer: SignedReport
    clearance_delta: Fraction | None
    cooccurrence_delta: Fraction | None


def compare_reports(connection: sqlite3.Connection, old_id: int, new_id: int) -> ReportComparison:
    older, newer = read(connection, old_id), read(connection, new_id)
    before, after = older.result, newer.result
    if (before.initial_kind, before.round_number) != (after.initial_kind, after.round_number):
        return ReportComparison(older, newer, None, None)
    old_conditional = before.conditional_cooccurrence
    new_conditional = after.conditional_cooccurrence
    conditional_delta = None
    if old_conditional is not None and new_conditional is not None:
        conditional_delta = new_conditional - old_conditional
    return ReportComparison(older, newer, after.clearance - before.clearance, conditional_delta)
