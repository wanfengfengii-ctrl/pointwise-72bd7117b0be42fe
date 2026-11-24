from intake.catalog import AcceptedPacket
from report.distribution import DifferenceDistribution
from report.store import ReportDraft, ReportStore, SignedReport


def publish_report(
    store: ReportStore,
    parents: tuple[AcceptedPacket, AcceptedPacket],
    distribution: DifferenceDistribution,
) -> SignedReport:
    left, right = parents
    draft = ReportDraft(
        (left.receipt, right.receipt), distribution.first_differences, distribution.always_same
    )
    return store.commit(draft)
