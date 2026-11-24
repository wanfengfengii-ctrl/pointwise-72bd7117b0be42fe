import sqlite3

from labdb import initialize, is_record_number, write_transaction
from rules.revisions import RuleDefinition, RuleRevision, decode_revision, encode_revision


class RuleCatalog:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        initialize(
            connection,
            '''CREATE TABLE IF NOT EXISTS rule_revisions (
                revision_id INTEGER PRIMARY KEY,
                rule_code TEXT NOT NULL,
                definition TEXT NOT NULL
            )''',
            '''CREATE TABLE IF NOT EXISTS current_rules (
                rule_code TEXT PRIMARY KEY,
                revision_id INTEGER NOT NULL REFERENCES rule_revisions(revision_id)
            )''',
        )

    def append_revision(self, definition: RuleDefinition) -> int:
        encoded = encode_revision(definition)
        with write_transaction(self.connection):
            result = self.connection.execute(
                'INSERT INTO rule_revisions (rule_code, definition) VALUES (?, ?)',
                (definition.code, encoded),
            )
            revision_id = result.lastrowid
            self.connection.execute(
                '''INSERT INTO current_rules (rule_code, revision_id) VALUES (?, ?)
                   ON CONFLICT(rule_code) DO UPDATE SET revision_id = excluded.revision_id''',
                (definition.code, revision_id),
            )
        return revision_id

    def get_revision(self, revision_id: int) -> RuleRevision | None:
        if not is_record_number(revision_id):
            return None
        row = self.connection.execute(
            '''SELECT revision_id, rule_code, definition FROM rule_revisions
               WHERE revision_id = ?''',
            (revision_id,),
        ).fetchone()
        return decode_revision(*row) if row is not None else None

    def current_revision(self, rule_code: str) -> RuleRevision | None:
        row = self.connection.execute(
            '''SELECT r.revision_id, r.rule_code, r.definition
               FROM current_rules AS c JOIN rule_revisions AS r USING (revision_id)
               WHERE c.rule_code = ?''',
            (rule_code,),
        ).fetchone()
        return decode_revision(*row) if row is not None else None
