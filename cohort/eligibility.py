from collections.abc import Iterable
from dataclasses import dataclass
import sqlite3

from cohort.revisions import Amendment, CohortRevision, RevisionStore
from trials.batches import validate_identity
from trials.ledger import CompletedObservation, ObservationLedger
from trials.offspring import Offspring


@dataclass(frozen=True, slots=True)
class EffectiveInspection:
    observation: CompletedObservation
    offspring: Offspring
    amendment_revision_id: int | None = None


def _resolve(
    ledger: ObservationLedger,
    revision: CohortRevision,
    inspection_id: str,
    amendment: Amendment | None,
) -> EffectiveInspection:
    observation = ledger.read_at(inspection_id, revision.watermark)
    if observation is None:
        raise ValueError(f'inspection {inspection_id!r} is not complete in revision {revision.revision_id}')
    if amendment is None:
        return EffectiveInspection(observation, observation.offspring)
    return EffectiveInspection(observation, amendment.offspring, amendment.revision_id)


def resolve_inspection(
    connection: sqlite3.Connection, revision_id: int, inspection_id: str
) -> EffectiveInspection:
    return select_eligible(connection, revision_id, (inspection_id,))[0]


def select_eligible(
    connection: sqlite3.Connection, revision_id: int, inspection_ids: Iterable[str]
) -> tuple[EffectiveInspection, ...]:
    if isinstance(inspection_ids, (str, bytes)):
        raise ValueError('inspection selection must be a collection of IDs')
    identities = sorted({validate_identity(identity, 'inspection ID') for identity in inspection_ids})
    revisions = RevisionStore(connection)
    revision = revisions.require(revision_id)
    amendments = revisions.applied_amendments(revision_id)
    ledger = ObservationLedger(connection)
    return tuple(_resolve(ledger, revision, identity, amendments.get(identity)) for identity in identities)
