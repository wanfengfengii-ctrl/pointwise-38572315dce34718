from dataclasses import dataclass
import sqlite3

from trials.batches import validate_identity
from trials.offspring import Offspring, ParentKind, validate_offspring
from trials.parents import Inspection


@dataclass(frozen=True, slots=True)
class CompletedObservation:
    inspection_id: str
    batch_id: str
    parent_kind: ParentKind
    offspring: Offspring
    cursor: int


class ObservationLedger:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS completed_observations (
                cursor INTEGER PRIMARY KEY,
                inspection_id TEXT NOT NULL UNIQUE REFERENCES inspections(inspection_id),
                offspring TEXT NOT NULL CHECK (offspring IN ('', 'A', 'B', 'AB'))
            )
        ''')

    def append(self, inspection: Inspection, offspring: Offspring) -> CompletedObservation:
        """Append the observation in the same transaction as mark_completed."""
        if not self.connection.in_transaction or not inspection.completed:
            raise RuntimeError('observation requires a completed identity in a transaction')
        combination = validate_offspring(inspection.parent_kind, offspring)
        result = self.connection.execute('''
            INSERT INTO completed_observations (inspection_id, offspring) VALUES (?, ?)
        ''', (inspection.inspection_id, ''.join(combination)))
        return CompletedObservation(
            inspection.inspection_id, inspection.batch_id, inspection.parent_kind,
            combination, result.lastrowid,
        )

    def read_at(self, inspection_id: str, watermark: int) -> CompletedObservation | None:
        inspection_id = validate_identity(inspection_id, 'inspection ID')
        row = self.connection.execute('''
            SELECT i.inspection_id, i.batch_id, i.parent_kind, o.offspring, o.cursor
            FROM completed_observations AS o
            JOIN inspections AS i USING (inspection_id)
            WHERE o.inspection_id = ? AND o.cursor <= ?
        ''', (inspection_id, watermark)).fetchone()
        if row is None:
            return None
        identity, batch_id, kind, offspring, cursor = row
        return CompletedObservation(identity, batch_id, kind, tuple(offspring), cursor)

    def high_watermark(self) -> int:
        return self.connection.execute(
            'SELECT COALESCE(MAX(cursor), 0) FROM completed_observations'
        ).fetchone()[0]
