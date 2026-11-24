from issue.envelope import IssueEnvelope
from issue.evidence import build_evidence, evidence_payload
from issue.register import IssueRegister
from rules.catalog import RuleCatalog


class UnknownRevision(LookupError):
    pass


def freeze(catalog: RuleCatalog, register: IssueRegister, revision_id: int) -> IssueEnvelope:
    revision = catalog.get_revision(revision_id)
    if revision is None:
        raise UnknownRevision(f'unknown rule revision {revision_id!r}')
    payload = evidence_payload(build_evidence(revision.definition))
    return register.record(revision, payload)
