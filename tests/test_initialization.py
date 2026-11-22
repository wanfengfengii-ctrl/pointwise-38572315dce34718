from fractions import Fraction

from cohort.amendments import amend
from cohort.freeze import freeze, read_frozen_cohort
from cohort.revisions import RevisionStore
from demo import initialize_receiver, initialize_source
from models.publish import fit, read_publication
from reports.history import read
from reports.issue import issue
from risk.accept import accept, read_accepted_model
from tests import LabCase
from trials.batches import BatchStore
from trials.completion import record
from trials.ledger import ObservationLedger
from trials.parents import InspectionStore


class InitializationTests(LabCase):
    def test_first_initialization_has_no_sample_data(self):
        source = self.connect(self.source_path.with_name('empty-day.sqlite'))
        receiver = self.connect(self.receiver_path.with_name('empty-night.sqlite'))
        initialize_source(source)
        initialize_receiver(receiver)
        self.assertEqual(source.execute('SELECT COUNT(*) FROM batches').fetchone()[0], 0)
        self.assertEqual(ObservationLedger(source).high_watermark(), 0)
        self.assertEqual(receiver.execute('SELECT COUNT(*) FROM accepted_models').fetchone()[0], 0)
        self.assertEqual(receiver.execute('SELECT COUNT(*) FROM signed_reports').fetchone()[0], 0)
        self.assertEqual(source.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        self.assertEqual(receiver.execute('PRAGMA foreign_keys').fetchone()[0], 1)

    def test_repeated_initialization_preserves_user_facts(self):
        BatchStore(self.source).open('custom')
        zero = record(self.source, 'custom', 'custom-a', 'A', ())
        record(self.source, 'custom', 'custom-b', 'B', ('A',))
        pending = InspectionStore(self.source).start('custom', 'in-progress', 'B')
        base = RevisionStore(self.source).create_base()
        revision = amend(self.source, base.revision_id, 'custom-a', ('A',))
        frozen = freeze(self.source, revision.revision_id, ['custom-a', 'custom-b'])
        edition = fit(self.source, frozen.cohort_id)
        accepted = accept(self.receiver, edition.text)
        signed = issue(self.receiver, accepted.accepted_id, 'A', 1)
        self.assertEqual(signed.result.clearance, Fraction(0))
        self.assertIsNone(signed.result.conditional_cooccurrence)
        initialize_source(self.source)
        initialize_receiver(self.receiver)
        self.reopen_source()
        self.reopen_receiver()
        self.assertEqual(BatchStore(self.source).require('custom').batch_id, 'custom')
        self.assertEqual(InspectionStore(self.source).require('in-progress'), pending)
        self.assertEqual(ObservationLedger(self.source).read_at('custom-a', base.watermark), zero)
        restored = read_frozen_cohort(self.source, frozen.cohort_id)
        self.assertEqual(restored, frozen)
        self.assertEqual(restored.members[0].offspring, ('A',))
        self.assertEqual(restored.members[0].amendment_revision_id, revision.revision_id)
        self.assertEqual(read_publication(self.source, edition.law.model_id), edition)
        self.assertEqual(read_accepted_model(self.receiver, accepted.accepted_id), accepted)
        self.assertEqual(read(self.receiver, signed.report_id), signed)
        self.assertEqual(self.source.execute('SELECT COUNT(*) FROM completed_observations').fetchone()[0], 2)
        self.assertEqual(self.receiver.execute('SELECT COUNT(*) FROM signed_reports').fetchone()[0], 1)
