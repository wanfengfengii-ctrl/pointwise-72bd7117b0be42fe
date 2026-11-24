from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
import sqlite3

from intake.receipt import IntakeReceipt, make_intake_receipt
from issue.codec import decode_packet, encode_packet
from issue.envelope import IssueEnvelope
from issue.window import parse_credential
from labdb import initialize, is_record_number, write_transaction


@dataclass(frozen=True)
class AcceptedPacket:
    envelope: IssueEnvelope
    receipt: IntakeReceipt

    @property
    def intake_id(self) -> int:
        return self.receipt.intake_id


@dataclass(frozen=True)
class WindowIntake:
    """A verified window delivery together with its request window."""

    receipt: IntakeReceipt
    window: tuple[Fraction, Fraction]
    traces: tuple[dict, ...]
    rule_code: str
    revision_id: int

    @property
    def intake_id(self) -> int:
        return self.receipt.intake_id


class IntakeCatalog:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        initialize(
            connection,
            '''CREATE TABLE IF NOT EXISTS received_packets (
                intake_id INTEGER PRIMARY KEY,
                packet BLOB NOT NULL
            )''',
            '''CREATE TABLE IF NOT EXISTS intake_receipts (
                intake_id INTEGER PRIMARY KEY REFERENCES received_packets(intake_id),
                station TEXT NOT NULL,
                issue_id INTEGER NOT NULL,
                rule_code TEXT NOT NULL,
                revision_id INTEGER NOT NULL,
                digest TEXT NOT NULL
            )''',
            '''CREATE TABLE IF NOT EXISTS pinned_window_issues (
                station TEXT NOT NULL,
                issue_id INTEGER NOT NULL,
                credential BLOB NOT NULL,
                PRIMARY KEY (station, issue_id)
            )''',
            '''CREATE TABLE IF NOT EXISTS window_intakes (
                intake_id INTEGER PRIMARY KEY REFERENCES received_packets(intake_id),
                lo TEXT NOT NULL,
                hi TEXT NOT NULL
            )''',
        )

    def accept(self, envelope: IssueEnvelope) -> AcceptedPacket:
        encoded = encode_packet(envelope)
        with write_transaction(self.connection):
            cursor = self.connection.execute(
                'INSERT INTO received_packets (packet) VALUES (?)', (encoded,)
            )
            receipt = make_intake_receipt(cursor.lastrowid, envelope)
            self.connection.execute(
                '''INSERT INTO intake_receipts
                   (intake_id, station, issue_id, rule_code, revision_id, digest)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (
                    receipt.intake_id, receipt.station, receipt.issue_id,
                    receipt.rule_code, receipt.revision_id, receipt.digest,
                ),
            )
        return AcceptedPacket(envelope, receipt)

    def pin(self, station: str, issue_id: int, credential: bytes) -> None:
        pinned = parse_credential(credential)
        if pinned.station != station or pinned.issue_id != issue_id:
            raise ValueError('credential does not match the pinned station and issue number')
        with write_transaction(self.connection):
            row = self.connection.execute(
                'SELECT credential FROM pinned_window_issues WHERE station = ? AND issue_id = ?',
                (station, issue_id),
            ).fetchone()
            if row is not None:
                if bytes(row[0]) != credential:
                    raise ValueError('conflicting pin for this station and issue number')
                return
            self.connection.execute(
                '''INSERT INTO pinned_window_issues (station, issue_id, credential)
                   VALUES (?, ?, ?)''',
                (station, issue_id, credential),
            )

    def get_pin(self, station: str, issue_id: int) -> bytes | None:
        if not isinstance(station, str) or not is_record_number(issue_id):
            return None
        row = self.connection.execute(
            'SELECT credential FROM pinned_window_issues WHERE station = ? AND issue_id = ?',
            (station, issue_id),
        ).fetchone()
        return bytes(row[0]) if row is not None else None

    def accept_window(
        self,
        fields: dict,
        raw: bytes,
        window: tuple[Fraction, Fraction],
    ) -> IntakeReceipt:
        digest = sha256(raw).hexdigest()
        with write_transaction(self.connection):
            cursor = self.connection.execute(
                'INSERT INTO received_packets (packet) VALUES (?)', (raw,)
            )
            intake_id = cursor.lastrowid
            receipt = IntakeReceipt(
                intake_id,
                fields['station'],
                fields['issue_id'],
                fields['rule_code'],
                fields['revision_id'],
                digest,
            )
            self.connection.execute(
                '''INSERT INTO intake_receipts
                   (intake_id, station, issue_id, rule_code, revision_id, digest)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (
                    receipt.intake_id, receipt.station, receipt.issue_id,
                    receipt.rule_code, receipt.revision_id, receipt.digest,
                ),
            )
            self.connection.execute(
                'INSERT INTO window_intakes (intake_id, lo, hi) VALUES (?, ?, ?)',
                (intake_id, str(window[0]), str(window[1])),
            )
        return receipt

    def get(self, intake_id: int) -> AcceptedPacket | None:
        if not is_record_number(intake_id):
            return None
        row = self.connection.execute(
            '''SELECT p.packet, r.intake_id, r.station, r.issue_id, r.rule_code,
                      r.revision_id, r.digest
               FROM received_packets AS p JOIN intake_receipts AS r USING (intake_id)
               WHERE p.intake_id = ?''',
            (intake_id,),
        ).fetchone()
        if row is None:
            return None
        envelope = IssueEnvelope.from_fields(decode_packet(row[0]))
        return AcceptedPacket(envelope, IntakeReceipt(*row[1:]))

    def get_window(self, intake_id: int) -> WindowIntake | None:
        if not is_record_number(intake_id):
            return None
        row = self.connection.execute(
            '''SELECT p.packet, r.intake_id, r.station, r.issue_id, r.rule_code,
                      r.revision_id, r.digest, w.lo, w.hi
               FROM received_packets AS p
               JOIN intake_receipts AS r USING (intake_id)
               JOIN window_intakes AS w USING (intake_id)
               WHERE p.intake_id = ?''',
            (intake_id,),
        ).fetchone()
        if row is None:
            return None
        from issue.window import decode_window_packet

        fields = decode_window_packet(bytes(row[0]))
        receipt = IntakeReceipt(*row[1:7])
        window = (Fraction(row[7]), Fraction(row[8]))
        return WindowIntake(
            receipt,
            window,
            tuple(fields['body']['traces']),
            fields['rule_code'],
            fields['revision_id'],
        )
