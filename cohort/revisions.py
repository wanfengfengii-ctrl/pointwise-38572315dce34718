from dataclasses import dataclass
import sqlite3

from trials.ledger import ObservationLedger
from trials.offspring import Offspring


@dataclass(frozen=True, slots=True)
class CohortRevision:
    revision_id: int
    watermark: int
    base_revision_id: int | None = None


@dataclass(frozen=True, slots=True)
class Amendment:
    revision_id: int
    inspection_id: str
    offspring: Offspring


class RevisionStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS cohort_revisions (
                revision_id INTEGER PRIMARY KEY,
                watermark INTEGER NOT NULL CHECK (watermark >= 0),
                base_revision_id INTEGER REFERENCES cohort_revisions(revision_id),
                inspection_id TEXT REFERENCES completed_observations(inspection_id),
                replacement TEXT CHECK (replacement IN ('', 'A', 'B', 'AB')),
                CHECK (
                    (base_revision_id IS NULL AND inspection_id IS NULL AND replacement IS NULL)
                    OR
                    (base_revision_id IS NOT NULL AND inspection_id IS NOT NULL AND replacement IS NOT NULL)
                )
            )
        ''')

    def create_base(self) -> CohortRevision:
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            watermark = ObservationLedger(self.connection).high_watermark()
            result = self.connection.execute(
                'INSERT INTO cohort_revisions (watermark) VALUES (?)', (watermark,)
            )
            revision = CohortRevision(result.lastrowid, watermark)
        return revision

    def require(self, revision_id: int) -> CohortRevision:
        if type(revision_id) is not int or not 0 < revision_id < 2**63:
            raise KeyError(f'unknown revision {revision_id!r}')
        row = self.connection.execute('''
            SELECT revision_id, watermark, base_revision_id
            FROM cohort_revisions WHERE revision_id = ?
        ''', (revision_id,)).fetchone()
        if row is None:
            raise KeyError(f'unknown revision {revision_id!r}')
        return CohortRevision(*row)

    def append_amendment(
        self, base: CohortRevision, inspection_id: str, offspring: Offspring
    ) -> CohortRevision:
        """Persist the correction validated by amend in its write transaction."""
        if not self.connection.in_transaction:
            raise RuntimeError('amendment requires a revision transaction')
        result = self.connection.execute('''
            INSERT INTO cohort_revisions (watermark, base_revision_id, inspection_id, replacement)
            VALUES (?, ?, ?, ?)
        ''', (base.watermark, base.revision_id, inspection_id, ''.join(offspring)))
        return CohortRevision(result.lastrowid, base.watermark, base.revision_id)

    def applied_amendments(self, revision_id: int) -> dict[str, Amendment]:
        self.require(revision_id)
        rows = self.connection.execute('''
            WITH RECURSIVE lineage (revision_id, base_revision_id, inspection_id, replacement, depth) AS (
                SELECT revision_id, base_revision_id, inspection_id, replacement, 0
                FROM cohort_revisions WHERE revision_id = ?
                UNION ALL
                SELECT parent.revision_id, parent.base_revision_id, parent.inspection_id,
                       parent.replacement, lineage.depth + 1
                FROM lineage JOIN cohort_revisions AS parent
                ON parent.revision_id = lineage.base_revision_id
            )
            SELECT revision_id, inspection_id, replacement FROM lineage
            WHERE inspection_id IS NOT NULL ORDER BY depth DESC
        ''', (revision_id,))
        latest = {}
        for amendment_id, inspection_id, replacement in rows:
            latest[inspection_id] = Amendment(amendment_id, inspection_id, tuple(replacement))
        return latest
