from cohort.amendments import amend
from cohort.freeze import freeze, read_frozen_cohort
from cohort.provenance import verify_provenance
from cohort.revisions import RevisionStore
from tests import LabCase
from trials.completion import record
from trials.parents import InspectionStore


class CohortTests(LabCase):
    def test_incomplete_rejected(self):
        record(self.source, 'shift', 'closed', 'A', ())
        InspectionStore(self.source).start('shift', 'pending', 'B')
        base = RevisionStore(self.source).create_base()
        with self.assertRaisesRegex(ValueError, 'pending'):
            freeze(self.source, base.revision_id, ['closed', 'pending'])
        self.assertEqual(self.source.execute('SELECT COUNT(*) FROM frozen_cohorts').fetchone()[0], 0)
        self.assertEqual(self.source.execute('SELECT COUNT(*) FROM frozen_members').fetchone()[0], 0)

    def test_exact_selection(self):
        first = record(self.source, 'shift', 'a', 'A', ())
        InspectionStore(self.source).start('shift', 'b', 'B')
        old = RevisionStore(self.source).create_base()
        second = record(self.source, 'shift', 'b', 'B', ('A',))
        record(self.source, 'shift', 'unused', 'A', ('B',))
        with self.assertRaisesRegex(ValueError, 'b'):
            freeze(self.source, old.revision_id, ['a', 'b'])
        new = RevisionStore(self.source).create_base()
        with self.assertRaisesRegex(ValueError, 'missing'):
            freeze(self.source, new.revision_id, ['a', 'missing'])
        cohort = freeze(self.source, new.revision_id, ['b', 'a', 'b'])
        self.assertEqual([member.observation for member in cohort.members], [first, second])
        self.assertEqual(cohort.provenance.revision_id, new.revision_id)
        self.assertTrue(verify_provenance(cohort.provenance, reversed(cohort.members)))
        self.assertFalse(verify_provenance(cohort.provenance, cohort.members[:1]))
        self.assertEqual(self.source.execute('SELECT COUNT(*) FROM frozen_cohorts').fetchone()[0], 1)

    def test_revision_selection(self):
        observation = record(self.source, 'shift', 'target', 'A', ())
        base = RevisionStore(self.source).create_base()
        left = amend(self.source, base.revision_id, 'target', ('A',))
        right = amend(self.source, base.revision_id, 'target', ('B',))
        latest = amend(self.source, left.revision_id, 'target', ('B', 'A'))
        original = freeze(self.source, base.revision_id, ['target'])
        original_member = original.members[0]
        self.assertEqual(original_member.observation, observation)
        self.assertEqual(original_member.offspring, ())
        self.assertIsNone(original_member.amendment_revision_id)
        for revision, combination in ((left, ('A',)), (right, ('B',)), (latest, ('A', 'B'))):
            with self.subTest(revision=revision.revision_id):
                cohort = freeze(self.source, revision.revision_id, ['target'])
                self.assertEqual(cohort.members[0].observation, observation)
                self.assertEqual(cohort.members[0].offspring, combination)
                self.assertEqual(cohort.members[0].amendment_revision_id, revision.revision_id)
                self.assertNotEqual(cohort.provenance.digest, original.provenance.digest)
        self.reopen_source()
        self.assertEqual(read_frozen_cohort(self.source, original.cohort_id), original)
        selected_again = freeze(self.source, left.revision_id, ['target'])
        self.assertEqual(selected_again.members[0].offspring, ('A',))

    def test_invalid_amendment_leaves_no_revision(self):
        record(self.source, 'shift', 'b', 'B', ())
        InspectionStore(self.source).start('shift', 'pending', 'A')
        base = RevisionStore(self.source).create_base()
        for identity, combination in (('b', ('B',)), ('pending', ()), ('missing', ())):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                amend(self.source, base.revision_id, identity, combination)
        with self.assertRaises(KeyError):
            amend(self.source, base.revision_id + 1, 'b', ('A',))
        self.assertEqual(RevisionStore(self.source).applied_amendments(base.revision_id), {})
        self.assertEqual(self.source.execute('SELECT COUNT(*) FROM cohort_revisions').fetchone()[0], 1)
