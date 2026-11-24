from contextlib import closing
from dataclasses import asdict
from fractions import Fraction
import json
from pathlib import Path
from tempfile import TemporaryDirectory

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
from trial.history import ReplayHistory
from trial.session import preview


SAMPLES = Path(__file__).resolve().parent / 'samples'


def load_sample(name: str) -> dict:
    return json.loads((SAMPLES / f'{name}.json').read_text(encoding='utf-8'))


def run() -> None:
    with TemporaryDirectory(prefix='repair-shift-') as directory:
        day_path = Path(directory) / 'day.sqlite3'
        night_path = Path(directory) / 'night.sqlite3'
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
        print('断源签发', json.dumps(asdict(signed), ensure_ascii=False, default=str))
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


if __name__ == '__main__':
    run()
