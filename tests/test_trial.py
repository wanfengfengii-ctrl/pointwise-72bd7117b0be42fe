from fractions import Fraction
import sqlite3

from rules.validation import InvalidRules
from tests import LedgerCase, chain, sample
from trial.session import InvalidReplay, preview


class TestTrial(LedgerCase):
    def test_half_open(self):
        revision = self.enroll(sample('old'))
        record = preview(self.catalog, self.history, revision, '1/2', 2)
        self.assertEqual(record.trace.actions, ('进站', '留线'))
        self.assertEqual(record.grade, Fraction(1, 2))
        self.assertEqual(self.history.get(record.record_id), record)

    def test_multi_step(self):
        revision = self.enroll(sample('old'))
        left = preview(self.catalog, self.history, revision, '1/4', 2)
        right = preview(self.catalog, self.history, revision, Fraction(1, 2), 2)
        self.assertEqual(left.trace.actions, ('进站', '返检'))
        self.assertEqual(right.trace.actions, ('进站', '留线'))
        self.assertEqual(self.history.get(left.record_id).grade, Fraction(1, 4))
        self.assertEqual(self.history.get(right.record_id).grade, Fraction(1, 2))

    def test_terminal_window(self):
        revision = self.enroll(sample('old'))
        empty = preview(self.catalog, self.history, revision, 0, 0)
        two = preview(self.catalog, self.history, revision, 0, 2)
        three = preview(self.catalog, self.history, revision, 0, 3)
        self.assertEqual(empty.trace.actions, ())
        self.assertIsNone(empty.trace.ended_at)
        self.assertEqual(two.trace.actions, ('进站', '返检'))
        self.assertEqual(three.trace.actions, two.trace.actions)
        self.assertIsNone(two.trace.ended_at)
        self.assertEqual(three.trace.ended_at, 3)
        self.assertEqual(self.history.get(three.record_id).trace.ended_at, 3)
        terminal_start = self.enroll(chain(()))
        ended = preview(self.catalog, self.history, terminal_start, 0, 1)
        self.assertEqual(ended.trace.actions, ())
        self.assertEqual(ended.trace.ended_at, 1)

    def test_invalid_input(self):
        revision = self.enroll(sample('old'))
        previous = preview(self.catalog, self.history, revision, 0, 1)
        before = self.counts(self.day, 'replay_history')
        for revision_id, grade, beats in (
            (999, 0, 2), (revision, 1, 2), (revision, 0, -1),
            (revision, '-1/2', 1), (revision, '1/0', 1),
            (revision, 0.5, 1), (revision, True, 1),
            (revision, 0, True), (revision, 0, '2'), (True, 0, 1),
        ):
            with self.subTest(revision_id=revision_id, grade=grade, beats=beats):
                with self.assertRaises(InvalidReplay):
                    preview(self.catalog, self.history, revision_id, grade, beats)
        self.assertEqual(self.counts(self.day, 'replay_history'), before)
        self.assertEqual(self.history.get(previous.record_id), previous)

    def test_gap(self):
        revision = self.enroll(sample('old'))
        broken = sample('old')
        broken['states']['private-sort-28'][0]['upper'] = '1/3'
        with self.assertRaises(InvalidRules):
            self.enroll(broken)
        self.assertEqual(self.catalog.current_revision('R-17').revision_id, revision)
        self.assertEqual(self.counts(self.day, 'rule_revisions', 'current_rules'), (1, 1))
        replay = preview(self.catalog, self.history, revision, '5/12', 3)
        self.assertEqual(replay.trace.actions, ('进站', '返检'))
        self.assertEqual(replay.trace.ended_at, 3)

    def test_history_binding(self):
        revision = self.enroll(sample('old'))
        recorded = preview(self.catalog, self.history, revision, '1/4', 3)
        broken = sample('old')
        broken['states']['private-sort-28'][1]['lower'] = '2/3'
        with self.assertRaises(InvalidRules):
            self.enroll(broken)
        corrected = self.enroll(sample('swapped'))
        self.assertEqual(self.catalog.current_revision('R-17').revision_id, corrected)
        self.assertNotEqual(corrected, revision)
        self.assertEqual(self.history.get(recorded.record_id), recorded)
        self.assertEqual(recorded.revision_id, revision)
        self.assertEqual(recorded.trace.actions, ('进站', '返检'))
        self.assertEqual(recorded.trace.ended_at, 3)
        now = preview(self.catalog, self.history, corrected, '1/4', 3)
        self.assertEqual(now.trace.actions, ('进站', '留线'))
        self.assertEqual(self.counts(self.day, 'rule_revisions', 'replay_history'), (2, 2))

    def test_bad_rules_do_not_promote(self):
        revision = self.enroll(sample('old'))
        overlap = sample('old')
        overlap['states']['private-sort-28'][0]['upper'] = '2/3'
        unknown = sample('old')
        unknown['states']['private-sort-28'][0]['next'] = 'missing'
        bad_start = sample('old')
        bad_start['start'] = 'missing'
        terminal_rows = sample('old')
        terminal_rows['terminals'].append('private-sort-28')
        for malformed in (overlap, unknown, bad_start, terminal_rows):
            with self.subTest(malformed=malformed):
                with self.assertRaises(InvalidRules):
                    self.enroll(malformed)
        self.assertEqual(self.catalog.current_revision('R-17').revision_id, revision)
        self.assertEqual(self.counts(self.day, 'rule_revisions'), (1,))

    def test_failed_promotion_rolls_back_revision(self):
        old = self.enroll(sample('old'))
        self.day.execute('''CREATE TRIGGER block_promotion BEFORE UPDATE ON current_rules
                            BEGIN SELECT RAISE(ABORT, 'promotion blocked'); END''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'promotion blocked'):
            self.enroll(sample('swapped'))
        self.assertEqual(self.catalog.current_revision('R-17').revision_id, old)
        self.assertEqual(self.counts(self.day, 'rule_revisions', 'current_rules'), (1, 1))
