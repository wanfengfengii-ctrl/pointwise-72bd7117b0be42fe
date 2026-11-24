from hmac import compare_digest
import re

from issue.codec import InvalidPacketEncoding, decode_packet
from issue.envelope import IssueEnvelope, V1, packet_digest
from issue.evidence import read_evidence
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
