from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from intake.catalog import IntakeCatalog
from intake.receive import receive
from issue.codec import encode_packet
from issue.freeze import freeze
from issue.register import IssueRegister
from labdb import open_database
from report.store import ReportStore
from rules.catalog import RuleCatalog
from rules.importer import register
from trial.history import ReplayHistory


SAMPLES = Path(__file__).resolve().parents[1] / 'samples'


def sample(name):
    return json.loads((SAMPLES / f'{name}.json').read_text(encoding='utf-8'))


def with_cut(rules, cut):
    changed = deepcopy(rules)
    branches = next(rows for rows in changed['states'].values() if len(rows) == 2)
    branches[0]['upper'] = cut
    branches[1]['lower'] = cut
    return changed


def chain(actions, repeat_from=None):
    states = {}
    for index, action in enumerate(actions):
        if index + 1 < len(actions):
            next_state = f's{index + 1}'
        else:
            next_state = 'done' if repeat_from is None else f's{repeat_from}'
        states[f's{index}'] = [transition(action, next_state)]
    return {'start': 's0' if actions else 'done', 'terminals': ['done'], 'states': states}


def transition(action, next_state, lower='0', upper='1'):
    return {'lower': lower, 'upper': upper, 'action': action, 'next': next_state}


class LedgerCase(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory(prefix='repair-tests-')))
        self.day_path = directory / 'day.sqlite3'
        self.night_path = directory / 'night.sqlite3'
        self.open_day()
        self.open_night()

    def open_day(self):
        self.day = open_database(self.day_path)
        self.addCleanup(self.day.close)
        self.catalog = RuleCatalog(self.day)
        self.history = ReplayHistory(self.day)
        self.issues = IssueRegister(self.day, 'repair-test')

    def open_night(self):
        self.night = open_database(self.night_path)
        self.addCleanup(self.night.close)
        self.intake = IntakeCatalog(self.night)
        self.store = ReportStore(self.night)

    def isolate_source(self):
        self.day.close()
        self.day_path.rename(self.day_path.with_suffix('.closed'))
        self.assertFalse(self.day_path.exists())

    def enroll(self, rules):
        return register(self.catalog, 'R-17', rules)

    def issue(self, revision_id):
        return freeze(self.catalog, self.issues, revision_id)

    def accept(self, revision_id):
        return receive(self.intake, encode_packet(self.issue(revision_id)))

    def receive_pair(self, left, right):
        return self.accept(self.enroll(left)), self.accept(self.enroll(right))

    def counts(self, connection, *tables):
        return tuple(
            connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            for table in tables
        )

    def intake_counts(self):
        return self.counts(self.night, 'received_packets', 'intake_receipts')

    def report_counts(self):
        return self.counts(self.night, 'reports', 'report_receipts')
