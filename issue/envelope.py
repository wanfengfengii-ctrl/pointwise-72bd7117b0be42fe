from dataclasses import dataclass, replace
from hashlib import sha256
import json

from issue.codec import encode_payload


V1 = 1


@dataclass(frozen=True)
class IssueEnvelope:
    version: int
    station: str
    issue_id: int
    rule_code: str
    revision_id: int
    body: bytes
    digest: str

    def binding_fields(self) -> dict:
        return {
            'version': self.version,
            'station': self.station,
            'issue_id': self.issue_id,
            'rule_code': self.rule_code,
            'revision_id': self.revision_id,
            'body': json.loads(self.body),
        }

    @classmethod
    def from_fields(cls, fields: dict) -> 'IssueEnvelope':
        return cls(
            fields['version'],
            fields['station'],
            fields['issue_id'],
            fields['rule_code'],
            fields['revision_id'],
            encode_payload(fields['body']),
            fields['digest'],
        )


def packet_digest(envelope: IssueEnvelope) -> str:
    return sha256(encode_payload(envelope.binding_fields())).hexdigest()


def seal_envelope(
    station: str, issue_id: int, rule_code: str, revision_id: int, payload: dict
) -> IssueEnvelope:
    unsigned = IssueEnvelope(V1, station, issue_id, rule_code, revision_id, encode_payload(payload), '')
    return replace(unsigned, digest=packet_digest(unsigned))
