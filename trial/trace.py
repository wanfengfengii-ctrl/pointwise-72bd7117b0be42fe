from dataclasses import dataclass
from fractions import Fraction

from rules.revisions import RuleDefinition
from trial.step import step


@dataclass(frozen=True)
class ReplayTrace:
    actions: tuple[str, ...]
    ended_at: int | None


def observe_trace(definition: RuleDefinition, grade: Fraction, beats: int) -> ReplayTrace:
    position = definition.start
    actions = []
    for beat in range(1, beats + 1):
        result = step(definition, position, grade)
        if result.action is None:
            return ReplayTrace(tuple(actions), beat)
        actions.append(result.action)
        position = result.next_state
    return ReplayTrace(tuple(actions), None)
