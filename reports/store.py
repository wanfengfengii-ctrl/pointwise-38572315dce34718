from dataclasses import dataclass
import json
import sqlite3

from models.codec import decode_fraction, decode_origin, encode_fraction, encode_origin
from risk.evaluate import RiskResult


@dataclass(frozen=True, slots=True)
class SignedReport:
    report_id: int
    result: RiskResult


class SignedReportStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS signed_reports (
                report_id INTEGER PRIMARY KEY,
                accepted_id INTEGER NOT NULL REFERENCES accepted_models(accepted_id),
                model_id TEXT NOT NULL,
                origin TEXT NOT NULL,
                initial_kind TEXT NOT NULL CHECK (initial_kind IN ('A', 'B')),
                round_number INTEGER NOT NULL CHECK (round_number BETWEEN 1 AND 6),
                clearance TEXT NOT NULL,
                cooccurrence TEXT
            )
        ''')

    def commit(self, result: RiskResult) -> SignedReport:
        """Commit an evaluated result and its fixed origin before returning a receipt."""
        conditional = result.conditional_cooccurrence
        parameters = (
            result.accepted_id, result.model_id,
            json.dumps(encode_origin(result.origin), sort_keys=True),
            result.initial_kind, result.round_number, json.dumps(encode_fraction(result.clearance)),
            None if conditional is None else json.dumps(encode_fraction(conditional)),
        )
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            cursor = self.connection.execute('''
                INSERT INTO signed_reports (
                    accepted_id, model_id, origin, initial_kind, round_number, clearance, cooccurrence
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', parameters)
            report_id = cursor.lastrowid
        return SignedReport(report_id, result)

    def find(self, report_id: int) -> SignedReport | None:
        if type(report_id) is not int or not 0 < report_id < 2**63:
            return None
        row = self.connection.execute('''
            SELECT accepted_id, model_id, origin, initial_kind, round_number, clearance, cooccurrence
            FROM signed_reports WHERE report_id = ?
        ''', (report_id,)).fetchone()
        if row is None:
            return None
        accepted, model, origin, initial, round_number, clearance, cooccurrence = row
        result = RiskResult(
            accepted, model, decode_origin(json.loads(origin)), initial, round_number,
            decode_fraction(json.loads(clearance)),
            None if cooccurrence is None else decode_fraction(json.loads(cooccurrence)),
        )
        return SignedReport(report_id, result)
