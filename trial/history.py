from dataclasses import dataclass
from fractions import Fraction
import json
import sqlite3

from labdb import initialize, is_record_number, write_transaction
from rules.grade import parse_rational
from trial.trace import ReplayTrace


@dataclass(frozen=True)
class ReplayRecord:
    record_id: int
    revision_id: int
    grade: Fraction
    beats: int
    trace: ReplayTrace


class ReplayHistory:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        initialize(
            connection,
            '''CREATE TABLE IF NOT EXISTS replay_history (
                record_id INTEGER PRIMARY KEY,
                revision_id INTEGER NOT NULL REFERENCES rule_revisions(revision_id),
                grade TEXT NOT NULL,
                beats TEXT NOT NULL,
                actions TEXT NOT NULL,
                ended_at TEXT
            )''',
        )

    def record(
        self, revision_id: int, grade: Fraction, beats: int, trace: ReplayTrace
    ) -> ReplayRecord:
        actions = json.dumps(trace.actions, ensure_ascii=False)
        end = str(trace.ended_at) if trace.ended_at is not None else None
        with write_transaction(self.connection):
            cursor = self.connection.execute(
                '''INSERT INTO replay_history (revision_id, grade, beats, actions, ended_at)
                   VALUES (?, ?, ?, ?, ?)''',
                (revision_id, str(grade), str(beats), actions, end),
            )
            record_id = cursor.lastrowid
        return ReplayRecord(record_id, revision_id, grade, beats, trace)

    def get(self, record_id: int) -> ReplayRecord | None:
        if not is_record_number(record_id):
            return None
        row = self.connection.execute(
            '''SELECT revision_id, grade, beats, actions, ended_at FROM replay_history
               WHERE record_id = ?''',
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        revision_id, grade, beats, actions, end = row
        trace = ReplayTrace(tuple(json.loads(actions)), int(end) if end is not None else None)
        return ReplayRecord(record_id, revision_id, parse_rational(grade), int(beats), trace)
