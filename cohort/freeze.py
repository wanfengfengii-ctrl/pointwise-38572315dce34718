from collections.abc import Iterable
from dataclasses import dataclass
import sqlite3
from uuid import uuid4

from cohort.eligibility import EffectiveInspection, select_eligible
from cohort.provenance import CohortProvenance, build_provenance, verify_provenance
from cohort.revisions import RevisionStore
from trials.batches import validate_identity
from trials.ledger import CompletedObservation


@dataclass(frozen=True, slots=True)
class FrozenCohort:
    provenance: CohortProvenance
    members: tuple[EffectiveInspection, ...]

    @property
    def cohort_id(self) -> str:
        return self.provenance.cohort_id


def initialize_cohorts(connection: sqlite3.Connection) -> None:
    RevisionStore(connection).initialize()
    connection.execute('''
        CREATE TABLE IF NOT EXISTS frozen_cohorts (
            cohort_id TEXT PRIMARY KEY NOT NULL,
            revision_id INTEGER NOT NULL REFERENCES cohort_revisions(revision_id),
            digest TEXT NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS frozen_members (
            cohort_id TEXT NOT NULL REFERENCES frozen_cohorts(cohort_id),
            inspection_id TEXT NOT NULL REFERENCES inspections(inspection_id),
            batch_id TEXT NOT NULL REFERENCES batches(batch_id),
            parent_kind TEXT NOT NULL,
            observation_cursor INTEGER NOT NULL REFERENCES completed_observations(cursor),
            original TEXT NOT NULL,
            effective TEXT NOT NULL,
            amendment_revision_id INTEGER REFERENCES cohort_revisions(revision_id),
            PRIMARY KEY (cohort_id, inspection_id)
        )
    ''')


def freeze(
    connection: sqlite3.Connection, revision_id: int, inspection_ids: Iterable[str]
) -> FrozenCohort:
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        members = select_eligible(connection, revision_id, inspection_ids)
        cohort_id = uuid4().hex
        provenance = build_provenance(cohort_id, revision_id, members)
        connection.execute('''
            INSERT INTO frozen_cohorts (cohort_id, revision_id, digest) VALUES (?, ?, ?)
        ''', (cohort_id, revision_id, provenance.digest))
        connection.executemany('''
            INSERT INTO frozen_members (
                cohort_id, inspection_id, batch_id, parent_kind, observation_cursor,
                original, effective, amendment_revision_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            (cohort_id, member.observation.inspection_id, member.observation.batch_id,
             member.observation.parent_kind, member.observation.cursor,
             ''.join(member.observation.offspring), ''.join(member.offspring), member.amendment_revision_id)
            for member in members
        ))
    return FrozenCohort(provenance, members)


def read_frozen_cohort(connection: sqlite3.Connection, cohort_id: str) -> FrozenCohort:
    cohort_id = validate_identity(cohort_id, 'cohort ID')
    row = connection.execute('''
        SELECT cohort_id, revision_id, digest FROM frozen_cohorts WHERE cohort_id = ?
    ''', (cohort_id,)).fetchone()
    if row is None:
        raise KeyError(f'unknown frozen cohort {cohort_id!r}')
    provenance = CohortProvenance(*row)
    rows = connection.execute('''
        SELECT inspection_id, batch_id, parent_kind, observation_cursor,
               original, effective, amendment_revision_id
        FROM frozen_members WHERE cohort_id = ? ORDER BY inspection_id
    ''', (cohort_id,))
    members = tuple(
        EffectiveInspection(
            CompletedObservation(identity, batch, kind, tuple(original), cursor),
            tuple(effective), amendment,
        )
        for identity, batch, kind, cursor, original, effective, amendment in rows
    )
    if not verify_provenance(provenance, members):
        raise ValueError('frozen member facts do not match their provenance')
    return FrozenCohort(provenance, members)
