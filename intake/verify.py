from hmac import compare_digest
from fractions import Fraction
import re

from issue.codec import InvalidPacketEncoding, decode_packet
from issue.envelope import IssueEnvelope, V1, packet_digest
from issue.evidence import read_evidence
from issue.window import (
    check_window_proof,
    decode_window_packet,
    intersects,
    parse_credential,
    segment_digest,
    window_signed_payload,
)
from labdb import is_record_number


class InvalidPacket(ValueError):
    pass


def verify_packet(raw: bytes) -> IssueEnvelope:
    try:
        fields = decode_packet(raw)
    except InvalidPacketEncoding as error:
        raise InvalidPacket(str(error)) from error
    if type(fields['version']) is not int or fields['version'] != V1:
        raise InvalidPacket('unsupported packet version')
    if any(
        not isinstance(fields[key], str) or not fields[key].strip()
        for key in ('station', 'rule_code')
    ) or not all(is_record_number(fields[key]) for key in ('issue_id', 'revision_id')):
        raise InvalidPacket('invalid issuance identity or revision source')
    digest = fields['digest']
    if not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
        raise InvalidPacket('invalid packet digest format')
    envelope = IssueEnvelope.from_fields(fields)
    if not compare_digest(digest, packet_digest(envelope)):
        raise InvalidPacket('packet digest does not match content and source')
    try:
        read_evidence(envelope.body)
    except ValueError as error:
        raise InvalidPacket(f'invalid public evidence: {error}') from error
    return envelope


def verify_window_packet(
    raw: bytes,
    station: str,
    issue_id: int,
    window: tuple,
    credential_bytes: bytes,
) -> dict:
    """Verify one window delivery against the request and the pinned credential.

    Return the decoded packet fields only when the requested station, issue
    number, revision and window all match, the proof was produced under the
    pinned key, and the delivered segments are exactly the original segments
    that share a positive length with the window.
    """
    credential = parse_credential(credential_bytes)
    if credential.station != station or credential.issue_id != issue_id:
        raise InvalidPacket('pinned credential does not match the requested issuance')
    try:
        fields = decode_window_packet(raw)
    except ValueError as error:
        raise InvalidPacket(f'malformed window packet: {error}') from error
    if fields['station'] != station or fields['issue_id'] != issue_id:
        raise InvalidPacket('window packet identity does not match the request')
    if (
        fields['rule_code'] != credential.rule_code
        or fields['revision_id'] != credential.revision_id
    ):
        raise InvalidPacket('window packet source does not match the pinned credential')
    low, high = window
    if (fields['body']['window'][0], fields['body']['window'][1]) != (str(low), str(high)):
        raise InvalidPacket('window packet was produced for a different window')
    signed = window_signed_payload(
        fields['station'],
        fields['issue_id'],
        fields['rule_code'],
        fields['revision_id'],
        window,
        fields['body']['traces'],
    )
    try:
        check_window_proof(credential.key, signed, fields['body']['proof'])
    except ValueError as error:
        raise InvalidPacket(str(error)) from error

    expected = [
        (lower, upper, digest)
        for lower, upper, digest in credential.segments
        if intersects(lower, upper, low, high)
    ]
    delivered = fields['body']['traces']
    if len(delivered) != len(expected):
        raise InvalidPacket('window packet does not deliver exactly the intersecting segments')
    for row, (lower, upper, digest) in zip(delivered, expected):
        if (Fraction(row['lower']), Fraction(row['upper'])) != (lower, upper):
            raise InvalidPacket('window packet segment boundary is not the original boundary')
        if segment_digest(row) != digest:
            raise InvalidPacket('window packet segment contents do not match the credential')
    return fields

