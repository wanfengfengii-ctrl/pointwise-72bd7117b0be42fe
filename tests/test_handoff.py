from collections import defaultdict
from fractions import Fraction
import json
import sqlite3

from intake.receive import receive
from intake.verify import InvalidPacket
from issue.codec import encode_packet, encode_payload
from issue.envelope import seal_envelope
from issue.freeze import UnknownRevision
from tests import LedgerCase, sample


def row_at(envelope, grade):
    matches = [
        row for row in json.loads(envelope.body)['traces']
        if Fraction(row['lower']) <= Fraction(grade) < Fraction(row['upper'])
    ]
    if len(matches) != 1:
        raise AssertionError(f'expected exactly one trace for grade {grade}')
    return matches[0]


def trace_masses(envelope):
    totals = defaultdict(Fraction)
    for row in json.loads(envelope.body)['traces']:
        trace = (tuple(row['actions']), row['repeat_from'])
        totals[trace] += Fraction(row['upper']) - Fraction(row['lower'])
    return dict(totals)


class TestHandoff(LedgerCase):
    def test_freeze_selected(self):
        old = self.enroll(sample('old'))
        corrected = self.enroll(sample('swapped'))
        self.assertEqual(self.catalog.current_revision('R-17').revision_id, corrected)
        packet = self.issue(old)
        accepted = receive(self.intake, encode_packet(packet))
        original_row = row_at(accepted.envelope, '1/4')
        self.assertEqual(original_row['actions'], ['进站', '返检'])
        self.assertEqual(accepted.receipt.revision_id, old)
        self.assertEqual(accepted.receipt.issue_id, packet.issue_id)
        self.assertEqual(accepted.receipt.station, 'repair-test')
        self.assertEqual(accepted.receipt.rule_code, 'R-17')
        self.assertEqual(accepted.receipt.digest, packet.digest)
        self.enroll(sample('aligned'))
        self.assertEqual(self.issues.get(packet.issue_id), packet)
        self.assertEqual(self.intake.get(accepted.intake_id), accepted)

    def test_unknown_revision(self):
        self.issue(self.enroll(sample('old')))
        before = self.counts(self.day, 'issued_packets')
        with self.assertRaises(UnknownRevision):
            self.issue(999)
        self.assertEqual(self.counts(self.day, 'issued_packets'), before)

    def test_public_only(self):
        rules = sample('old')
        accepted = self.accept(self.enroll(rules))
        data = encode_packet(accepted.envelope).decode('utf-8')
        for private_value in (*rules['states'], *rules['terminals'], rules['note']):
            self.assertNotIn(private_value, data)
        self.assertNotIn('note', data)
        row = row_at(accepted.envelope, '1/2')
        self.assertEqual(row['actions'], ['进站', '留线'])
        self.assertIsNone(row['repeat_from'])
        self.assertEqual(len(row['actions']) + 1, 3)

    def test_grade_binding(self):
        aligned = self.accept(self.enroll(sample('aligned'))).envelope
        swapped = self.accept(self.enroll(sample('swapped'))).envelope
        expected_masses = {
            (('进站', '返检'), None): Fraction(1, 2),
            (('进站', '留线'), None): Fraction(1, 2),
        }
        self.assertEqual(trace_masses(aligned), expected_masses)
        self.assertEqual(trace_masses(swapped), expected_masses)
        for grade, a, b in (('1/4', '返检', '留线'), ('1/2', '留线', '返检'), ('3/4', '留线', '返检')):
            with self.subTest(grade=grade):
                self.assertEqual(row_at(aligned, grade)['actions'], ['进站', a])
                self.assertEqual(row_at(swapped, grade)['actions'], ['进站', b])

    def test_tampered_packet(self):
        packet = self.issue(self.enroll(sample('old')))
        receive(self.intake, encode_packet(packet))
        before = self.intake_counts()
        fields = json.loads(encode_packet(packet))
        fields['body']['traces'][0]['actions'][1] = '补检'
        with self.assertRaisesRegex(InvalidPacket, 'digest'):
            receive(self.intake, encode_payload(fields))
        self.assertEqual(self.intake_counts(), before)

    def test_source_binding(self):
        packet = self.issue(self.enroll(sample('old')))
        for key, value in (
            ('revision_id', packet.revision_id + 1), ('issue_id', packet.issue_id + 1),
            ('station', 'another-station'), ('rule_code', 'R-18'),
        ):
            fields = json.loads(encode_packet(packet))
            fields[key] = value
            with self.subTest(field=key):
                with self.assertRaisesRegex(InvalidPacket, 'digest'):
                    receive(self.intake, encode_payload(fields))
        self.assertEqual(self.intake_counts(), (0, 0))

    def test_matching_digest_does_not_validate_bad_evidence(self):
        packet = self.issue(self.enroll(sample('old')))
        for key, value in (('repeat_from', 2), ('lower', '1/4'), ('upper', '2/4')):
            payload = json.loads(packet.body)
            payload['traces'][0][key] = value
            signed = seal_envelope(packet.station, packet.issue_id, packet.rule_code,
                                   packet.revision_id, payload)
            with self.subTest(field=key):
                with self.assertRaisesRegex(InvalidPacket, 'public evidence'):
                    receive(self.intake, encode_packet(signed))
        self.assertEqual(self.intake_counts(), (0, 0))

    def test_intake_receipt_failure_rolls_back_both_writes(self):
        packet = self.issue(self.enroll(sample('old')))
        self.night.execute('''CREATE TRIGGER block_intake BEFORE INSERT ON intake_receipts
                              BEGIN SELECT RAISE(ABORT, 'intake blocked'); END''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'intake blocked'):
            receive(self.intake, encode_packet(packet))
        self.night.close()
        self.open_night()
        self.assertEqual(self.intake_counts(), (0, 0))
        self.night.execute('DROP TRIGGER block_intake')
        accepted = receive(self.intake, encode_packet(packet))
        self.assertEqual(self.intake_counts(), (1, 1))
        self.assertEqual(self.intake.get(accepted.intake_id), accepted)
