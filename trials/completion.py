import sqlite3

from trials.batches import BatchStore, validate_identity
from trials.ledger import CompletedObservation, ObservationLedger
from trials.offspring import Offspring, ParentKind, validate_offspring, validate_parent_kind
from trials.parents import Inspection, InspectionStore


def initialize_trials(connection: sqlite3.Connection) -> None:
    BatchStore(connection).initialize()
    InspectionStore(connection).initialize()
    ObservationLedger(connection).initialize()


def record(
    connection: sqlite3.Connection,
    batch_id: str,
    inspection_id: str,
    parent_kind: ParentKind,
    offspring: Offspring | list[ParentKind],
) -> CompletedObservation:
    """Record a complete inspection, including an explicitly empty combination."""
    pending = Inspection(
        validate_identity(inspection_id, 'inspection ID'),
        validate_identity(batch_id, 'batch ID'),
        validate_parent_kind(parent_kind),
    )
    combination = validate_offspring(pending.parent_kind, offspring)
    inspections = InspectionStore(connection)
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        existing = inspections.find(pending.inspection_id)
        if existing is None:
            inspections._insert_pending(pending)
        elif existing.batch_id != pending.batch_id or existing.parent_kind != pending.parent_kind:
            raise ValueError('record does not match the registered batch and parent kind')
        completed = inspections.mark_completed(pending.inspection_id)
        observation = ObservationLedger(connection).append(completed, combination)
    return observation
