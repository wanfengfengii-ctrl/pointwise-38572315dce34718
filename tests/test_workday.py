import unittest

from demo import run_workday


class WorkdayTests(unittest.TestCase):
    def test_complete_workday(self):
        night, after_correction = run_workday()
        self.assertEqual(night['case_id'], 'v7')
        self.assertEqual(night['actual'], {'round_1': ['1/3', '1/4'], 'round_2': ['1/3', '1/16']})
        self.assertEqual(night['downstream_actual']['reserve_both'], [True, False])
        self.assertEqual(after_correction['case_id'], 'v8')
        self.assertEqual(after_correction['actual'], {'original': ['1/3', '1/4'], 'revised': ['1', '1/2']})
        self.assertEqual(after_correction['downstream_actual'], {
            'same_archive': True, 'separate_origins': True, 'deltas': ['2/3', '1/4'],
        })
