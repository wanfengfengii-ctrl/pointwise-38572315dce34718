import sqlite3
from uuid import uuid4

from cohort.freeze import read_frozen_cohort
from models.exchange import ModelEdition, decode_edition, encode_edition
from models.frequency import count_frequencies
from models.law import FrozenLaw, LawOrigin
from trials.batches import validate_identity


def initialize_models(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS published_models (
            model_id TEXT PRIMARY KEY NOT NULL,
            cohort_id TEXT NOT NULL REFERENCES frozen_cohorts(cohort_id),
            edition TEXT NOT NULL
        )
    ''')


def fit(connection: sqlite3.Connection, cohort_id: str) -> ModelEdition:
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        cohort = read_frozen_cohort(connection, cohort_id)
        classes = count_frequencies(cohort)
        origin = LawOrigin(cohort.cohort_id, cohort.provenance.revision_id, cohort.provenance.digest)
        law = FrozenLaw(uuid4().hex, origin, classes)
        text = encode_edition(law)
        connection.execute('''
            INSERT INTO published_models (model_id, cohort_id, edition) VALUES (?, ?, ?)
        ''', (law.model_id, cohort.cohort_id, text))
    return ModelEdition(law, text)


def read_publication(connection: sqlite3.Connection, model_id: str) -> ModelEdition:
    model_id = validate_identity(model_id, 'model ID')
    row = connection.execute(
        'SELECT cohort_id, edition FROM published_models WHERE model_id = ?', (model_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f'unknown published model {model_id!r}')
    edition = decode_edition(row[1])
    if edition.law.model_id != model_id or edition.law.origin.cohort_id != row[0]:
        raise ValueError('stored edition does not match its publication identity')
    return edition
