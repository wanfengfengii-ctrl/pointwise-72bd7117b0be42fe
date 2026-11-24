import sqlite3

from issue.codec import decode_packet, encode_packet
from issue.envelope import IssueEnvelope, seal_envelope
from issue.window import build_credential
from labdb import is_record_number, write_transaction
from rules.revisions import RuleRevision


class IssueRegister:
    def __init__(self, connection: sqlite3.Connection, station: str):
        if not isinstance(station, str) or not station.strip():
            raise ValueError('station must be nonempty text')
        station.encode('utf-8')
        self.connection = connection
        with write_transaction(connection):
            connection.execute(
                '''CREATE TABLE IF NOT EXISTS issue_station (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    station TEXT NOT NULL
                )'''
            )
            connection.execute(
                '''CREATE TABLE IF NOT EXISTS issued_packets (
                    issue_id INTEGER PRIMARY KEY,
                    revision_id INTEGER NOT NULL REFERENCES rule_revisions(revision_id),
                    packet BLOB NOT NULL
                )'''
            )
            connection.execute(
                '''CREATE TABLE IF NOT EXISTS window_issues (
                    issue_id INTEGER PRIMARY KEY REFERENCES issued_packets(issue_id),
                    revision_id INTEGER NOT NULL REFERENCES rule_revisions(revision_id),
                    credential BLOB NOT NULL
                )'''
            )
            connection.execute(
                'INSERT OR IGNORE INTO issue_station (singleton, station) VALUES (1, ?)',
                (station,),
            )
            saved_station = connection.execute(
                'SELECT station FROM issue_station WHERE singleton = 1'
            ).fetchone()[0]
            if saved_station != station:
                raise ValueError('station differs from the registered issuance station')
        self.station = station

    def record(self, revision: RuleRevision, payload: dict) -> IssueEnvelope:
        with write_transaction(self.connection):
            issue_id = self.connection.execute(
                'SELECT COALESCE(MAX(issue_id), 0) + 1 FROM issued_packets'
            ).fetchone()[0]
            envelope = seal_envelope(
                self.station, issue_id, revision.definition.code, revision.revision_id, payload
            )
            self.connection.execute(
                'INSERT INTO issued_packets (issue_id, revision_id, packet) VALUES (?, ?, ?)',
                (issue_id, revision.revision_id, encode_packet(envelope)),
            )
        return envelope

    def record_window(
        self, revision: RuleRevision, payload: dict, traces: tuple
    ) -> tuple[IssueEnvelope, int, bytes]:
        """Record a window-capable issuance and mint its opaque credential."""
        with write_transaction(self.connection):
            issue_id = self.connection.execute(
                'SELECT COALESCE(MAX(issue_id), 0) + 1 FROM issued_packets'
            ).fetchone()[0]
            envelope = seal_envelope(
                self.station, issue_id, revision.definition.code, revision.revision_id, payload
            )
            credential = build_credential(
                self.station, issue_id, revision.definition.code,
                revision.revision_id, traces,
            )
            self.connection.execute(
                'INSERT INTO issued_packets (issue_id, revision_id, packet) VALUES (?, ?, ?)',
                (issue_id, revision.revision_id, encode_packet(envelope)),
            )
            self.connection.execute(
                'INSERT INTO window_issues (issue_id, revision_id, credential) VALUES (?, ?, ?)',
                (issue_id, revision.revision_id, credential),
            )
        return envelope, issue_id, credential

    def is_window_issue(self, issue_id: int) -> bool:
        return self.get_window_credential(issue_id) is not None

    def get_window_credential(self, issue_id: int) -> bytes | None:
        if not is_record_number(issue_id):
            return None
        row = self.connection.execute(
            'SELECT credential FROM window_issues WHERE issue_id = ?', (issue_id,)
        ).fetchone()
        return bytes(row[0]) if row is not None else None

    def get(self, issue_id: int) -> IssueEnvelope | None:
        if not is_record_number(issue_id):
            return None
        row = self.connection.execute(
            'SELECT packet FROM issued_packets WHERE issue_id = ?', (issue_id,)
        ).fetchone()
        return IssueEnvelope.from_fields(decode_packet(row[0])) if row is not None else None
