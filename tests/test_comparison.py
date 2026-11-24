from dataclasses import asdict
from fractions import Fraction
import json
import sqlite3

from report.compare import InvalidComparison, compare
from report.read import ReportNotFound, read
from tests import LedgerCase, chain, sample, transition, with_cut
from trial.session import preview


class TestComparison(LedgerCase):
    def _compare(self, left, right):
        return compare(self.intake, self.store, left.intake_id, right.intake_id)

    def _assert_distribution(self, report, rows, same):
        self.assertEqual(report.draft.first_differences, rows)
        self.assertEqual(report.draft.always_same, same)
        self.assertIsInstance(report.draft.always_same, Fraction)
        for _, mass in report.draft.first_differences:
            self.assertIsInstance(mass, Fraction)
            self.assertGreater(mass, 0)
        self.assertEqual(sum(mass for _, mass in rows) + report.draft.always_same, 1)

    def test_grade_swap(self):
        left, right = self.receive_pair(sample('old'), sample('swapped'))
        wanted = (left.receipt, right.receipt)
        self.isolate_source()
        signed = self._compare(left, right)
        self._assert_distribution(signed, ((2, Fraction(1)),), Fraction(0))
        self.assertEqual(signed.draft.parents, wanted)
        self.assertEqual(signed.receipt.parents, wanted)
        self.assertEqual(self.report_counts(), (1, 1))
        downstream = read(self.store, signed.report_id)
        self.assertEqual(downstream, signed)
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v5',
            'input': {'ordered_intakes': [left.intake_id, right.intake_id],
                      'grades': ['[0,1/2)', '[1/2,1)'], 'source_available': self.day_path.exists()},
            'expected': {'first_differences': [[2, '1']], 'always_same': '0'},
            'actual': {'first_differences': [[beat, str(mass)] for beat, mass in signed.draft.first_differences],
                       'always_same': str(signed.draft.always_same)},
            'downstream_expected': {'parents': [asdict(parent) for parent in wanted], 'paired': True},
            'downstream_actual': {'parents': [asdict(parent) for parent in downstream.receipt.parents],
                                  'paired': downstream.report_id == downstream.receipt.report_id},
            'code_paths': ['issue/evidence.py', 'intake/catalog.py', 'report/compare.py',
                           'report/distribution.py', 'report/sequence.py', 'report/store.py', 'report/read.py'],
            'oracle': '两半区各长 1/2，首拍均进站，次拍均互换。报告父件应为请求的有序实收回执。',
        }, ensure_ascii=False))

    def test_aligned(self):
        left, right = self.receive_pair(sample('old'), sample('aligned'))
        self.isolate_source()
        self._assert_distribution(self._compare(left, right), (), Fraction(1))

    def test_exact_mass(self):
        left, right = self.receive_pair(with_cut(sample('old'), '1/3'), with_cut(sample('aligned'), '2/3'))
        self.isolate_source()
        signed = self._compare(left, right)
        self._assert_distribution(signed, ((2, Fraction(1, 3)),), Fraction(2, 3))
        self.assertEqual(read(self.store, signed.report_id).draft, signed.draft)

    def test_aggregates_multiple_first_beats_in_order(self):
        right_rules = chain(('A',), 0)
        right_rules['states'] = {
            's0': [transition('A', 'choice', '0', '1/6'),
                   transition('B', 'done', '1/6', '1/3'),
                   transition('A', 'choice', '1/3', '1/2'),
                   transition('A', 'same', '1/2', '1')],
            'choice': [transition('B', 'done')],
            'same': [transition('A', 'same')],
        }
        left, right = self.receive_pair(chain(('A',), 0), right_rules)
        self.isolate_source()
        self._assert_distribution(
            self._compare(left, right), ((1, Fraction(1, 6)), (2, Fraction(1, 3))), Fraction(1, 2)
        )

    def test_ordered_parents(self):
        left, right = self.receive_pair(sample('old'), sample('swapped'))
        self.isolate_source()
        forward = self._compare(left, right)
        reverse = self._compare(right, left)
        self.assertEqual(forward.draft.first_differences, reverse.draft.first_differences)
        self.assertEqual(forward.draft.always_same, reverse.draft.always_same)
        self.assertEqual(forward.draft.parents, (left.receipt, right.receipt))
        self.assertEqual(reverse.draft.parents, (right.receipt, left.receipt))
        self.assertEqual(forward.receipt.parents, forward.draft.parents)
        self.assertEqual(reverse.receipt.parents, reverse.draft.parents)
        self.assertEqual(read(self.store, reverse.report_id), reverse)
        self._assert_distribution(self._compare(left, left), (), Fraction(1))

    def test_historical_read(self):
        left, right = self.receive_pair(sample('old'), sample('swapped'))
        original = self._compare(left, right)
        self._assert_distribution(original, ((2, Fraction(1)),), Fraction(0))
        self.enroll(sample('aligned'))
        self.isolate_source()
        self.night.close()
        self.open_night()
        recalled = read(self.store, original.report_id)
        self.assertEqual(recalled, original)
        self.assertEqual(recalled.draft.parents, (left.receipt, right.receipt))
        self.assertEqual(recalled.receipt.parents, (left.receipt, right.receipt))
        self.assertEqual(self.report_counts(), (1, 1))

    def test_another_report(self):
        left, right = self.receive_pair(sample('old'), sample('swapped'))
        original = self._compare(left, right)
        corrected = self.accept(self.enroll(sample('aligned')))
        self.isolate_source()
        later = self._compare(left, corrected)
        self.night.close()
        self.open_night()
        old_result = read(self.store, original.report_id)
        new_result = read(self.store, later.report_id)
        self.assertNotEqual(original.report_id, later.report_id)
        self._assert_distribution(old_result, ((2, Fraction(1)),), Fraction(0))
        self._assert_distribution(new_result, (), Fraction(1))
        self.assertEqual(old_result, original)
        self.assertEqual(new_result, later)
        self.assertEqual(old_result.draft.parents, (left.receipt, right.receipt))
        self.assertEqual(new_result.draft.parents, (left.receipt, corrected.receipt))
        self.assertEqual(self.report_counts(), (2, 2))

    def test_not_found(self):
        before = self.report_counts()
        with self.assertRaises(ReportNotFound):
            read(self.store, 999)
        self.assertEqual(self.report_counts(), before)

    def test_reopen_initialize(self):
        left, right = self.receive_pair(sample('old'), sample('swapped'))
        original = self._compare(left, right)
        user_rules = sample('aligned')
        user_rules['note'] = '质控复查后的用户更正'
        current_id = self.enroll(user_rules)
        recorded = preview(self.catalog, self.history, current_id, '1/4', 3)
        day_tables = ('rule_revisions', 'current_rules', 'replay_history', 'issued_packets')
        for _ in range(2):
            self.day.close()
            self.night.close()
            self.open_day()
            self.open_night()
            current = self.catalog.current_revision('R-17')
            self.assertEqual(current.revision_id, current_id)
            self.assertEqual(current.definition.note, user_rules['note'])
            self.assertEqual(self.counts(self.day, *day_tables), (3, 1, 1, 2))
            self.assertEqual(self.intake_counts(), (2, 2))
            self.assertEqual(self.report_counts(), (1, 1))
            self.assertEqual(self.history.get(recorded.record_id), recorded)
            self.assertEqual(self.issues.get(left.receipt.issue_id), left.envelope)
            self.assertEqual(self.intake.get(right.intake_id), right)
            recalled = read(self.store, original.report_id)
            self.assertEqual(recalled.draft.parents, (left.receipt, right.receipt))
            self.assertEqual(recalled.receipt, original.receipt)
            self.assertEqual(recalled, original)

    def test_missing_receipt(self):
        left = self.accept(self.enroll(sample('old')))
        self.isolate_source()
        before = self.report_counts()
        with self.assertRaisesRegex(InvalidComparison, 'right'):
            compare(self.intake, self.store, left.intake_id, 999)
        with self.assertRaisesRegex(InvalidComparison, 'left'):
            compare(self.intake, self.store, True, left.intake_id)
        self.assertEqual(self.report_counts(), before)

    def _block_report_receipts(self):
        self.night.execute('''CREATE TRIGGER block_report_receipt BEFORE INSERT ON report_receipts
                              BEGIN SELECT RAISE(ABORT, 'report receipt blocked'); END''')

    def test_publish_rollback(self):
        left, right = self.receive_pair(sample('old'), sample('swapped'))
        self.isolate_source()
        original = self._compare(left, right)
        before = self.report_counts()
        self._block_report_receipts()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'report receipt blocked'):
            self._compare(right, left)
        self.night.close()
        self.open_night()
        self.assertEqual(self.report_counts(), before)
        self.assertEqual(read(self.store, original.report_id), original)

    def test_publish_retry(self):
        left, right = self.receive_pair(sample('old'), sample('swapped'))
        self.isolate_source()
        self._block_report_receipts()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'report receipt blocked'):
            self._compare(left, right)
        self.night.close()
        self.open_night()
        self.assertEqual(self.report_counts(), (0, 0))
        self.night.execute('DROP TRIGGER block_report_receipt')
        signed = self._compare(left, right)
        self.assertEqual(self.report_counts(), (1, 1))
        self._assert_distribution(signed, ((2, Fraction(1)),), Fraction(0))
        self.assertEqual(signed.receipt.report_id, signed.report_id)
        self.assertEqual(signed.receipt.parents, (left.receipt, right.receipt))
        self.assertEqual(read(self.store, signed.report_id), signed)

    def test_deferred_commit_failure_rolls_back_both_writes(self):
        left, right = self.receive_pair(sample('old'), sample('swapped'))
        self.isolate_source()
        self.night.execute('CREATE TABLE publication_gate (gate_id INTEGER PRIMARY KEY)')
        self.night.execute('''CREATE TABLE gated_publication (
            gate_id INTEGER REFERENCES publication_gate(gate_id) DEFERRABLE INITIALLY DEFERRED
        )''')
        self.night.execute('''CREATE TRIGGER check_gate AFTER INSERT ON report_receipts
                              BEGIN INSERT INTO gated_publication VALUES (1); END''')
        with self.assertRaises(sqlite3.IntegrityError):
            self._compare(left, right)
        self.assertFalse(self.night.in_transaction)
        self.night.close()
        self.open_night()
        self.assertEqual(self.report_counts(), (0, 0))
        self.assertEqual(self.counts(self.night, 'gated_publication'), (0,))

    def test_equivalent_cycles(self):
        left, right = self.receive_pair(chain(('A',), 0), chain(('A', 'A'), 0))
        self.isolate_source()
        self._assert_distribution(self._compare(left, right), (), Fraction(1))

    def test_second_beat(self):
        left, right = self.receive_pair(chain(('A',), 0), chain(('A', 'B'), 0))
        self.isolate_source()
        self._assert_distribution(self._compare(left, right), ((2, Fraction(1)),), Fraction(0))

    def test_termination(self):
        left, right = self.receive_pair(chain(('A',)), chain(('A',)))
        cycle = self.accept(self.enroll(chain(('A',), 0)))
        immediate = self.accept(self.enroll(chain(())))
        end_action = self.accept(self.enroll(chain(('结束',))))
        self.isolate_source()
        self._assert_distribution(self._compare(left, right), (), Fraction(1))
        self._assert_distribution(self._compare(left, cycle), ((2, Fraction(1)),), Fraction(0))
        self._assert_distribution(self._compare(immediate, end_action), ((1, Fraction(1)),), Fraction(0))

    def test_mixed(self):
        rules = chain(('A', 'A'), 0)
        rules['states']['s1'] = [transition('A', 's0', '0', '1/2'), transition('B', 's0', '1/2', '1')]
        left, right = self.receive_pair(chain(('A',), 0), rules)
        self.isolate_source()
        report = self._compare(left, right)
        self._assert_distribution(report, ((2, Fraction(1, 2)),), Fraction(1, 2))
        self.assertEqual(read(self.store, report.report_id), report)

    def test_cycle_phase_and_late_divergence(self):
        left, same = self.receive_pair(chain(('A', 'B'), 0), chain(('A', 'B', 'A'), 1))
        later = self.accept(self.enroll(chain(('A', 'B', 'A', 'B', 'C'), 4)))
        self.isolate_source()
        self._assert_distribution(self._compare(left, same), (), Fraction(1))
        self._assert_distribution(self._compare(left, later), ((5, Fraction(1)),), Fraction(0))
