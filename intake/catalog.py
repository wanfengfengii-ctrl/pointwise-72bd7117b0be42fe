from dataclasses import dataclass
import sqlite3

from intake.receipt import IntakeReceipt, make_intake_receipt
from issue.codec import decode_packet, encode_packet
from issue.envelope import IssueEnvelope
from labdb import initialize, is_record_number, write_transaction


@dataclass(frozen=True)
class AcceptedPacket:
    envelope: IssueEnvelope
    receipt: IntakeReceipt

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
