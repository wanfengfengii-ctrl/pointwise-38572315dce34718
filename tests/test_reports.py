from fractions import Fraction
import json
import sqlite3

from cohort.amendments import amend
from cohort.freeze import freeze, read_frozen_cohort
from models.publish import fit
from reports.compare import compare_reports
from reports.export import export_report
from reports.history import ReportNotFoundError, read
from reports.issue import issue
from risk.accept import accept
from risk.clearance import ClearanceProbabilities, population_clearance
from risk.rounds import round_distribution
from tests import LabCase, worksheet_edition, worksheet_law


class ReportTests(LabCase):
    def test_clearance_after_disconnect(self):
        edition = self.publish_counts('day', (1, 0, 0, 3))
        model = accept(self.receiver, edition.text)
        self.source.close()
        self.reopen_receiver()
        results = [issue(self.receiver, model.accepted_id, 'A', round_number)
                   for round_number in (1, 2)]
        self.assertEqual([report.result.clearance for report in results], [Fraction(1, 3)] * 2)
        self.assertEqual([report.result.conditional_cooccurrence for report in results],
                         [Fraction(1, 4), Fraction(1, 16)])
        for report in results:
            self.assertEqual(report.result.origin, edition.law.origin)
            self.assertEqual(report.result.model_id, edition.law.model_id)
            self.assertEqual(read(self.receiver, report.report_id), report)

    def test_independent_edition(self):
        model = accept(self.receiver, worksheet_edition((1, 0, 0, 3)))
        self.source.close()
        expected = (('A', 1, Fraction(1, 4)), ('A', 2, Fraction(1, 16)),
                    ('B', 1, Fraction(0)), ('B', 2, Fraction(1, 4)))
        for kind, round_number, cooccurrence in expected:
            with self.subTest(kind=kind, round=round_number):
                result = issue(self.receiver, model.accepted_id, kind, round_number).result
                self.assertEqual(result.clearance, Fraction(1, 3))
                self.assertEqual(result.conditional_cooccurrence, cooccurrence)

    def test_conditional_rounds(self):
        model = accept(self.receiver, worksheet_edition((1, 0, 1, 6), (1, 3)))
        first_a = issue(self.receiver, model.accepted_id, 'A', 1).result
        second_b = issue(self.receiver, model.accepted_id, 'B', 2).result
        self.assertEqual((first_a.clearance, first_a.conditional_cooccurrence), (Fraction(5, 18), Fraction(11, 32)))
        self.assertEqual((second_b.clearance, second_b.conditional_cooccurrence), (Fraction(11, 24), Fraction(5, 32)))
        law = worksheet_law((1, 0, 0, 3))
        self.assertEqual(round_distribution(law, 'A', 2), {
            (0, 0): Fraction(1, 4), (1, 0): Fraction(3, 16), (2, 1): Fraction(9, 16),
        })
        actual = round_distribution(worksheet_law((0, 0, 0, 1)), 'A', 6)
        self.assertEqual(actual, {(13, 8): Fraction(1)})
        self.assertEqual(population_clearance(ClearanceProbabilities(Fraction(0), Fraction(0)), (0, 0)), 1)

    def test_extinction_branches(self):
        cases = (
            ((0, 0, 0, 1), (0, 1), 'A', Fraction(0), None),
            ((0, 0, 1, 0), (0, 1), 'B', Fraction(0), None),
            ((0, 1, 0, 0), (1, 0), 'A', Fraction(0), None),
            ((0, 1, 0, 0), (1, 0), 'B', Fraction(1), Fraction(0)),
            ((1, 0, 0, 0), (0, 1), 'A', Fraction(1), Fraction(0)),
            ((1, 0, 0, 1), (0, 1), 'A', Fraction(1), Fraction(1, 2)),
        )
        for a, b, kind, clearance, cooccurrence in cases:
            with self.subTest(a=a, b=b, initial=kind):
                model = accept(self.receiver, worksheet_edition(a, b))
                report = issue(self.receiver, model.accepted_id, kind, 1)
                self.assertEqual(report.result.clearance, clearance)
                self.assertEqual(report.result.conditional_cooccurrence, cooccurrence)
                if cooccurrence == 0:
                    self.assertIsInstance(report.result.conditional_cooccurrence, Fraction)
                exported = json.loads(export_report(self.receiver, report.report_id))
                if cooccurrence is None:
                    self.assertIsNone(exported['conditional_cooccurrence'])
                elif cooccurrence == 0:
                    self.assertEqual(exported['conditional_cooccurrence'], [0, 1])

    def test_request_bounds(self):
        model = accept(self.receiver, worksheet_edition((1, 0, 0, 3)))
        for bad_round in (0, 7, 1.0, True, '2'):
            with self.subTest(round=bad_round), self.assertRaises(ValueError):
                issue(self.receiver, model.accepted_id, 'A', bad_round)
        with self.assertRaises(ValueError):
            issue(self.receiver, model.accepted_id, 'C', 1)
        with self.assertRaises(KeyError):
            issue(self.receiver, model.accepted_id + 1, 'A', 1)
        self.assertEqual(self.receiver.execute('SELECT COUNT(*) FROM signed_reports').fetchone()[0], 0)
        self.assertEqual(issue(self.receiver, model.accepted_id, 'A', 6).result.round_number, 6)

    def test_history_after_amendment(self):
        edition = self.publish_counts('old', (1, 0, 0, 3))
        before = accept(self.receiver, edition.text)
        original = issue(self.receiver, before.accepted_id, 'A', 1)
        original_export = export_report(self.receiver, original.report_id)
        cohort = read_frozen_cohort(self.source, edition.law.origin.cohort_id)
        target = next(member for member in cohort.members if member.offspring == ('A', 'B'))
        correction = amend(self.source, cohort.provenance.revision_id, target.observation.inspection_id, ())
        revised = freeze(self.source, correction.revision_id,
                         [member.observation.inspection_id for member in cohort.members])
        changed = fit(self.source, revised.cohort_id)
        self.source.close()
        self.reopen_receiver()
        new_model = accept(self.receiver, changed.text)
        after = issue(self.receiver, new_model.accepted_id, 'A', 1)
        self.assertEqual((after.result.clearance, after.result.conditional_cooccurrence),
                         (Fraction(1), Fraction(1, 2)))
        self.assertEqual(read(self.receiver, original.report_id), original)
        self.assertEqual(export_report(self.receiver, original.report_id), original_export)
        old_payload = json.loads(original_export)
        self.assertEqual(old_payload['clearance'], [1, 3])
        self.assertEqual(old_payload['conditional_cooccurrence'], [1, 4])
        self.assertEqual(old_payload['origin']['cohort_digest'], cohort.provenance.digest)
        self.assertNotEqual(after.result.model_id, original.result.model_id)
        self.assertNotEqual(after.result.origin, original.result.origin)
        with self.assertRaises(ReportNotFoundError):
            read(self.receiver, after.report_id + 1)

    def test_comparison(self):
        before = accept(self.receiver, worksheet_edition((1, 0, 0, 3)))
        after = accept(self.receiver, worksheet_edition((1, 0, 0, 1)))
        certain_survival = accept(self.receiver, worksheet_edition((0, 0, 0, 1)))
        r1 = issue(self.receiver, before.accepted_id, 'A', 1)
        r2 = issue(self.receiver, after.accepted_id, 'A', 1)
        different_round = issue(self.receiver, after.accepted_id, 'A', 2)
        different_initial = issue(self.receiver, after.accepted_id, 'B', 1)
        undefined = issue(self.receiver, certain_survival.accepted_id, 'A', 1)
        comparison = compare_reports(self.receiver, r1.report_id, r2.report_id)
        self.assertEqual((comparison.older, comparison.newer), (r1, r2))
        self.assertEqual((comparison.clearance_delta, comparison.cooccurrence_delta),
                         (Fraction(2, 3), Fraction(1, 4)))
        for other in (different_round, different_initial):
            comparison = compare_reports(self.receiver, r1.report_id, other.report_id)
            self.assertIsNone(comparison.clearance_delta)
            self.assertIsNone(comparison.cooccurrence_delta)
            self.assertEqual(comparison.newer, other)
        comparison = compare_reports(self.receiver, undefined.report_id, r2.report_id)
        self.assertEqual(comparison.clearance_delta, Fraction(1))
        self.assertIsNone(comparison.cooccurrence_delta)

    def test_failed_commit(self):
        model = accept(self.receiver, worksheet_edition((1, 0, 0, 3)))
        original = issue(self.receiver, model.accepted_id, 'A', 1)
        self.receiver.executescript('''
            CREATE TABLE fixture_commit_gate (key INTEGER PRIMARY KEY);
            CREATE TABLE fixture_commit_check (
                key INTEGER REFERENCES fixture_commit_gate(key) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER fixture_report_commit AFTER INSERT ON signed_reports
            BEGIN INSERT INTO fixture_commit_check VALUES (1); END;
        ''')
        receipt = None
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
            receipt = issue(self.receiver, model.accepted_id, 'A', 2)
        self.assertIsNone(receipt)
        self.assertFalse(self.receiver.in_transaction)
        self.reopen_receiver()
        rows = self.receiver.execute('SELECT report_id FROM signed_reports ORDER BY report_id').fetchall()
        self.assertEqual(rows, [(original.report_id,)])
        self.assertEqual(self.receiver.execute('SELECT COUNT(*) FROM fixture_commit_check').fetchone()[0], 0)
        self.assertEqual(read(self.receiver, original.report_id), original)
        with self.assertRaises(ReportNotFoundError):
            read(self.receiver, original.report_id + 1)
        self.receiver.execute('DROP TRIGGER fixture_report_commit')
        retry = issue(self.receiver, model.accepted_id, 'A', 2)
        self.assertEqual(retry.result.conditional_cooccurrence, Fraction(1, 16))
