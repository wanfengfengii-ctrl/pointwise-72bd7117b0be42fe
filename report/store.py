from dataclasses import asdict, dataclass
from fractions import Fraction
import json
import sqlite3

from intake.receipt import IntakeReceipt
from labdb import initialize, is_record_number, write_transaction


@dataclass(frozen=True)
class ReportDraft:
    parents: tuple[IntakeReceipt, IntakeReceipt]
    first_differences: tuple[tuple[int, Fraction], ...]
    always_same: Fraction
    window: tuple[Fraction, Fraction] | None = None


@dataclass(frozen=True)
class ReportReceipt:
    report_id: int
    parents: tuple[IntakeReceipt, IntakeReceipt]


@dataclass(frozen=True)
class SignedReport:
    report_id: int
    draft: ReportDraft
    receipt: ReportReceipt


def _parents_from_json(parents: list[dict]) -> tuple[IntakeReceipt, IntakeReceipt]:
    left, right = parents
    return IntakeReceipt(**left), IntakeReceipt(**right)


class ReportStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        initialize(
            connection,
            '''CREATE TABLE IF NOT EXISTS reports (
                report_id INTEGER PRIMARY KEY,
                draft TEXT NOT NULL
            )''',
            '''CREATE TABLE IF NOT EXISTS report_receipts (
                report_id INTEGER PRIMARY KEY REFERENCES reports(report_id),
                parents TEXT NOT NULL
            )''',
        )

    def commit(self, draft: ReportDraft) -> SignedReport:
        parents = [asdict(parent) for parent in draft.parents]
        stored = {
            'parents': parents,
            'first_differences': [(beat, str(mass)) for beat, mass in draft.first_differences],
            'always_same': str(draft.always_same),
        }
        if draft.window is not None:
            stored['window'] = [str(draft.window[0]), str(draft.window[1])]
        encoded = json.dumps(stored, ensure_ascii=False)
        with write_transaction(self.connection):
            cursor = self.connection.execute('INSERT INTO reports (draft) VALUES (?)', (encoded,))
            receipt = ReportReceipt(cursor.lastrowid, draft.parents)
            self.connection.execute(
                'INSERT INTO report_receipts (report_id, parents) VALUES (?, ?)',
                (receipt.report_id, json.dumps(parents, ensure_ascii=False)),
            )
        return SignedReport(receipt.report_id, draft, receipt)

    def get(self, report_id: int) -> SignedReport | None:
        if not is_record_number(report_id):
            return None
        row = self.connection.execute(
            '''SELECT r.draft, s.parents FROM reports AS r
               JOIN report_receipts AS s USING (report_id)
               WHERE r.report_id = ?''',
            (report_id,),
        ).fetchone()
        if row is None:
            return None
        stored = json.loads(row[0])
        window = None
        if 'window' in stored:
            window = (Fraction(stored['window'][0]), Fraction(stored['window'][1]))
        draft = ReportDraft(
            _parents_from_json(stored['parents']),
            tuple((beat, Fraction(mass)) for beat, mass in stored['first_differences']),
            Fraction(stored['always_same']),
            window,
        )
        receipt = ReportReceipt(report_id, _parents_from_json(json.loads(row[1])))
        return SignedReport(report_id, draft, receipt)
