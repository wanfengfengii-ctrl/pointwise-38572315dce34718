import copy
from fractions import Fraction
from hashlib import sha256
import json
import sqlite3

from cohort.amendments import amend
from cohort.freeze import freeze, read_frozen_cohort
from cohort.revisions import RevisionStore
from demo import initialize_receiver, run_pool_shift
from models.frequency import MissingClassError, count_frequencies
from models.pool import decode_pool_document
from models.publish import fit, publish_pool
from pool_fixture import load_pool_sample
from reports.history import read_pool_report
from reports.issue import issue_pool
from risk.accept import accept, accept_pool
from tests import LabCase
from trials.completion import record


def remake_document(body):
    canonical = json.dumps(body, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=True, allow_nan=False)
    return json.dumps({
        'version': 2,
        'body': body,
        'body_sha256': sha256(canonical.encode('utf-8')).hexdigest(),
    }, sort_keys=True, separators=(',', ':'))


class PoolTests(LabCase):
    def setUp(self):
        super().setUp()
        self.samples = load_pool_sample(self.source)

    def publish(self, name):
        cohorts = self.samples[name]
        ids = [cohort.cohort_id for cohort in cohorts]
        return ids, publish_pool(self.source, ids)

    def accept_named(self, name):
        ids, text = self.publish(name)
        return ids, accept_pool(self.receiver, text)

    def test_fixture_single_cohort_marginals(self):
        common = tuple(map(count_frequencies, self.samples['common_three']))
        paired = tuple(map(count_frequencies, self.samples['separate_pairs']))
        self.assertEqual(common, paired)
        self.assertEqual([a.sample_size for a, _ in common], [3, 2, 2])
        self.assertEqual([str(a.probability(('A', 'B'))) for a, _ in common], ['1/3', '0', '0'])
        old, changed, _ = self.samples['swapped']
        self.assertEqual(count_frequencies(old), count_frequencies(changed))
        self.assertNotEqual(old.provenance, changed.provenance)

    def test_publish_request_validation(self):
        first, second = self.samples['split']
        with self.assertRaises(ValueError):
            publish_pool(self.source, [first.cohort_id])
        with self.assertRaises(ValueError):
            publish_pool(self.source, [first.cohort_id, first.cohort_id])
        with self.assertRaises(ValueError):
            publish_pool(self.source, first.cohort_id)
        with self.assertRaises(ValueError):
            publish_pool(self.source, [first.cohort_id, 7])
        with self.assertRaises(ValueError):
            publish_pool(self.source, [first.cohort_id, '  '])
        with self.assertRaises(KeyError):
            publish_pool(self.source, [first.cohort_id, 'unknown-cohort'])
        # single-class cohorts and in-package divergence are both allowed
        text = publish_pool(self.source, (second.cohort_id, first.cohort_id))
        self.assertIsInstance(text, str)
        self.assertIsInstance(self.publish('swapped')[1], str)
        repeat = publish_pool(self.source, [first.cohort_id, second.cohort_id])
        self.assertEqual(repeat, text)

    def test_document_format_and_privacy(self):
        ids, text = self.publish('swapped')
        packet = json.loads(text)
        self.assertEqual(set(packet), {'version', 'body', 'body_sha256'})
        self.assertEqual(packet['version'], 2)
        canonical = json.dumps(packet['body'], sort_keys=True, separators=(',', ':'),
                               ensure_ascii=True, allow_nan=False)
        self.assertEqual(packet['body_sha256'], sha256(canonical.encode('utf-8')).hexdigest())
        self.assertEqual(set(packet['body']), {'origins', 'evidence'})
        origins = packet['body']['origins']
        self.assertEqual([origin['cohort_id'] for origin in origins], sorted(ids))
        self.assertEqual(len({origin['cohort_id'] for origin in origins}), len(ids))
        self.assertNotIn('pool-inspection', text)
        self.assertNotIn('pool-day', text)
        document = decode_pool_document(text)
        self.assertEqual(document.text, text)
        self.assertEqual([origin.cohort_id for origin in document.origins], sorted(ids))
        self.assertEqual({origin.revision_id for origin in document.origins},
                         {cohort.provenance.revision_id for cohort in self.samples['swapped']})

    def test_accept_and_version_separation(self):
        ids, text = self.publish('common_three')
        accepted_id = accept_pool(self.receiver, text)
        self.assertIsInstance(accepted_id, str)
        self.assertNotEqual(accepted_id, accept_pool(self.receiver, text))
        edition = fit(self.source, self.samples['common_three'][0].cohort_id)
        with self.assertRaises(ValueError):
            accept_pool(self.receiver, edition.text)
        with self.assertRaises(ValueError):
            accept(self.receiver, text)
        with self.assertRaises(ValueError):
            accept_pool(self.receiver, 2)
        self.assertEqual(self.receiver.execute('SELECT COUNT(*) FROM accepted_models').fetchone()[0], 0)

    def test_accept_rejects_bad_documents(self):
        ids, text = self.publish('common_three')
        tampered = json.loads(text)
        tampered['body']['evidence']['cells'][0]['count'] += 1
        with self.assertRaisesRegex(ValueError, 'digest'):
            accept_pool(self.receiver, json.dumps(tampered))
        duplicate = text.replace('"version":2', '"version":2,"version":2', 1)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            accept_pool(self.receiver, duplicate)
        body = json.loads(text)['body']
        for version in (1, 3, '2', True):
            with self.subTest(version=version):
                packet = json.loads(remake_document(body))
                packet['version'] = version
                with self.assertRaisesRegex(ValueError, 'version'):
                    accept_pool(self.receiver, json.dumps(packet))
        self.assertEqual(self.receiver.execute('SELECT COUNT(*) FROM accepted_pools').fetchone()[0], 0)

    def test_accept_rejects_inconsistent_evidence(self):
        ids, text = self.publish('common_three')
        body = json.loads(text)['body']
        rejected = []

        def check(mutate):
            mutated = copy.deepcopy(body)
            mutate(mutated)
            document = remake_document(mutated)
            with self.assertRaises(ValueError, msg=document):
                accept_pool(self.receiver, document)
            rejected.append(document)

        check(lambda b: b['evidence']['cells'][0].update(count=0))
        check(lambda b: b['evidence']['cells'][0].update(count=True))
        check(lambda b: b['evidence']['cells'][0].update(count='2'))
        check(lambda b: b['evidence']['cells'][0].update(values=[None] * len(ids)))
        check(lambda b: b['evidence']['cells'][0].update(values=['A']))
        check(lambda b: b['evidence']['cells'].append(b['evidence']['cells'][0]))
        check(lambda b: b['evidence']['cells'][0].update(kind='C'))
        check(lambda b: b['evidence'].update(extra=1))
        check(lambda b: b.update(unknown=[]))
        check(lambda b: b['origins'].reverse())
        check(lambda b: b['origins'].append(b['origins'][0]))
        check(lambda b: b.update(origins=b['origins'][:1]))
        check(lambda b: b['origins'].pop())

        def b_kind_b_offspring(b):
            for cell in b['evidence']['cells']:
                if cell['kind'] == 'B':
                    cell['values'] = ['B' if value is not None else None for value in cell['values']]
                    return
            raise AssertionError('no B cell in the evidence')

        check(b_kind_b_offspring)

        def noncanonical_offspring(b):
            for cell in b['evidence']['cells']:
                if 'AB' in cell['values']:
                    cell['values'] = ['BA' if value == 'AB' else value for value in cell['values']]
                    return
            raise AssertionError('no AB cell in the evidence')

        check(noncanonical_offspring)
        self.assertGreater(len(rejected), 10)
        self.assertEqual(self.receiver.execute('SELECT COUNT(*) FROM accepted_pools').fetchone()[0], 0)

    def test_common_three_selections(self):
        ids, accepted_id = self.accept_named('common_three')
        report = issue_pool(self.receiver, accepted_id, ids, 'A', 1)
        self.assertEqual(report.counts_a, (4, 0, 0, 1))
        self.assertEqual(report.counts_b, (0, 1))
        self.assertEqual(report.clearance, Fraction(1))
        self.assertEqual(report.conditional_cooccurrence, Fraction(1, 5))
        self.assertEqual([origin.cohort_id for origin in report.origins], sorted(ids))
        self.assertEqual(report.accepted_id, accepted_id)
        self.assertIsInstance(report.report_id, str)
        reordered = issue_pool(self.receiver, accepted_id, list(reversed(ids)), 'A', 1)
        self.assertEqual(reordered.counts_a, report.counts_a)
        self.assertEqual(reordered.origins, report.origins)
        first_pair = issue_pool(self.receiver, accepted_id, ids[:2], 'A', 1)
        self.assertEqual(first_pair.counts_a, (3, 0, 0, 1))
        self.assertEqual(first_pair.conditional_cooccurrence, Fraction(1, 4))
        last_pair = issue_pool(self.receiver, accepted_id, ids[1:], 'A', 1)
        self.assertEqual(last_pair.counts_a, (3, 0, 0, 0))
        self.assertEqual(last_pair.conditional_cooccurrence, Fraction(0))
        self.assertIsInstance(last_pair.conditional_cooccurrence, Fraction)
        from_b = issue_pool(self.receiver, accepted_id, ids, 'B', 1)
        self.assertEqual(from_b.clearance, Fraction(1))
        self.assertEqual(from_b.conditional_cooccurrence, Fraction(0))

    def test_separate_pairs_selection(self):
        ids, accepted_id = self.accept_named('separate_pairs')
        report = issue_pool(self.receiver, accepted_id, ids, 'A', 1)
        self.assertEqual(report.counts_a, (3, 0, 0, 1))
        self.assertEqual(report.counts_b, (0, 1))
        self.assertEqual(report.clearance, Fraction(1))
        self.assertEqual(report.conditional_cooccurrence, Fraction(1, 4))
        pair = issue_pool(self.receiver, accepted_id, ids[:2], 'A', 1)
        self.assertEqual(pair.counts_a, (3, 0, 0, 1))
        self.assertEqual(pair.conditional_cooccurrence, Fraction(1, 4))

    def test_swapped_conflict(self):
        ids, accepted_id = self.accept_named('swapped')
        first = issue_pool(self.receiver, accepted_id, [ids[0]], 'A', 1)
        second = issue_pool(self.receiver, accepted_id, [ids[1]], 'A', 1)
        self.assertEqual(first.conditional_cooccurrence, Fraction(1, 2))
        self.assertEqual(second.conditional_cooccurrence, Fraction(1, 2))
        self.assertEqual(first.counts_a, second.counts_a)
        partial = issue_pool(self.receiver, accepted_id, [ids[0], ids[2]], 'A', 1)
        self.assertEqual(partial.conditional_cooccurrence, Fraction(1, 2))
        self.assertEqual(len(partial.origins), 2)
        for selection in (ids[:2], [ids[1], ids[0]], ids):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                issue_pool(self.receiver, accepted_id, selection, 'A', 1)

    def test_split_requires_both_classes(self):
        ids, accepted_id = self.accept_named('split')
        both = issue_pool(self.receiver, accepted_id, ids, 'A', 1)
        self.assertEqual(both.counts_a, (1, 0, 0, 1))
        self.assertEqual(both.counts_b, (0, 1))
        self.assertEqual(both.conditional_cooccurrence, Fraction(1, 2))
        for selection in ([ids[0]], [ids[1]]):
            with self.subTest(selection=selection), self.assertRaises(MissingClassError):
                issue_pool(self.receiver, accepted_id, selection, 'A', 1)

    def test_selection_request_validation(self):
        ids, accepted_id = self.accept_named('common_three')
        report = issue_pool(self.receiver, accepted_id, ids, 'A', 1)
        with self.assertRaises(ValueError):
            issue_pool(self.receiver, accepted_id, [], 'A', 1)
        with self.assertRaises(ValueError):
            issue_pool(self.receiver, accepted_id, [ids[0], ids[0]], 'A', 1)
        with self.assertRaises(ValueError):
            issue_pool(self.receiver, accepted_id, ids[0], 'A', 1)
        with self.assertRaises(ValueError):
            issue_pool(self.receiver, accepted_id, [ids[0], 'unknown-cohort'], 'A', 1)
        with self.assertRaises(ValueError):
            issue_pool(self.receiver, accepted_id, ids, 'C', 1)
        for bad_round in (0, 7, 1.0, True, '2'):
            with self.subTest(round=bad_round), self.assertRaises(ValueError):
                issue_pool(self.receiver, accepted_id, ids, 'A', bad_round)
        with self.assertRaises(KeyError):
            issue_pool(self.receiver, 'unknown-accepted', ids, 'A', 1)
        with self.assertRaises(ValueError):
            issue_pool(self.receiver, 1, ids, 'A', 1)
        with self.assertRaises(KeyError):
            read_pool_report(self.receiver, 'unknown-report')
        with self.assertRaises(ValueError):
            read_pool_report(self.receiver, 1)
        self.assertEqual(
            self.receiver.execute('SELECT COUNT(*) FROM signed_pool_reports').fetchone()[0], 1)
        self.assertEqual(read_pool_report(self.receiver, report.report_id), report)

    def test_zero_clearance_selection(self):
        record(self.source, 'shift', 'a-only', 'A', ('A', 'B'))
        record(self.source, 'shift', 'b-only', 'B', ('A',))
        revision = RevisionStore(self.source).create_base()
        first = freeze(self.source, revision.revision_id, ['a-only', 'b-only'])
        second = freeze(self.source, revision.revision_id, ['b-only', 'a-only'])
        accepted_id = accept_pool(
            self.receiver, publish_pool(self.source, [first.cohort_id, second.cohort_id]))
        report = issue_pool(
            self.receiver, accepted_id, [first.cohort_id, second.cohort_id], 'A', 1)
        self.assertEqual(report.counts_a, (0, 0, 0, 1))
        self.assertEqual(report.counts_b, (0, 1))
        self.assertEqual(report.clearance, Fraction(0))
        self.assertIsNone(report.conditional_cooccurrence)

    def test_same_value_different_amendment_counts_once(self):
        record(self.source, 'shift', 'flex', 'A', ())
        record(self.source, 'shift', 'mate', 'B', ('A',))
        base = RevisionStore(self.source).create_base()
        away = amend(self.source, base.revision_id, 'flex', ('A',))
        back = amend(self.source, away.revision_id, 'flex', ())
        first = freeze(self.source, base.revision_id, ['flex', 'mate'])
        second = freeze(self.source, back.revision_id, ['flex', 'mate'])
        self.assertNotEqual(
            first.members[0].amendment_revision_id, second.members[0].amendment_revision_id)
        accepted_id = accept_pool(
            self.receiver, publish_pool(self.source, [first.cohort_id, second.cohort_id]))
        report = issue_pool(
            self.receiver, accepted_id, [second.cohort_id, first.cohort_id], 'A', 1)
        self.assertEqual(report.counts_a, (1, 0, 0, 0))
        self.assertEqual(report.counts_b, (0, 1))
        self.assertEqual(report.clearance, Fraction(1))

    def test_atomic_failures_and_retry(self):
        ids, accepted_id = self.accept_named('swapped')
        before = self.receiver.execute('SELECT COUNT(*) FROM signed_pool_reports').fetchone()[0]
        with self.assertRaises(ValueError):
            issue_pool(self.receiver, accepted_id, ids[:2], 'A', 1)
        self.assertEqual(
            self.receiver.execute('SELECT COUNT(*) FROM signed_pool_reports').fetchone()[0], before)
        self.receiver.execute('''
            CREATE TRIGGER reject_pool_report BEFORE INSERT ON signed_pool_reports
            BEGIN SELECT RAISE(ABORT, 'pool report rejected'); END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'pool report rejected'):
            issue_pool(self.receiver, accepted_id, [ids[0]], 'A', 1)
        self.assertFalse(self.receiver.in_transaction)
        self.reopen_receiver()
        self.assertEqual(
            self.receiver.execute('SELECT COUNT(*) FROM signed_pool_reports').fetchone()[0], before)
        self.receiver.execute('DROP TRIGGER reject_pool_report')
        retry = issue_pool(self.receiver, accepted_id, [ids[0]], 'A', 1)
        self.assertEqual(retry.conditional_cooccurrence, Fraction(1, 2))

    def test_accept_atomic_failure_and_retry(self):
        ids, text = self.publish('common_three')
        self.receiver.execute('''
            CREATE TRIGGER reject_pool_accept BEFORE INSERT ON accepted_pools
            BEGIN SELECT RAISE(ABORT, 'pool accept rejected'); END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'pool accept rejected'):
            accept_pool(self.receiver, text)
        self.assertFalse(self.receiver.in_transaction)
        self.assertEqual(self.receiver.execute('SELECT COUNT(*) FROM accepted_pools').fetchone()[0], 0)
        self.receiver.execute('DROP TRIGGER reject_pool_accept')
        accepted_id = accept_pool(self.receiver, text)
        report = issue_pool(self.receiver, accepted_id, ids, 'A', 1)
        self.assertEqual(report.conditional_cooccurrence, Fraction(1, 5))

    def test_history_survives_reopen_and_source_errata(self):
        ids, accepted_id = self.accept_named('common_three')
        report = issue_pool(self.receiver, accepted_id, ids, 'A', 1)
        cohort = read_frozen_cohort(self.source, ids[0])
        target = next(member for member in cohort.members if member.offspring == ('A', 'B'))
        correction = amend(
            self.source, cohort.provenance.revision_id, target.observation.inspection_id, ())
        revised = freeze(self.source, correction.revision_id,
                         [member.observation.inspection_id for member in cohort.members])
        initialize_receiver(self.receiver)
        self.reopen_receiver()
        self.reopen_source()
        archived = read_pool_report(self.receiver, report.report_id)
        self.assertEqual(archived, report)
        self.assertEqual(archived.counts_a, (4, 0, 0, 1))
        again = issue_pool(self.receiver, accepted_id, ids, 'A', 1)
        self.assertEqual(again.counts_a, report.counts_a)
        self.assertEqual(again.clearance, report.clearance)
        new_text = publish_pool(self.source, [revised.cohort_id, ids[1]])
        new_accepted = accept_pool(self.receiver, new_text)
        new_report = issue_pool(self.receiver, new_accepted, [revised.cohort_id, ids[1]], 'A', 1)
        self.assertNotEqual(new_report.counts_a, report.counts_a)

    def test_demo_pool_shift(self):
        scenario = run_pool_shift()
        self.assertEqual(scenario['case_id'], 'v9')
        self.assertEqual(scenario['actual']['common_three'][3], '1/5')
        self.assertEqual(scenario['actual']['separate_pairs'][3], '1/4')
        self.assertEqual(scenario['downstream_actual'], scenario['downstream_expected'])
        self.assertEqual(scenario['downstream_actual']['reserve_both'],
                         {'common_three': False, 'separate_pairs': True})
