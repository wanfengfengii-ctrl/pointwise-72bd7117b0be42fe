from contextlib import closing
from fractions import Fraction
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from intake.catalog import IntakeCatalog
from intake.receive import pin_window_issue, receive, receive_window
from issue.codec import encode_packet, encode_payload
from issue.freeze import freeze, freeze_window, make_window_packet
from issue.register import IssueRegister
from labdb import open_database
from report.compare import compare, compare_window
from report.read import read
from report.store import ReportStore
from rules.catalog import RuleCatalog
from rules.importer import register


SAMPLE = Path(__file__).resolve().parent / "samples" / "window_review.json"


def load_case():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def preload_credentials(install, station, *issued):
    for issue_id, credential in issued:
        install(station, issue_id, credential)


def verify_v1():
    case = load_case()
    with closing(open_database(":memory:")) as night:
        intake = IntakeCatalog(night)
        store = ReportStore(night)
        with closing(open_database(":memory:")) as day:
            catalog = RuleCatalog(day)
            issues = IssueRegister(day, "repair-window")
            left_rev = register(catalog, case["rule_code"], case["left"])
            right_rev = register(catalog, case["rule_code"], case["right"])
            left = receive(intake, encode_packet(freeze(catalog, issues, left_rev)))
            right = receive(intake, encode_packet(freeze(catalog, issues, right_rev)))
        signed = compare(intake, store, left.intake_id, right.intake_id)
        result = {
            "first_differences": [[beat, str(mass)] for beat, mass in signed.draft.first_differences],
            "always_same": str(signed.draft.always_same),
        }
        if result != case["expected_whole"]:
            raise AssertionError(f"整域对照不符: {result!r}")
        if signed.receipt.parents != (left.receipt, right.receipt):
            raise AssertionError("父件与实际实收顺序不符")
        if read(store, signed.report_id) != signed:
            raise AssertionError("复领结果不符")
        return result


def _window_trial(night, day, case, window):
    """Run one full window cycle and return the signed report and receipts."""
    catalog = RuleCatalog(day)
    issues = IssueRegister(day, "repair-window")
    left_rev = register(catalog, case["rule_code"], case["left"])
    right_rev = register(catalog, case["rule_code"], case["right"])
    left_issue, left_credential = freeze_window(catalog, issues, left_rev)
    right_issue, right_credential = freeze_window(catalog, issues, right_rev)
    intake = IntakeCatalog(night)
    store = ReportStore(night)
    preload_credentials(
        intake.pin,
        "repair-window",
        (left_issue, left_credential),
        (right_issue, right_credential),
    )
    lo, hi = window
    left = receive_window(
        intake, "repair-window", left_issue, lo, hi,
        make_window_packet(issues, left_issue, lo, hi),
    )
    right = receive_window(
        intake, "repair-window", right_issue, lo, hi,
        make_window_packet(issues, right_issue, lo, hi),
    )
    signed = compare_window(intake, store, left.intake_id, right.intake_id)
    return signed, left, right, (left_issue, right_issue)


def verify_window(window=None):
    """Sign the sample over the requested window and assert the documented result."""
    case = load_case()
    lo, hi = window if window is not None else case["window"]
    with closing(open_database(":memory:")) as night:
        with closing(open_database(":memory:")) as day:
            signed, left, right, _ = _window_trial(night, day, case, (lo, hi))
        result = {
            "first_differences": [[beat, str(mass)] for beat, mass in signed.draft.first_differences],
            "always_same": str(signed.draft.always_same),
        }
        if result != case["expected_window"]:
            raise AssertionError(f"窗口对照不符: {result!r}")
        if signed.draft.window != (Fraction(lo), Fraction(hi)):
            raise AssertionError("定稿窗口不符")
        if signed.receipt.parents != (left, right):
            raise AssertionError("窗口父件与实际实收顺序不符")
        if read(ReportStore(night), signed.report_id) != signed:
            raise AssertionError("窗口复领结果不符")
        return result


def verify_window_business():
    """End-to-end window verification: offline signing, rejections, and re-claim.

    Runs on temporary files so the day-side source can be taken away, and so
    the night library can be reopened for a by-number recall.  Returns the
    signed report's identity for the demo.
    """
    case = load_case()
    with TemporaryDirectory(prefix="window-verify-") as directory:
        day_path = Path(directory) / "day.sqlite3"
        night_path = Path(directory) / "night.sqlite3"
        with closing(open_database(day_path)) as day:
            catalog = RuleCatalog(day)
            issues = IssueRegister(day, "repair-window")
            left_rev = register(catalog, case["rule_code"], case["left"])
            right_rev = register(catalog, case["rule_code"], case["right"])
            left_issue, left_credential = freeze_window(catalog, issues, left_rev)
            right_issue, right_credential = freeze_window(catalog, issues, right_rev)
            lo, hi = case["window"]
            left_packet = make_window_packet(issues, left_issue, lo, hi)
            right_packet = make_window_packet(issues, right_issue, lo, hi)
            # Tampered piece: one action rewritten, everything else intact.
            tampered = json.loads(left_packet)
            tampered["body"]["traces"][0]["actions"][1] = "补检"
            tampered_packet = encode_payload(tampered)
            # Missing-segment piece: drop one delivered original segment.
            missing = json.loads(right_packet)
            del missing["body"]["traces"][-1]
            missing_packet = encode_payload(missing)

        with closing(open_database(night_path)) as night:
            intake = IntakeCatalog(night)
            store = ReportStore(night)
            preload_credentials(
                intake.pin,
                "repair-window",
                (left_issue, left_credential),
                (right_issue, right_credential),
            )

            def rejected(issue_id, lo_, hi_, packet):
                counts = tuple(
                    night.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                    for name in ("received_packets", "reports")
                )
                try:
                    receive_window(intake, "repair-window", issue_id, lo_, hi_, packet)
                except ValueError:
                    pass
                else:
                    raise AssertionError("伪件或漏段来件应被拒绝")
                after = tuple(
                    night.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                    for name in ("received_packets", "reports")
                )
                if after != counts:
                    raise AssertionError("拒件不应留下定稿或回执")

            rejected(left_issue, lo, hi, tampered_packet)
            rejected(right_issue, lo, hi, missing_packet)
            rejected(left_issue, "1/5", "3/4", left_packet)

            left = receive_window(intake, "repair-window", left_issue, lo, hi, left_packet)
            right = receive_window(intake, "repair-window", right_issue, lo, hi, right_packet)
            day_path.rename(day_path.with_suffix(".closed"))
            signed = compare_window(intake, store, left.intake_id, right.intake_id)

        expected = case["expected_window"]
        actual = {
            "first_differences": [[beat, str(mass)] for beat, mass in signed.draft.first_differences],
            "always_same": str(signed.draft.always_same),
        }
        if actual != expected:
            raise AssertionError(f"断源窗口签发不符: {actual!r}")
        if signed.draft.parents != (left, right) or signed.receipt.parents != (left, right):
            raise AssertionError("窗口父件应为请求的有序双实收回执")

        with closing(open_database(night_path)) as night:
            recalled = read(ReportStore(night), signed.report_id)
        if recalled != signed:
            raise AssertionError("窗口按号复领结果不符")
        return signed


if __name__ == "__main__":
    print("样例的 V1 整域报告", json.dumps(verify_v1(), ensure_ascii=False))
    print("样例的窗口复查报告", json.dumps(verify_window(), ensure_ascii=False))
    window_business = verify_window_business()
    print(
        "样例的窗口业务核验",
        json.dumps(
            {
                "report_id": window_business.report_id,
                "window": [str(bound) for bound in window_business.draft.window],
                "parents": [receipt.intake_id for receipt in window_business.draft.parents],
                "first_differences": [
                    [beat, str(mass)] for beat, mass in window_business.draft.first_differences
                ],
                "always_same": str(window_business.draft.always_same),
            },
            ensure_ascii=False,
        ),
    )
