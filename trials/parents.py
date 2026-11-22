from dataclasses import dataclass, replace
import sqlite3

from trials.batches import BatchStore, validate_identity
from trials.offspring import ParentKind, validate_parent_kind


@dataclass(frozen=True, slots=True)
class Inspection:
    inspection_id: str
    batch_id: str
    parent_kind: ParentKind
    completed: bool = False


class InspectionStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS inspections (
                inspection_id TEXT PRIMARY KEY NOT NULL,
                batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                parent_kind TEXT NOT NULL CHECK (parent_kind IN ('A', 'B')),
                completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1))
            )
        ''')

    def find(self, inspection_id: str) -> Inspection | None:
        inspection_id = validate_identity(inspection_id, 'inspection ID')
        row = self.connection.execute('''
            SELECT inspection_id, batch_id, parent_kind, completed
            FROM inspections WHERE inspection_id = ?
        ''', (inspection_id,)).fetchone()
        if row is None:
            return None
        identity, batch_id, kind, completed = row
        return Inspection(identity, batch_id, kind, bool(completed))

    def require(self, inspection_id: str) -> Inspection:
        inspection = self.find(inspection_id)
        if inspection is None:
            raise KeyError(f'unknown inspection {inspection_id!r}')
        return inspection

    def _insert_pending(self, inspection: Inspection) -> None:
        BatchStore(self.connection).require(inspection.batch_id)
        self.connection.execute('''
            INSERT INTO inspections (inspection_id, batch_id, parent_kind)
            VALUES (?, ?, ?)
        ''', (inspection.inspection_id, inspection.batch_id, inspection.parent_kind))

    def start(self, batch_id: str, inspection_id: str, parent_kind: ParentKind) -> Inspection:
        inspection = Inspection(
            validate_identity(inspection_id, 'inspection ID'),
            validate_identity(batch_id, 'batch ID'),
            validate_parent_kind(parent_kind),
        )
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            if self.find(inspection.inspection_id) is not None:
                raise ValueError(f'inspection ID already registered: {inspection.inspection_id!r}')
            self._insert_pending(inspection)
        return inspection

    def mark_completed(self, inspection_id: str) -> Inspection:
        """Advance an identity inside the caller's observation transaction."""
        if not self.connection.in_transaction:
            raise RuntimeError('completion requires an observation transaction')
        inspection = self.require(inspection_id)
        if inspection.completed:
            raise ValueError(f'inspection already completed: {inspection_id!r}')
        self.connection.execute(
            'UPDATE inspections SET completed = 1 WHERE inspection_id = ?',
            (inspection_id,),
        )
        return replace(inspection, completed=True)
