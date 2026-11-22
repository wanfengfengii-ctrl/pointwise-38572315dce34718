from dataclasses import dataclass
import sqlite3


def validate_identity(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError(f'{label} must be nonblank text without NUL')
    return value


@dataclass(frozen=True, slots=True)
class Batch:
    batch_id: str


class BatchStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS batches (
                batch_id TEXT PRIMARY KEY NOT NULL
            )
        ''')

    def open(self, batch_id: str) -> Batch:
        batch = Batch(validate_identity(batch_id, 'batch ID'))
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            self.connection.execute(
                'INSERT INTO batches (batch_id) VALUES (?) ON CONFLICT(batch_id) DO NOTHING',
                (batch.batch_id,),
            )
        return batch

    def require(self, batch_id: str) -> Batch:
        batch_id = validate_identity(batch_id, 'batch ID')
        row = self.connection.execute(
            'SELECT batch_id FROM batches WHERE batch_id = ?', (batch_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f'unknown batch {batch_id!r}')
        return Batch(row[0])
