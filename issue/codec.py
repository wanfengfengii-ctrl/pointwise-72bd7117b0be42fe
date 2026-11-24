from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from issue.envelope import IssueEnvelope


class InvalidPacketEncoding(ValueError):
    pass


def encode_payload(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        allow_nan=False,
    ).encode('utf-8')


def encode_packet(packet: IssueEnvelope) -> bytes:
    fields = packet.binding_fields()
    fields['digest'] = packet.digest
    return encode_payload(fields)


def decode_packet(raw: bytes) -> dict:
    if not isinstance(raw, bytes):
        raise InvalidPacketEncoding('packet must be UTF-8 bytes')
    try:
        fields = json.loads(raw.decode('utf-8'))
        if not isinstance(fields, dict) or fields.keys() != {
            'version', 'station', 'issue_id', 'rule_code', 'revision_id', 'body', 'digest'
        }:
            raise ValueError('invalid V1 envelope fields')
        if not isinstance(fields['body'], dict):
            raise ValueError('packet body must be an object')
        if encode_payload(fields) != raw:
            raise ValueError('packet encoding is not canonical')
    except (ValueError, RecursionError) as error:
        raise InvalidPacketEncoding(str(error)) from error
    return fields
