from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
import json
import sqlite3

from models.exchange import decode_edition, encode_edition
from models.frequency import MissingClassError
from models.publish import fit, read_publication
from reports.issue import issue
from risk.accept import accept, read_accepted_model
from tests import LabCase, worksheet_law


class ModelTests(LabCase):
    def test_joint_frequency(self):
        cohort = self.freeze_records([
            ('z', 'A', ()), ('x', 'A', ('B', 'A')), ('y', 'B', ('A',)),
        ])
        published = fit(self.source, cohort.cohort_id)
        received = decode_edition(published.text)
        self.assertEqual(received, read_publication(self.source, published.law.model_id))
        a, b = received.law.classes
        self.assertEqual((a.sample_size, b.sample_size), (2, 1))
        self.assertEqual(a.frequencies, (
            ((), Fraction(1, 2)), (('A',), Fraction(0)), (('B',), Fraction(0)),
            (('A', 'B'), Fraction(1, 2)),
        ))
        self.assertEqual(b.frequencies, (((), Fraction(0)), (('A',), Fraction(1))))
        self.assertEqual(received.law.origin.cohort_id, cohort.cohort_id)
        self.assertEqual(received.law.origin.cohort_digest, cohort.provenance.digest)
        self.assertEqual(received.law.origin.revision_id, cohort.provenance.revision_id)
        rerun = fit(self.source, cohort.cohort_id)
        self.assertNotEqual(rerun.law.model_id, published.law.model_id)
        self.assertEqual(rerun.law.origin, published.law.origin)
        self.assertEqual(rerun.law.classes, published.law.classes)

    def test_equal_marginals(self):
        editions = (
            self.publish_counts('paired', (4, 0, 0, 12)),
            self.publish_counts('mixed', (1, 3, 3, 9)),
        )
        self.source.close()
        for edition, counts, expected_risks in zip(
            editions, ((4, 0, 0, 12), (1, 3, 3, 9)),
            ((Fraction(1, 3), Fraction(1, 4), Fraction(1, 16)),
             (Fraction(1, 9), Fraction(1, 16), Fraction(7, 256))),
        ):
            model = accept(self.receiver, edition.text)
            a = model.law.for_kind('A')
            self.assertEqual(a.sample_size, 16)
            self.assertEqual(tuple(p for _, p in a.frequencies), tuple(Fraction(n, 16) for n in counts))
            for kind in ('A', 'B'):
                self.assertEqual(sum(mass for children, mass in a.frequencies if kind in children), Fraction(3, 4))
            first = issue(self.receiver, model.accepted_id, 'A', 1).result
            second = issue(self.receiver, model.accepted_id, 'A', 2).result
            self.assertEqual((first.clearance, first.conditional_cooccurrence,
                              second.conditional_cooccurrence), expected_risks)
            self.assertEqual(second.clearance, first.clearance)

    def test_missing_class(self):
        previous = self.publish_counts('valid', (1, 0, 0, 1))
        for present in ('A', 'B'):
            with self.subTest(present=present):
                cohort = self.freeze_records([(f'only-{present}', present, ())])
                with self.assertRaises(MissingClassError):
                    fit(self.source, cohort.cohort_id)
        stored = self.source.execute('SELECT model_id FROM published_models').fetchall()
        self.assertEqual(stored, [(previous.law.model_id,)])
        self.assertEqual(read_publication(self.source, previous.law.model_id), previous)

    def test_mixed_model(self):
        left = self.publish_counts('left', (1, 0, 0, 3))
        right = self.publish_counts('right', (1, 0, 0, 3))
        self.assertEqual(left.law.classes, right.law.classes)
        self.assertNotEqual(left.law.origin, right.law.origin)
        left_model = accept(self.receiver, left.text)
        right_model = accept(self.receiver, right.text)
        mixed = json.loads(left.text)
        mixed['origin'] = json.loads(right.text)['origin']
        with self.assertRaisesRegex(ValueError, 'origin'):
            accept(self.receiver, json.dumps(mixed))
        self.assertEqual(read_accepted_model(self.receiver, left_model.accepted_id), left_model)
        self.assertEqual(read_accepted_model(self.receiver, right_model.accepted_id), right_model)
        self.assertEqual(self.receiver.execute('SELECT COUNT(*) FROM accepted_models').fetchone()[0], 2)

    def test_changed_body_and_invalid_counts_are_rejected(self):
        edition = self.publish_counts('publication', (1, 0, 0, 3))
        packet = json.loads(edition.text)
        packet['body']['classes'][0]['sample_size'] = 3
        with self.assertRaisesRegex(ValueError, 'digest'):
            accept(self.receiver, json.dumps(packet))
        canonical_body = json.dumps(packet['body'], sort_keys=True, separators=(',', ':'))
        packet['body_sha256'] = sha256(canonical_body.encode('utf-8')).hexdigest()
        with self.assertRaisesRegex(ValueError, 'whole observation count'):
            accept(self.receiver, json.dumps(packet))
        duplicate = edition.text.replace('"version":1', '"version":1,"version":1')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            accept(self.receiver, duplicate)
        self.assertEqual(self.receiver.execute('SELECT COUNT(*) FROM accepted_models').fetchone()[0], 0)

    def test_invalid_law_has_no_edition(self):
        law = worksheet_law((1, 0, 0, 3))
        a, b = law.classes
        wrong_total = replace(a, frequencies=(
            ((), Fraction(1, 4)), (('A',), Fraction(0)),
            (('B',), Fraction(0)), (('A', 'B'), Fraction(1, 2)),
        ))
        wrong_support = replace(b, frequencies=(((), Fraction(0)), (('B',), Fraction(1))))
        for rows, message in (((wrong_total, b), 'sum to one'), ((a, wrong_support), 'support')):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                encode_edition(replace(law, classes=rows))

    def test_failed_publication_leaves_original(self):
        original = self.publish_counts('original', (1, 0, 0, 3))
        self.source.execute('''
            CREATE TRIGGER reject_publication BEFORE INSERT ON published_models
            BEGIN SELECT RAISE(ABORT, 'publication rejected'); END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'publication rejected'):
            fit(self.source, original.law.origin.cohort_id)
        self.reopen_source()
        self.assertEqual(read_publication(self.source, original.law.model_id), original)
        self.assertEqual(self.source.execute('SELECT COUNT(*) FROM published_models').fetchone()[0], 1)
