import sqlite3

from cohort.eligibility import resolve_inspection
from cohort.revisions import CohortRevision, RevisionStore
from trials.offspring import Offspring, ParentKind, validate_offspring


def amend(
    connection: sqlite3.Connection,
    base_revision_id: int,
    inspection_id: str,
    offspring: Offspring | list[ParentKind],
) -> CohortRevision:
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        revisions = RevisionStore(connection)
        base = revisions.require(base_revision_id)
        member = resolve_inspection(connection, base.revision_id, inspection_id)
        replacement = validate_offspring(member.observation.parent_kind, offspring)
        revision = revisions.append_amendment(base, member.observation.inspection_id, replacement)
    return revision
