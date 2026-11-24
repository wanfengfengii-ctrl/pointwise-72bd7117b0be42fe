from intake.catalog import IntakeCatalog
from issue.codec import InvalidPacketEncoding
from issue.window import rows_to_traces
from report.distribution import InvalidEvidence, compare_distribution, compare_window_distribution
from report.publish import publish_report, publish_window_report
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


def compare_window(
    intake: IntakeCatalog, store: ReportStore, left_id: int, right_id: int
) -> SignedReport:
    """Sign a report over two verified window intakes taken in the given order."""
    left = intake.get_window(left_id)
    right = intake.get_window(right_id)
    if left is None:
        raise InvalidComparison(f'left intake {left_id!r} is not a window intake')
    if right is None:
        raise InvalidComparison(f'right intake {right_id!r} is not a window intake')
    if left.window != right.window:
        raise InvalidComparison('both window intakes must share the same window')
    try:
        distribution = compare_window_distribution(
            rows_to_traces(left.traces), rows_to_traces(right.traces), left.window
        )
    except InvalidEvidence as error:
        raise InvalidComparison(f'unusable window evidence: {error}') from error
    return publish_window_report(store, (left, right), distribution, left.window)

