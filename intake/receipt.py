from dataclasses import dataclass

from issue.envelope import IssueEnvelope


@dataclass(frozen=True)
class IntakeReceipt:
    intake_id: int
    station: str
    issue_id: int
    rule_code: str
    revision_id: int
    digest: str


def make_intake_receipt(intake_id: int, envelope: IssueEnvelope) -> IntakeReceipt:
    return IntakeReceipt(
        intake_id,
        envelope.station,
        envelope.issue_id,
        envelope.rule_code,
        envelope.revision_id,
        envelope.digest,
    )
