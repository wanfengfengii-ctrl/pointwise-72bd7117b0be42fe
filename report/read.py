from report.store import ReportStore, SignedReport


class ReportNotFound(LookupError):
    pass


def read(store: ReportStore, report_id: int) -> SignedReport:
    report = store.get(report_id)
    if report is None:
        raise ReportNotFound(f'unknown report number {report_id!r}')
    return report
