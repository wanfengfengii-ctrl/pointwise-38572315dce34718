import sqlite3

from reports.store import PoolReport, PoolReportStore, SignedReport, SignedReportStore


class ReportNotFoundError(LookupError):
    """The requested report number was not signed in this receiver database."""


def read(connection: sqlite3.Connection, report_id: int) -> SignedReport:
    report = SignedReportStore(connection).find(report_id)
    if report is None:
        raise ReportNotFoundError(f'unknown report {report_id!r}')
    return report


def read_pool_report(connection: sqlite3.Connection, report_id: str) -> PoolReport:
    """Read a signed V2 pool report by number; stored facts never change."""
    report = PoolReportStore(connection).find(report_id)
    if report is None:
        raise KeyError(f'unknown pool report {report_id!r}')
    return report
