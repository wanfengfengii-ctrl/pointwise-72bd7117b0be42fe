from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction
import json
import sqlite3

from intake.catalog import IntakeCatalog
from intake.receive import pin_window_issue, receive_window
from issue.codec import encode_payload
from issue.freeze import freeze, freeze_window, make_window_packet
from issue.register import IssueRegister
from report.compare import InvalidComparison, compare_window
from report.read import ReportNotFound, read
from report.store import ReportStore
from rules.catalog import RuleCatalog
from rules.importer import register
from tests import LedgerCase, chain
from window_fixture import load_case


STATION = 'repair-test'


class WindowCase(LedgerCase):
    def setUp(self):
        super().setUp()
        self.case = load_case()
        self.left_rev = register(self.catalog, self.case['rule_code'], self.case['left'])
        self.right_rev = register(self.catalog, self.case['rule_code'], self.case['right'])
        self.left_issue, self.left_cred = freeze_window(self.catalog, self.issues, self.left_rev)
        self.right_issue, self.right_cred = freeze_window(self.catalog, self.issues, self.right_rev)
        for issue_id, credential in (
            (self.left_issue, self.left_cred), (self.right_issue, self.right_cred)
        ):
            pin_window_issue(self.intake, STATION, issue_id, credential)

    def deliver(self, issue_id, lo, hi, *, packet=None):
        raw = packet if packet is not None else make_window_packet(
            self.issues, issue_id, lo, hi
        )
        return receive_window(self.intake, STATION, issue_id, lo, hi, raw)

    def sign(self, lo='1/4', hi='3/4'):
        left = self.deliver(self.left_issue, lo, hi)
        right = self.deliver(self.right_issue, lo, hi)
        return compare_window(self.intake, self.store, left.intake_id, right.intake_id), left, right


class TestWindowDelivery(WindowCase):
    def test_sample_window_matches(self):
        signed, left, right = self.sign()
        expected = self.case['expected_window']
        self.assertEqual(
            [[beat, str(mass)] for beat, mass in signed.draft.first_differences],
            expected['first_differences'],
        )
        self.assertEqual(str(signed.draft.always_same), expected['always_same'])
        self.assertEqual(signed.draft.window, (Fraction(1, 4), Fraction(3, 4)))
        self.assertEqual(signed.draft.parents, (left, right))
        self.assertEqual(signed.receipt.parents, (left, right))
        self.assertEqual(signed.receipt.report_id, signed.report_id)
        self.assertEqual(read(self.store, signed.report_id), signed)

    def test_tight_window(self):
        signed, _, _ = self.sign('1/2', '2/3')
        self.assertEqual(signed.draft.first_differences, ((2, Fraction(1)),))
        self.assertEqual(signed.draft.always_same, Fraction(0))

    def test_only_positive_intersections_delivered(self):
        # [1/4, 3/4) cuts [1/8,1/3) and [2/3,5/6) internally; the low/high
        # out-of-window segments touch it not at all.
        raw = json.loads(make_window_packet(self.issues, self.left_issue, '1/4', '3/4'))
        bands = [(row['lower'], row['upper']) for row in raw['body']['traces']]
        self.assertEqual(
            bands,
            [('1/8', '1/3'), ('1/3', '1/2'), ('1/2', '2/3'), ('2/3', '5/6')],
        )
        self.assertNotIn('窗外低档', json.dumps(raw, ensure_ascii=False))
        self.assertNotIn('窗外高档', json.dumps(raw, ensure_ascii=False))

    def test_endpoint_touch_not_delivered(self):
        # [1/2, 2/3) abuts [1/3,1/2) and [2/3,5/6) only at endpoints.
        raw = json.loads(make_window_packet(self.issues, self.left_issue, '1/2', '2/3'))
        bands = [(row['lower'], row['upper']) for row in raw['body']['traces']]
        self.assertEqual(bands, [('1/2', '2/3')])

    def test_later_revision_does_not_change_issue(self):
        before = make_window_packet(self.issues, self.left_issue, '1/4', '3/4')
        corrected = deepcopy(self.case['left'])
        corrected['states']['sort'][3]['action'] = '改写'
        register(self.catalog, self.case['rule_code'], corrected)
        after = make_window_packet(self.issues, self.left_issue, '1/4', '3/4')
        self.assertEqual(before, after)

    def test_unknown_and_non_window_issue(self):
        with self.assertRaises(ValueError):
            make_window_packet(self.issues, 999, '1/4', '3/4')
        plain = freeze(self.catalog, self.issues, self.left_rev)
        with self.assertRaises(ValueError):
            make_window_packet(self.issues, plain.issue_id, '1/4', '3/4')

    def test_illegal_windows(self):
        for lo, hi in (('3/4', '1/4'), ('1/2', '1/2'), ('-1/4', '1/2'),
                       ('1/2', '5/4'), (0.5, '3/4'), (True, '3/4')):
            with self.subTest(lo=lo, hi=hi):
                with self.assertRaises(ValueError):
                    make_window_packet(self.issues, self.left_issue, lo, hi)

    def test_duplicate_delivery_gets_new_numbers(self):
        first = self.deliver(self.left_issue, '1/4', '3/4')
        before = self.intake_counts()
        second = self.deliver(self.left_issue, '1/4', '3/4')
        self.assertNotEqual(first.intake_id, second.intake_id)
        self.assertEqual(self.intake_counts(), (before[0] + 1, before[1] + 1))
        self.assertEqual(self.intake.get_window(second.intake_id).window,
                         (Fraction(1, 4), Fraction(3, 4)))

    def test_digest_is_actual_bytes(self):
        raw = make_window_packet(self.issues, self.left_issue, '1/4', '3/4')
        receipt = self.deliver(self.left_issue, '1/4', '3/4', packet=raw)
        from hashlib import sha256
        self.assertEqual(receipt.digest, sha256(raw).hexdigest())


class TestWindowRejection(WindowCase):
    def _assert_rejected(self, issue_id, lo, hi, packet=None, *, request_issue=None,
                         request_station=STATION):
        before = self.intake_counts()
        raw = packet if packet is not None else make_window_packet(
            self.issues, issue_id, lo, hi
        )
        with self.assertRaises(ValueError):
            receive_window(
                self.intake,
                request_station,
                request_issue if request_issue is not None else issue_id,
                lo,
                hi,
                raw,
            )
        self.assertEqual(self.intake_counts(), before)
        self.assertEqual(self.report_counts(), (0, 0))

    def test_missing_credential(self):
        # Requested under a station that never pinned this issuance.
        self._assert_rejected(self.left_issue, '1/4', '3/4', request_station='other-station')
        # Registered window issue that is not pinned in this foreign library.
        fresh = IssueRegister(self.day, STATION)
        other_issue, _ = freeze_window(self.catalog, fresh, self.left_rev)
        raw = make_window_packet(fresh, other_issue, '1/4', '3/4')
        self._assert_rejected(other_issue, '1/4', '3/4', packet=raw)

    def test_wrong_window_request(self):
        raw = make_window_packet(self.issues, self.left_issue, '1/4', '3/4')
        self._assert_rejected(self.left_issue, '1/5', '3/4', packet=raw)
        self._assert_rejected(self.left_issue, '1/4', '2/3', packet=raw)

    def test_missing_segment(self):
        fields = json.loads(make_window_packet(self.issues, self.left_issue, '1/4', '3/4'))
        del fields['body']['traces'][-1]
        self._assert_rejected(self.left_issue, '1/4', '3/4', packet=encode_payload(fields))

    def test_extra_segment(self):
        fields = json.loads(make_window_packet(self.issues, self.left_issue, '1/4', '3/4'))
        extra = deepcopy(fields['body']['traces'][0])
        extra.update({'lower': '0', 'upper': '1/8', 'actions': ['进站', '窗外低档']})
        fields['body']['traces'].insert(0, extra)
        self._assert_rejected(self.left_issue, '1/4', '3/4', packet=encode_payload(fields))

    def test_rewritten_segment(self):
        fields = json.loads(make_window_packet(self.issues, self.left_issue, '1/4', '3/4'))
        fields['body']['traces'][0]['actions'][1] = '补检'
        self._assert_rejected(self.left_issue, '1/4', '3/4', packet=encode_payload(fields))

    def test_rewritten_boundary(self):
        fields = json.loads(make_window_packet(self.issues, self.left_issue, '1/4', '3/4'))
        fields['body']['traces'][0]['upper'] = '5/12'
        self._assert_rejected(self.left_issue, '1/4', '3/4', packet=encode_payload(fields))

    def test_swapped_issue(self):
        raw = make_window_packet(self.issues, self.right_issue, '1/4', '3/4')
        # Present the right revision's packet under the left issue number.
        self._assert_rejected(self.left_issue, '1/4', '3/4', packet=raw)

    def test_self_declared_digest_is_not_trusted(self):
        fields = json.loads(make_window_packet(self.issues, self.left_issue, '1/4', '3/4'))
        fields['body']['traces'][0]['actions'][1] = '补检'
        # Recompute a bogus HMAC-looking proof; without the pinned key it fails.
        fields['body']['proof']['mac'] = '0' * 64
        self._assert_rejected(self.left_issue, '1/4', '3/4', packet=encode_payload(fields))

    def test_non_canonical_packet(self):
        raw = make_window_packet(self.issues, self.left_issue, '1/4', '3/4')
        padded = raw.replace(b',', b', ', 1)
        self._assert_rejected(self.left_issue, '1/4', '3/4', packet=padded)

    def test_pin_conflict_preserves_original(self):
        original = self.intake.get_pin(STATION, self.left_issue)
        with self.assertRaises(ValueError):
            pin_window_issue(self.intake, STATION, self.left_issue, b'{"bogus":true}')
        self.assertEqual(self.intake.get_pin(STATION, self.left_issue), original)
        # Re-pinning the identical bytes succeeds.
        pin_window_issue(self.intake, STATION, self.left_issue, self.left_cred)

    def test_credential_station_mismatch(self):
        with self.assertRaises(ValueError):
            pin_window_issue(self.intake, 'other-station', self.left_issue, self.left_cred)


class TestWindowSigning(WindowCase):
    def test_ordered_parents(self):
        left = self.deliver(self.left_issue, '1/4', '3/4')
        right = self.deliver(self.right_issue, '1/4', '3/4')
        forward = compare_window(self.intake, self.store, left.intake_id, right.intake_id)
        reverse = compare_window(self.intake, self.store, right.intake_id, left.intake_id)
        self.assertEqual(forward.draft.parents, (left, right))
        self.assertEqual(reverse.draft.parents, (right, left))
        self.assertEqual(forward.draft.first_differences, reverse.draft.first_differences)
        self.assertEqual(forward.report_id != reverse.report_id, True)

    def test_mismatched_windows_rejected(self):
        left = self.deliver(self.left_issue, '1/4', '3/4')
        right = self.deliver(self.right_issue, '1/3', '2/3')
        with self.assertRaises(InvalidComparison):
            compare_window(self.intake, self.store, left.intake_id, right.intake_id)
        self.assertEqual(self.report_counts(), (0, 0))

    def test_non_window_or_missing_parents(self):
        window = self.deliver(self.left_issue, '1/4', '3/4')
        legacy = self.accept(self.left_rev)
        with self.assertRaisesRegex(InvalidComparison, 'right'):
            compare_window(self.intake, self.store, window.intake_id, 999)
        with self.assertRaisesRegex(InvalidComparison, 'left'):
            compare_window(self.intake, self.store, True, window.intake_id)
        with self.assertRaises(InvalidComparison):
            compare_window(self.intake, self.store, window.intake_id, legacy.intake_id)
        self.assertEqual(self.report_counts(), (0, 0))

    def test_publish_rollback(self):
        left = self.deliver(self.left_issue, '1/4', '3/4')
        right = self.deliver(self.right_issue, '1/4', '3/4')
        self.night.execute('''CREATE TRIGGER block_report_receipt BEFORE INSERT ON report_receipts
                              BEGIN SELECT RAISE(ABORT, 'blocked'); END''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'blocked'):
            compare_window(self.intake, self.store, left.intake_id, right.intake_id)
        self.night.execute('DROP TRIGGER block_report_receipt')
        self.assertEqual(self.report_counts(), (0, 0))
        with self.assertRaises(ReportNotFound):
            read(self.store, 1)

    def test_reopen_reclaim(self):
        signed, left, right = self.sign()
        self.night.close()
        self.open_night()
        recalled = read(self.store, signed.report_id)
        self.assertEqual(recalled, signed)
        self.assertEqual(recalled.draft.window, (Fraction(1, 4), Fraction(3, 4)))
        self.assertEqual(recalled.receipt.parents, (left, right))
        # The night library alone suffices; no day-side state is needed.
        self.day.close()
        self.open_night()


class TestWindowIntake(WindowCase):
    def test_acyclic_cycle_equivalence_over_window(self):
        # Same window, traces that differ only in cycle representation.
        left_rules = chain(('A',), 0)
        right_rules = chain(('A', 'A'), 0)
        left_rev = register(self.catalog, 'R-99', left_rules)
        right_rev = register(self.catalog, 'R-99', right_rules)
        left_issue, left_cred = freeze_window(self.catalog, self.issues, left_rev)
        right_issue, right_cred = freeze_window(self.catalog, self.issues, right_rev)
        pin_window_issue(self.intake, STATION, left_issue, left_cred)
        pin_window_issue(self.intake, STATION, right_issue, right_cred)
        left = self.deliver(left_issue, '0', '1')
        right = self.deliver(right_issue, '0', '1')
        signed = compare_window(self.intake, self.store, left.intake_id, right.intake_id)
        self.assertEqual(signed.draft.first_differences, ())
        self.assertEqual(signed.draft.always_same, Fraction(1))

    def test_partial_window_probabilities(self):
        # [1/8, 5/12) intersects [1/8,1/3) and [1/3,1/2) on the left and
        # [1/8,5/12), [5/12,1/2) on the right. The only difference is on
        # [1/2,2/3), so this window is entirely always-same.
        signed, _, _ = self.sign('1/8', '5/12')
        self.assertEqual(signed.draft.first_differences, ())
        self.assertEqual(signed.draft.always_same, Fraction(1))
