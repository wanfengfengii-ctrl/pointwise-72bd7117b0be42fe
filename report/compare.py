from intake.catalog import IntakeCatalog
from issue.codec import InvalidPacketEncoding
from report.distribution import InvalidEvidence, compare_distribution
from report.publish import publish_report
from report.store import ReportStore, SignedReport


class InvalidComparison(ValueError):
    pass


def compare(
    intake: IntakeCatalog, store: ReportStore, left_id: int, right_id: int
) -> SignedReport:
    try:
        left = intake.get(left_id)
        right = intake.get(right_id)
    except InvalidPacketEncoding as error:
        raise InvalidComparison(f'unreadable intake snapshot: {error}') from error
    if left is None:
        raise InvalidComparison(f'unknown left intake number {left_id!r}')
    if right is None:
        raise InvalidComparison(f'unknown right intake number {right_id!r}')
    try:
        distribution = compare_distribution(left.envelope.body, right.envelope.body)
    except InvalidEvidence as error:
        raise InvalidComparison(f'unusable public evidence: {error}') from error
    return publish_report(store, (left, right), distribution)
