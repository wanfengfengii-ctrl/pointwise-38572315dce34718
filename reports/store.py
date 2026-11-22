from dataclasses import dataclass
from fractions import Fraction
import json
import sqlite3
from uuid import uuid4

from models.codec import decode_fraction, decode_origin, encode_fraction, encode_origin
from models.law import LawOrigin
from risk.evaluate import PoolEvaluation, RiskResult
from trials.batches import validate_identity
from trials.offspring import ParentKind, validate_parent_kind


@dataclass(frozen=True, slots=True)
class SignedReport:
    report_id: int
    result: RiskResult


@dataclass(frozen=True, slots=True)
class PoolReport:
    report_id: str
    accepted_id: str
    origins: tuple[LawOrigin, ...]
    initial_kind: ParentKind
    round_number: int
    counts_a: tuple[int, int, int, int]
    counts_b: tuple[int, int]
    clearance: Fraction
    conditional_cooccurrence: Fraction | None


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


def _decode_counts(value: object, width: int, label: str) -> tuple[int, ...]:
    if (
        not isinstance(value, list) or len(value) != width
        or any(type(count) is not int or count < 0 for count in value)
    ):
        raise ValueError(f'stored {label} counts are invalid')
    return tuple(value)


class PoolReportStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS signed_pool_reports (
                report_id TEXT PRIMARY KEY NOT NULL,
                accepted_id TEXT NOT NULL REFERENCES accepted_pools(accepted_id),
                origins TEXT NOT NULL,
                initial_kind TEXT NOT NULL CHECK (initial_kind IN ('A', 'B')),
                round_number INTEGER NOT NULL CHECK (round_number BETWEEN 1 AND 6),
                counts_a TEXT NOT NULL,
                counts_b TEXT NOT NULL,
                clearance TEXT NOT NULL,
                cooccurrence TEXT
            )
        ''')

    def commit(self, evaluation: PoolEvaluation) -> PoolReport:
        """Atomically commit the acceptance, selected origins, counts, request, and result."""
        conditional = evaluation.conditional_cooccurrence
        report_id = uuid4().hex
        parameters = (
            report_id, evaluation.accepted_id,
            json.dumps([encode_origin(origin) for origin in evaluation.origins], sort_keys=True),
            evaluation.initial_kind, evaluation.round_number,
            json.dumps(evaluation.counts_a), json.dumps(evaluation.counts_b),
            json.dumps(encode_fraction(evaluation.clearance)),
            None if conditional is None else json.dumps(encode_fraction(conditional)),
        )
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            self.connection.execute('''
                INSERT INTO signed_pool_reports (
                    report_id, accepted_id, origins, initial_kind, round_number,
                    counts_a, counts_b, clearance, cooccurrence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', parameters)
        return PoolReport(
            report_id, evaluation.accepted_id, evaluation.origins, evaluation.initial_kind,
            evaluation.round_number, evaluation.counts_a, evaluation.counts_b,
            evaluation.clearance, evaluation.conditional_cooccurrence,
        )

    def find(self, report_id: str) -> PoolReport | None:
        report_id = validate_identity(report_id, 'report ID')
        row = self.connection.execute('''
            SELECT accepted_id, origins, initial_kind, round_number, counts_a, counts_b,
                   clearance, cooccurrence
            FROM signed_pool_reports WHERE report_id = ?
        ''', (report_id,)).fetchone()
        if row is None:
            return None
        accepted_id, origins, initial, round_number, counts_a, counts_b, clearance, cooccurrence = row
        return PoolReport(
            report_id, accepted_id,
            tuple(decode_origin(item) for item in json.loads(origins)),
            validate_parent_kind(initial), round_number,
            _decode_counts(json.loads(counts_a), 4, 'A'),
            _decode_counts(json.loads(counts_b), 2, 'B'),
            decode_fraction(json.loads(clearance)),
            None if cooccurrence is None else decode_fraction(json.loads(cooccurrence)),
        )
