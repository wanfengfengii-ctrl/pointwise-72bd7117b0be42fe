"""Formats and cryptography shared by window issuance and window intake.

The credential is an opaque byte string handed over through the trusted shift
channel.  It carries the identity of the issuance, a random MAC key and one
digest per *original* grade segment.  Digests and segment boundaries are not
decodable traces, so no out-of-window behaviour can be read out of it.
"""

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from hmac import compare_digest, new as hmac_new
import json
import os
import re

from issue.codec import encode_payload
from labdb import is_record_number
from rules.grade import parse_rational


WINDOW_VERSION = 2
CREDENTIAL_SCHEME = 'window-credential-v1'
PROOF_SCHEME = 'hmac-sha256-v2'

_HEX64 = re.compile(r'[0-9a-f]{64}')


@dataclass(frozen=True)
class Credential:
    station: str
    issue_id: int
    rule_code: str
    revision_id: int
    key: bytes
    segments: tuple[tuple[Fraction, Fraction, str], ...]


def require_window(lo: object, hi: object) -> tuple[Fraction, Fraction]:
    """Parse and validate a half-open rational window ``[lo, hi)``."""
    low = parse_rational(lo)
    high = parse_rational(hi)
    if not 0 <= low < high <= 1:
        raise ValueError('window must satisfy 0 <= lo < hi <= 1')
    return low, high


def window_strings(window: tuple[Fraction, Fraction]) -> list[str]:
    return [str(window[0]), str(window[1])]


def trace_row(trace) -> dict:
    """Return the canonical public row for one original segment."""
    return {
        'lower': str(trace.band.lower),
        'upper': str(trace.band.upper),
        'actions': list(trace.actions),
        'repeat_from': trace.repeat_from,
    }


def segment_digest(row: dict) -> str:
    return sha256(encode_payload(row)).hexdigest()


def intersects(lower: Fraction, upper: Fraction, lo: Fraction, hi: Fraction) -> bool:
    """True exactly when the half-open segment shares a positive length with the window."""
    return max(lower, lo) < min(upper, hi)


def read_window_rows(rows: object) -> tuple[dict, ...]:
    """Validate an ordered list of original segments supplied in a packet."""
    if not isinstance(rows, list) or not rows:
        raise ValueError('window traces must be a nonempty list')
    parsed = []
    cursor = Fraction(0)
    for row in rows:
        if not isinstance(row, dict) or row.keys() != {
            'lower', 'upper', 'actions', 'repeat_from'
        }:
            raise ValueError('invalid window trace fields')
        lower = _canonical_bound(row['lower'], 'trace lower')
        upper = _canonical_bound(row['upper'], 'trace upper')
        if not 0 <= lower < upper <= 1:
            raise ValueError('window trace bounds must be nonempty and within [0, 1)')
        if lower < cursor:
            raise ValueError('window traces must be disjoint and ordered')
        actions = row['actions']
        if not isinstance(actions, list) or any(
            not isinstance(action, str) or not action.strip() for action in actions
        ):
            raise ValueError('window trace actions must be public action codes')
        repeat = row['repeat_from']
        if repeat is not None and (type(repeat) is not int or not 0 <= repeat < len(actions)):
            raise ValueError('invalid window trace cycle entry')
        cursor = upper
        parsed.append(
            {
                'lower': str(lower),
                'upper': str(upper),
                'actions': list(actions),
                'repeat_from': repeat,
            }
        )
    return tuple(parsed)


def decode_window_packet(raw: object) -> dict:
    """Decode a canonical version 2 window packet without trusting its proof."""
    if not isinstance(raw, bytes):
        raise ValueError('window packet must be UTF-8 bytes')
    try:
        fields = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, RecursionError, ValueError) as error:
        raise ValueError('window packet is not decodable JSON') from error
    if not isinstance(fields, dict) or fields.keys() != {
        'version', 'station', 'issue_id', 'rule_code', 'revision_id', 'body'
    }:
        raise ValueError('invalid window envelope fields')
    if encode_payload(fields) != raw:
        raise ValueError('window packet encoding is not canonical')
    if type(fields['version']) is not int or fields['version'] != WINDOW_VERSION:
        raise ValueError('unsupported window packet version')
    if not isinstance(fields['station'], str) or not fields['station'].strip():
        raise ValueError('invalid window packet station')
    if not isinstance(fields['rule_code'], str) or not fields['rule_code'].strip():
        raise ValueError('invalid window packet rule code')
    if not is_record_number(fields['issue_id']) or not is_record_number(fields['revision_id']):
        raise ValueError('invalid window packet identity')
    body = fields['body']
    if not isinstance(body, dict) or body.keys() != {'window', 'traces', 'proof'}:
        raise ValueError('invalid window packet body')
    window = body['window']
    if (
        not isinstance(window, list) or len(window) != 2
        or not all(isinstance(bound, str) for bound in window)
    ):
        raise ValueError('invalid window bounds')
    low = _canonical_bound(window[0], 'window lower')
    high = _canonical_bound(window[1], 'window upper')
    if not 0 <= low < high <= 1:
        raise ValueError('window must satisfy 0 <= lo < hi <= 1')
    body['traces'] = list(read_window_rows(body['traces']))
    return fields


def rows_to_traces(rows) -> tuple:
    """Rebuild public grade traces from canonical window rows."""
    from issue.evidence import GradeTrace
    from rules.grade import GradeBand

    return tuple(
        GradeTrace(
            GradeBand(Fraction(row['lower']), Fraction(row['upper'])),
            tuple(row['actions']),
            row['repeat_from'],
        )
        for row in rows
    )


def build_credential(
    station: str,
    issue_id: int,
    rule_code: str,
    revision_id: int,
    traces: tuple,
) -> bytes:
    return encode_payload(
        {
            'scheme': CREDENTIAL_SCHEME,
            'station': station,
            'issue_id': issue_id,
            'rule_code': rule_code,
            'revision_id': revision_id,
            'key': os.urandom(32).hex(),
            'segments': [
                [str(trace.band.lower), str(trace.band.upper), segment_digest(trace_row(trace))]
                for trace in traces
            ],
        }
    )


def _canonical_bound(value: object, name: str) -> Fraction:
    if not isinstance(value, str):
        raise ValueError(f'{name} must be a rational string')
    bound = parse_rational(value)
    if str(bound) != value:
        raise ValueError(f'{name} must be in canonical form')
    return bound


def parse_credential(raw: object) -> Credential:
    if not isinstance(raw, bytes):
        raise ValueError('credential must be bytes')
    try:
        data = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError('credential is not a canonical JSON value') from error
    required = {'scheme', 'station', 'issue_id', 'rule_code', 'revision_id', 'key', 'segments'}
    if not isinstance(data, dict) or data.keys() != required:
        raise ValueError('invalid credential fields')
    if data['scheme'] != CREDENTIAL_SCHEME:
        raise ValueError('unsupported credential scheme')
    if not isinstance(data['station'], str) or not data['station'].strip():
        raise ValueError('invalid credential station')
    if not isinstance(data['rule_code'], str) or not data['rule_code'].strip():
        raise ValueError('invalid credential rule code')
    if not is_record_number(data['issue_id']) or not is_record_number(data['revision_id']):
        raise ValueError('invalid credential issuance identity')
    key = data['key']
    if not isinstance(key, str) or _HEX64.fullmatch(key) is None:
        raise ValueError('invalid credential key')
    raw_segments = data['segments']
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError('invalid credential segment list')
    segments = []
    cursor = Fraction(0)
    for entry in raw_segments:
        if not isinstance(entry, list) or len(entry) != 3:
            raise ValueError('invalid credential segment entry')
        lower = _canonical_bound(entry[0], 'segment lower')
        upper = _canonical_bound(entry[1], 'segment upper')
        digest = entry[2]
        if not isinstance(digest, str) or _HEX64.fullmatch(digest) is None:
            raise ValueError('invalid credential segment digest')
        if not 0 <= lower < upper <= 1 or lower != cursor:
            raise ValueError('credential segments must partition [0, 1)')
        cursor = upper
        segments.append((lower, upper, digest))
    if cursor != 1:
        raise ValueError('credential segments must partition [0, 1)')
    return Credential(
        data['station'],
        data['issue_id'],
        data['rule_code'],
        data['revision_id'],
        bytes.fromhex(key),
        tuple(segments),
    )


def window_signed_payload(
    station: str,
    issue_id: int,
    rule_code: str,
    revision_id: int,
    window: tuple[Fraction, Fraction],
    rows: list[dict],
) -> bytes:
    return encode_payload(
        {
            'version': WINDOW_VERSION,
            'station': station,
            'issue_id': issue_id,
            'rule_code': rule_code,
            'revision_id': revision_id,
            'window': window_strings(window),
            'traces': rows,
        }
    )


def make_window_proof(key: bytes, signed: bytes) -> dict:
    return {
        'scheme': PROOF_SCHEME,
        'mac': hmac_new(key, signed, sha256).hexdigest(),
    }


def check_window_proof(key: bytes, signed: bytes, proof: object) -> None:
    if not isinstance(proof, dict) or proof.keys() != {'scheme', 'mac'}:
        raise ValueError('invalid window packet proof')
    if proof['scheme'] != PROOF_SCHEME:
        raise ValueError('unsupported window packet proof')
    mac = proof['mac']
    if not isinstance(mac, str) or _HEX64.fullmatch(mac) is None:
        raise ValueError('invalid window packet proof')
    if not compare_digest(mac, make_window_proof(key, signed)['mac']):
        raise ValueError('window packet proof does not match the pinned credential')
