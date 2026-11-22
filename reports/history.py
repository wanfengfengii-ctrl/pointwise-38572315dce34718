import sqlite3

from reports.store import SignedReport, SignedReportStore


class ReportNotFoundError(LookupError):
    """The requested report number was not signed in this receiver database."""


def read(connection: sqlite3.Connection, report_id: int) -> SignedReport:
    report = SignedReportStore(connection).find(report_id)
    if report is None:
        raise ReportNotFoundError(f'unknown report {report_id!r}')
    return report
