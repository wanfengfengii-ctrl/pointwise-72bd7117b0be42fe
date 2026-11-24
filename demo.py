from contextlib import closing
from dataclasses import asdict
from fractions import Fraction
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from intake.catalog import IntakeCatalog
from intake.receive import pin_window_issue, receive, receive_window
from issue.codec import encode_packet
from issue.freeze import freeze, freeze_window, make_window_packet
from issue.register import IssueRegister
from labdb import open_database
from report.compare import compare, compare_window
from report.read import read
from report.store import ReportStore
from rules.catalog import RuleCatalog
from rules.importer import register
from trial.history import ReplayHistory
from trial.session import preview


SAMPLES = Path(__file__).resolve().parent / 'samples'


def load_sample(name: str) -> dict:
    return json.loads((SAMPLES / f'{name}.json').read_text(encoding='utf-8'))


def window_demo(night_path: Path) -> None:
    """Show the external window review: pin, deliver, sign, then recall by number."""
    case = json.loads((SAMPLES / 'window_review.json').read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='window-demo-') as directory:
        day_path = Path(directory) / 'day.sqlite3'
        with closing(open_database(day_path)) as day:
            catalog = RuleCatalog(day)
            issues = IssueRegister(day, 'repair-window')
            left_rev = register(catalog, case['rule_code'], case['left'])
            right_rev = register(catalog, case['rule_code'], case['right'])
            left_issue, left_credential = freeze_window(catalog, issues, left_rev)
            right_issue, right_credential = freeze_window(catalog, issues, right_rev)
            lo, hi = case['window']
            left_packet = make_window_packet(issues, left_issue, lo, hi)
            right_packet = make_window_packet(issues, right_issue, lo, hi)
        with closing(open_database(night_path)) as night:
            intake = IntakeCatalog(night)
            store = ReportStore(night)
            pin_window_issue(intake, 'repair-window', left_issue, left_credential)
            pin_window_issue(intake, 'repair-window', right_issue, right_credential)
            left = receive_window(intake, 'repair-window', left_issue, lo, hi, left_packet)
            right = receive_window(intake, 'repair-window', right_issue, lo, hi, right_packet)
            day_path.rename(day_path.with_suffix('.closed'))
            signed = compare_window(intake, store, left.intake_id, right.intake_id)
        print('窗口签发', json.dumps(draft_json(signed), ensure_ascii=False, default=str))
        with closing(open_database(night_path)) as night:
            recalled = read(ReportStore(night), signed.report_id)
        print('窗口复领', json.dumps({
            'report_id': recalled.report_id,
            'window': [str(bound) for bound in recalled.draft.window],
            'parents': [asdict(receipt) for receipt in recalled.receipt.parents],
            'first_differences': [[beat, str(mass)] for beat, mass in recalled.draft.first_differences],
            'always_same': str(recalled.draft.always_same),
        }, ensure_ascii=False, default=str))


def draft_json(signed) -> dict:
    """Serialise a report, keeping the original V1 shape for whole-domain reports."""
    data = asdict(signed)
    if data['draft'].get('window') is None:
        del data['draft']['window']
    return data


def run() -> None:
    with TemporaryDirectory(prefix='repair-shift-') as directory:
        day_path = Path(directory) / 'day.sqlite3'
        night_path = Path(directory) / 'night.sqlite3'
        window_night_path = Path(directory) / 'window-night.sqlite3'
        offline_path = day_path.with_suffix('.closed')
        with closing(open_database(day_path)) as day:
            catalog = RuleCatalog(day)
            history = ReplayHistory(day)
            issues = IssueRegister(day, 'repair-demo')
            old = register(catalog, 'R-17', load_sample('old'))
            replay = preview(catalog, history, old, '1/2', 3)
            swapped = register(catalog, 'R-17', load_sample('swapped'))
            old_packet = encode_packet(freeze(catalog, issues, old))
            new_packet = encode_packet(freeze(catalog, issues, swapped))
        print('现场复演', json.dumps(asdict(replay), ensure_ascii=False, default=str))
        with closing(open_database(night_path)) as night:
            intake = IntakeCatalog(night)
            store = ReportStore(night)
            left = receive(intake, old_packet)
            right = receive(intake, new_packet)
            day_path.rename(offline_path)
            signed = compare(intake, store, left.intake_id, right.intake_id)
        if signed.draft.first_differences != ((2, Fraction(1)),) or signed.draft.always_same != 0:
            raise RuntimeError('演示样例的第二拍首差概率应为 1')
        print('断源签发', json.dumps(draft_json(signed), ensure_ascii=False, default=str))
        offline_path.rename(day_path)
        with closing(open_database(day_path)) as day:
            catalog = RuleCatalog(day)
            latest = register(catalog, 'R-17', load_sample('aligned'))
            current = catalog.current_revision('R-17')
            if current is None or current.revision_id != latest:
                raise RuntimeError('更正后未取得新现行修订')
        with closing(open_database(night_path)) as night:
            original = read(ReportStore(night), signed.report_id)
        if original != signed:
            raise RuntimeError('重开后原定稿或回执变化')
        print('换班复领', json.dumps({
            'current_revision': latest,
            'report_id': original.report_id,
            'first_differences': original.draft.first_differences,
            'always_same': original.draft.always_same,
            'receipt': asdict(original.receipt),
        }, ensure_ascii=False, default=str))
        window_demo(window_night_path)


if __name__ == '__main__':
    run()
