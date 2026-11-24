from issue.codec import encode_payload
from issue.envelope import IssueEnvelope
from issue.evidence import build_evidence, evidence_payload, read_evidence
from issue.register import IssueRegister
from issue.window import (
    WINDOW_VERSION,
    intersects,
    make_window_proof,
    parse_credential,
    require_window,
    trace_row,
    window_signed_payload,
)
from rules.catalog import RuleCatalog


class UnknownRevision(LookupError):
    pass


def freeze(catalog: RuleCatalog, register: IssueRegister, revision_id: int) -> IssueEnvelope:
    revision = catalog.get_revision(revision_id)
    if revision is None:
        raise UnknownRevision(f'unknown rule revision {revision_id!r}')
    payload = evidence_payload(build_evidence(revision.definition))
    return register.record(revision, payload)


def freeze_window(
    catalog: RuleCatalog, register: IssueRegister, revision_id: int
) -> tuple[int, bytes]:
    """Pin the selected revision for later window delivery, returning its credential."""
    revision = catalog.get_revision(revision_id)
    if revision is None:
        raise UnknownRevision(f'unknown rule revision {revision_id!r}')
    traces = build_evidence(revision.definition)
    payload = evidence_payload(traces)
    _, issue_id, credential = register.record_window(revision, payload, traces)
    return issue_id, credential


def make_window_packet(
    register: IssueRegister, issue_id: int, lo: object, hi: object
) -> bytes:
    """Build a delivery for ``[lo, hi)`` from the segments fixed at issuance time."""
    low, high = require_window(lo, hi)
    if not register.is_window_issue(issue_id):
        raise ValueError(f'issue {issue_id!r} was not pinned for window delivery')
    envelope = register.get(issue_id)
    if envelope is None:
        raise ValueError(f'unknown issue number {issue_id!r}')
    credential = parse_credential(register.get_window_credential(issue_id))
    ordered = [
        trace_row(trace)
        for trace in read_evidence(envelope.body)
        if intersects(trace.band.lower, trace.band.upper, low, high)
    ]
    signed = window_signed_payload(
        envelope.station,
        issue_id,
        envelope.rule_code,
        envelope.revision_id,
        (low, high),
        ordered,
    )
    return encode_payload(
        {
            'version': WINDOW_VERSION,
            'station': envelope.station,
            'issue_id': issue_id,
            'rule_code': envelope.rule_code,
            'revision_id': envelope.revision_id,
            'body': {
                'window': [str(low), str(high)],
                'traces': ordered,
                'proof': make_window_proof(credential.key, signed),
            },
        }
    )
