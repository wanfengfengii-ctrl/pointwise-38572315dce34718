from dataclasses import dataclass
import sqlite3
from uuid import uuid4

from models.exchange import decode_edition
from models.law import FrozenLaw
from models.pool import PoolDocument, decode_pool_document
from trials.batches import validate_identity


@dataclass(frozen=True, slots=True)
class AcceptedModel:
    accepted_id: int
    law: FrozenLaw


def initialize_risk(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS accepted_models (
            accepted_id INTEGER PRIMARY KEY,
            model_id TEXT NOT NULL,
            edition TEXT NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS accepted_pools (
            accepted_id TEXT PRIMARY KEY NOT NULL,
            document TEXT NOT NULL
        )
    ''')


def accept(connection: sqlite3.Connection, edition: str) -> AcceptedModel:
    parsed = decode_edition(edition)
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        result = connection.execute('''
            INSERT INTO accepted_models (model_id, edition) VALUES (?, ?)
        ''', (parsed.law.model_id, parsed.text))
        accepted_id = result.lastrowid
    return AcceptedModel(accepted_id, parsed.law)


def read_accepted_model(connection: sqlite3.Connection, accepted_id: int) -> AcceptedModel:
    if type(accepted_id) is not int or not 0 < accepted_id < 2**63:
        raise KeyError(f'unknown accepted model {accepted_id!r}')
    row = connection.execute(
        'SELECT model_id, edition FROM accepted_models WHERE accepted_id = ?', (accepted_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f'unknown accepted model {accepted_id!r}')
    law = decode_edition(row[1]).law
    if law.model_id != row[0]:
        raise ValueError('stored edition does not match its accepted model identity')
    return AcceptedModel(accepted_id, law)


def accept_pool(connection: sqlite3.Connection, text: str) -> str:
    """Validate and fix a V2 pooled document, returning its acceptance number."""
    document = decode_pool_document(text)
    accepted_id = uuid4().hex
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        connection.execute(
            'INSERT INTO accepted_pools (accepted_id, document) VALUES (?, ?)',
            (accepted_id, document.text),
        )
    return accepted_id


def read_accepted_pool(connection: sqlite3.Connection, accepted_id: str) -> PoolDocument:
    accepted_id = validate_identity(accepted_id, 'accepted ID')
    row = connection.execute(
        'SELECT document FROM accepted_pools WHERE accepted_id = ?', (accepted_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f'unknown accepted pool {accepted_id!r}')
    return decode_pool_document(row[0])
