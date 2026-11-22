from contextlib import closing
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from cohort.amendments import amend
from cohort.freeze import freeze, initialize_cohorts
from cohort.revisions import RevisionStore
from models.publish import fit, initialize_models, publish_pool, read_publication
from reports.compare import compare_reports
from reports.export import export_report
from reports.history import read, read_pool_report
from reports.issue import issue, issue_pool
from reports.store import PoolReportStore, SignedReport, SignedReportStore
from risk.accept import accept, accept_pool, initialize_risk
from trials.batches import BatchStore
from trials.completion import initialize_trials, record
from trials.parents import InspectionStore


SAMPLE = Path(__file__).resolve().parent / 'samples' / 'workday.json'


def initialize_source(connection: sqlite3.Connection) -> None:
    connection.execute('PRAGMA foreign_keys = ON')
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        initialize_trials(connection)
        initialize_cohorts(connection)
        initialize_models(connection)


def initialize_receiver(connection: sqlite3.Connection) -> None:
    connection.execute('PRAGMA foreign_keys = ON')
    connection.execute('BEGIN IMMEDIATE')
    with connection:
        initialize_risk(connection)
        SignedReportStore(connection).initialize()
        PoolReportStore(connection).initialize()


def load_workday(connection: sqlite3.Connection) -> dict:
    sample = json.loads(SAMPLE.read_text(encoding='utf-8'))
    batch_id = sample['batch_id']
    BatchStore(connection).open(batch_id)
    observations = sample['observations']
    first = observations[0]
    InspectionStore(connection).start(batch_id, first['inspection_id'], first['parent_kind'])
    for row in observations:
        record(connection, batch_id, row['inspection_id'], row['parent_kind'], row['offspring'])
    return sample


def _values(report: SignedReport) -> list[str | None]:
    result = report.result
    conditional = result.conditional_cooccurrence
    return [str(result.clearance), None if conditional is None else str(conditional)]


def _verify(expected: object, actual: object, label: str) -> None:
    if expected != actual:
        raise AssertionError(f'{label}: expected {expected!r}, got {actual!r}')


def _reserve_both(report: SignedReport, threshold: Fraction) -> bool:
    probability = report.result.conditional_cooccurrence
    return probability is not None and probability >= threshold


def run_workday() -> tuple[dict, dict]:
    with TemporaryDirectory(prefix='coating-workday-') as directory:
        source_path = Path(directory) / 'day.sqlite'
        receiver_path = Path(directory) / 'night.sqlite'
        with closing(sqlite3.connect(source_path)) as source:
            initialize_source(source)
            sample = load_workday(source)
            identities = [row['inspection_id'] for row in sample['observations']]
            base = RevisionStore(source).create_base()
            cohort = freeze(source, base.revision_id, identities)
            edition = fit(source, cohort.cohort_id)
            portable = read_publication(source, edition.law.model_id).text

        with closing(sqlite3.connect(receiver_path)) as receiver:
            initialize_receiver(receiver)
            model = accept(receiver, portable)
            initial = sample['initial_kind']
            first = issue(receiver, model.accepted_id, initial, 1)
            second = issue(receiver, model.accepted_id, initial, 2)

        correction = sample['correction']
        with closing(sqlite3.connect(source_path)) as source:
            initialize_source(source)
            changed = amend(source, base.revision_id, correction['inspection_id'], correction['offspring'])
            revised_cohort = freeze(source, changed.revision_id, identities)
            revised_edition = fit(source, revised_cohort.cohort_id)

        with closing(sqlite3.connect(receiver_path)) as receiver:
            initialize_receiver(receiver)
            revised_model = accept(receiver, revised_edition.text)
            revised = issue(receiver, revised_model.accepted_id, initial, 1)
            archived = read(receiver, first.report_id)
            exported = json.loads(export_report(receiver, first.report_id))
            compared = compare_reports(receiver, first.report_id, revised.report_id)

        threshold = Fraction(*sample['reserve_threshold'])
        expected = {'round_1': ['1/3', '1/4'], 'round_2': ['1/3', '1/16']}
        actual = {'round_1': _values(first), 'round_2': _values(second)}
        downstream_expected = {'continued_risk': '2/3', 'reserve_both': [True, False]}
        downstream_actual = {
            'continued_risk': str(1 - first.result.clearance),
            'reserve_both': [_reserve_both(first, threshold), _reserve_both(second, threshold)],
        }
        _verify(expected, actual, 'original risk')
        _verify(downstream_expected, downstream_actual, 'staffing decision')
        clearance_scenario = {
            'case_id': 'v7',
            'input': {
                'observations': sample['observations'], 'initial': initial,
                'rounds': [1, 2], 'reserve_threshold': sample['reserve_threshold'],
            },
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream_actual,
            'code_paths': ['models/publish.py', 'risk/accept.py', 'risk/clearance.py', 'risk/evaluate.py', 'reports/issue.py'],
            'oracle': 'With qB=qA, the A equation has roots 1/3 and 1. Given eventual clearance, each A produces AB with probability 1/4, and two consecutive such transitions are necessary for round two cooccurrence.',
        }
        expected = {'original': ['1/3', '1/4'], 'revised': ['1', '1/2']}
        actual = {'original': _values(archived), 'revised': _values(revised)}
        downstream_expected = {'same_archive': True, 'separate_origins': True, 'deltas': ['2/3', '1/4']}
        downstream_actual = {
            'same_archive': archived == first and exported['clearance'] == [1, 3]
            and exported['conditional_cooccurrence'] == [1, 4]
            and exported['origin']['cohort_id'] == first.result.origin.cohort_id,
            'separate_origins': revised.result.origin.cohort_id != archived.result.origin.cohort_id,
            'deltas': [str(compared.clearance_delta), str(compared.cooccurrence_delta)],
        }
        _verify(expected, actual, 'revised and archived risk')
        _verify(downstream_expected, downstream_actual, 'handover comparison')
        history_scenario = {
            'case_id': 'v8',
            'input': {'amendment': correction, 'initial': initial, 'round': 1},
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream_actual,
            'code_paths': ['cohort/amendments.py', 'cohort/freeze.py', 'reports/history.py', 'reports/export.py', 'reports/compare.py'],
            'oracle': 'The correction leaves two empty and two AB observations. The only fixed-point value is one, so the new first-round risk is the observed AB frequency of one half. Subtract the original signed fractions.',
        }
        return clearance_scenario, history_scenario


def run_pool_shift() -> dict:
    """Sign night-shift staffing from pooled documents after the source closes."""
    from pool_fixture import load_pool_sample

    with TemporaryDirectory(prefix='coating-pool-') as directory:
        source_path = Path(directory) / 'pool-day.sqlite'
        receiver_path = Path(directory) / 'pool-night.sqlite'
        with closing(sqlite3.connect(source_path)) as source:
            initialize_source(source)
            samples = load_pool_sample(source)
            texts = {}
            for name in ('common_three', 'separate_pairs', 'swapped'):
                ids = [cohort.cohort_id for cohort in samples[name]]
                texts[name] = (ids, publish_pool(source, ids))

        reports = {}
        with closing(sqlite3.connect(receiver_path)) as receiver:
            initialize_receiver(receiver)
            for name in ('common_three', 'separate_pairs'):
                ids, text = texts[name]
                accepted_id = accept_pool(receiver, text)
                reports[name] = issue_pool(receiver, accepted_id, ids, 'A', 1)
            swapped_ids, swapped_text = texts['swapped']
            swapped_accepted = accept_pool(receiver, swapped_text)
            try:
                issue_pool(receiver, swapped_accepted, swapped_ids[:2], 'A', 1)
            except ValueError:
                conflict_rejected = True
            else:
                conflict_rejected = False
            partial = issue_pool(receiver, swapped_accepted, [swapped_ids[0], swapped_ids[2]], 'A', 1)
            archived_id = reports['separate_pairs'].report_id

        with closing(sqlite3.connect(receiver_path)) as receiver:
            initialize_receiver(receiver)
            archived = read_pool_report(receiver, archived_id)

        threshold = Fraction(1, 4)
        actual = {
            name: [list(report.counts_a), list(report.counts_b), str(report.clearance),
                   str(report.conditional_cooccurrence)]
            for name, report in reports.items()
        }
        expected = {
            'common_three': [[4, 0, 0, 1], [0, 1], '1', '1/5'],
            'separate_pairs': [[3, 0, 0, 1], [0, 1], '1', '1/4'],
        }
        downstream_expected = {
            'reserve_both': {'common_three': False, 'separate_pairs': True},
            'conflict_rejected': True,
            'partial_signs': '1/2',
            'archived_match': True,
        }
        downstream_actual = {
            'reserve_both': {
                name: report.conditional_cooccurrence >= threshold
                for name, report in reports.items()
            },
            'conflict_rejected': conflict_rejected,
            'partial_signs': str(partial.conditional_cooccurrence),
            'archived_match': archived == reports['separate_pairs'],
        }
        _verify(expected, actual, 'pooled staffing risk')
        _verify(downstream_expected, downstream_actual, 'pooled staffing decisions')
        return {
            'case_id': 'v9',
            'input': {
                'scenarios': ['common_three', 'separate_pairs'],
                'initial': 'A', 'round': 1, 'reserve_threshold': [1, 4],
            },
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream_actual,
            'code_paths': ['models/pool.py', 'models/publish.py', 'risk/accept.py',
                           'risk/evaluate.py', 'reports/issue.py', 'reports/history.py'],
            'oracle': 'Both packages share single-cohort and pairwise-intersection counts, '
                      'but pooled dedup leaves four A-empty observations in common_three and '
                      'three in separate_pairs, so first-round cooccurrence is 1/5 versus 1/4 '
                      'against the 1/4 two-lane reserve line.',
        }


if __name__ == '__main__':
    for scenario in run_workday():
        print('POINTWISE_SCENARIO ' + json.dumps(scenario, sort_keys=True))
    print('POINTWISE_SCENARIO ' + json.dumps(run_pool_shift(), sort_keys=True))
