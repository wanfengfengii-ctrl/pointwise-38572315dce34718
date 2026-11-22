import sqlite3

from cohort.freeze import freeze
from cohort.revisions import RevisionStore
from tests import LabCase
from trials.batches import BatchStore
from trials.completion import record
from trials.ledger import ObservationLedger
from trials.parents import InspectionStore


class TrialTests(LabCase):
    def test_zero_offspring_is_observed(self):
        InspectionStore(self.source).start('shift', 'zero', 'A')
        observed = record(self.source, 'shift', 'zero', 'A', ())
        self.assertEqual(observed.offspring, ())
        self.assertGreater(observed.cursor, 0)
        self.reopen_source()
        revision = RevisionStore(self.source).create_base()
        cohort = freeze(self.source, revision.revision_id, ['zero'])
        self.assertEqual(len(cohort.members), 1)
        member = cohort.members[0]
        self.assertEqual(member.observation, observed)
        self.assertEqual(member.offspring, ())
        self.assertIsNone(member.amendment_revision_id)
        self.assertTrue(InspectionStore(self.source).require('zero').completed)

    def test_invalid_combination(self):
        store = InspectionStore(self.source)
        pending = store.start('shift', 'pending-b', 'B')
        for identity in ('new-b', 'pending-b'):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                record(self.source, 'shift', identity, 'B', ('B',))
        self.assertIsNone(store.find('new-b'))
        self.assertEqual(store.require('pending-b'), pending)
        self.assertEqual(BatchStore(self.source).require('shift').batch_id, 'shift')
        self.assertEqual(ObservationLedger(self.source).high_watermark(), 0)

    def test_atomic_record(self):
        store = InspectionStore(self.source)
        pending = store.start('shift', 'pending', 'A')
        BatchStore(self.source).open('another-shift')
        with self.assertRaises(ValueError):
            record(self.source, 'another-shift', 'pending', 'A', ())
        with self.assertRaises(ValueError):
            record(self.source, 'shift', 'pending', 'B', ())
        with self.assertRaises(KeyError):
            record(self.source, 'missing', 'new', 'A', ())
        self.source.execute('''
            CREATE TRIGGER reject_observation BEFORE INSERT ON completed_observations
            BEGIN SELECT RAISE(ABORT, 'ledger rejected observation'); END
        ''')
        for identity in ('new', 'pending'):
            with self.subTest(identity=identity), self.assertRaisesRegex(sqlite3.IntegrityError, 'ledger rejected'):
                record(self.source, 'shift', identity, 'A', ('B', 'A'))
        self.assertIsNone(store.find('new'))
        self.assertEqual(store.require('pending'), pending)
        self.assertEqual(ObservationLedger(self.source).high_watermark(), 0)
        self.source.execute('DROP TRIGGER reject_observation')
        finished = record(self.source, 'shift', 'pending', 'A', ('B', 'A'))
        self.assertEqual(finished.offspring, ('A', 'B'))
        with self.assertRaises(ValueError):
            record(self.source, 'shift', 'pending', 'A', ())
        self.assertEqual(ObservationLedger(self.source).read_at('pending', finished.cursor), finished)
