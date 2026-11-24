from rules.catalog import RuleCatalog
from rules.grade import require_grade
from trial.history import ReplayHistory, ReplayRecord
from trial.trace import observe_trace


class InvalidReplay(ValueError):
    pass


def preview(
    catalog: RuleCatalog,
    history: ReplayHistory,
    revision_id: int,
    grade: object,
    beats: int,
) -> ReplayRecord:
    if type(beats) is not int or beats < 0:
        raise InvalidReplay('observation beats must be a nonnegative integer')
    revision = catalog.get_revision(revision_id)
    if revision is None:
        raise InvalidReplay(f'unknown rule revision {revision_id!r}')
    try:
        pinned_grade = require_grade(grade)
        trace = observe_trace(revision.definition, pinned_grade, beats)
    except ValueError as error:
        raise InvalidReplay(str(error)) from error
    return history.record(revision.revision_id, pinned_grade, beats, trace)
