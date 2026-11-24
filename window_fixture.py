from contextlib import closing
import json
from pathlib import Path

from intake.catalog import IntakeCatalog
from intake.receive import receive
from issue.codec import encode_packet
from issue.freeze import freeze
from issue.register import IssueRegister
from labdb import open_database
from report.compare import compare
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


if __name__ == "__main__":
    print("样例的 V1 整域报告", json.dumps(verify_v1(), ensure_ascii=False))
