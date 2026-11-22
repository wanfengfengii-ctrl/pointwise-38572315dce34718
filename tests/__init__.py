from fractions import Fraction
from hashlib import sha256
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from cohort.freeze import freeze
from cohort.revisions import RevisionStore
from demo import initialize_receiver, initialize_source
from models.exchange import encode_edition
from models.law import ClassLaw, FrozenLaw, LawOrigin
from models.publish import fit
from trials.batches import BatchStore
from trials.completion import record


class LabCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='coating-test-')
        self.addCleanup(directory.cleanup)
        self.source_path = Path(directory.name) / 'day.sqlite'
        self.receiver_path = Path(directory.name) / 'night.sqlite'
        self.source = self.connect(self.source_path)
        self.receiver = self.connect(self.receiver_path)
        initialize_source(self.source)
        initialize_receiver(self.receiver)
        BatchStore(self.source).open('shift')

    def connect(self, path):
        connection = sqlite3.connect(path)
        self.addCleanup(connection.close)
        return connection

    def reopen_source(self):
        self.source.close()
        self.source = self.connect(self.source_path)
        initialize_source(self.source)

    def reopen_receiver(self):
        self.receiver.close()
        self.receiver = self.connect(self.receiver_path)
        initialize_receiver(self.receiver)

    def freeze_records(self, rows):
        identities = []
        for identity, kind, offspring in rows:
            record(self.source, 'shift', identity, kind, offspring)
            identities.append(identity)
        revision = RevisionStore(self.source).create_base()
        return freeze(self.source, revision.revision_id, identities)

    def publish_counts(self, prefix, counts_a, counts_b=(0, 1)):
        rows = []
        for kind, combinations, counts in (
            ('A', ((), ('A',), ('B',), ('A', 'B')), counts_a),
            ('B', ((), ('A',)), counts_b),
        ):
            for combination, count in zip(combinations, counts):
                for _ in range(count):
                    rows.append((f'{prefix}-{len(rows):03}', kind, combination))
        return fit(self.source, self.freeze_records(rows).cohort_id)


def worksheet_law(counts_a, counts_b=(0, 1)):
    """Construct a worksheet model without using trial recording or fitting."""
    supports = (((), ('A',), ('B',), ('A', 'B')), ((), ('A',)))
    evidence = repr((counts_a, counts_b)).encode('ascii')
    digest = sha256(evidence).hexdigest()
    classes = tuple(
        ClassLaw(kind, sum(counts), tuple(
            (combination, Fraction(count, sum(counts)))
            for combination, count in zip(combinations, counts)
        ))
        for kind, combinations, counts in zip(('A', 'B'), supports, (counts_a, counts_b))
    )
    return FrozenLaw('worksheet-' + digest, LawOrigin('worksheet-cohort-' + digest, 1, digest), classes)


def worksheet_edition(counts_a, counts_b=(0, 1)):
    return encode_edition(worksheet_law(counts_a, counts_b))
