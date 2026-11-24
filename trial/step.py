from dataclasses import dataclass
from fractions import Fraction

from rules.revisions import RuleDefinition


@dataclass(frozen=True)
class StepResult:
    action: str | None
    next_state: str


def step(definition: RuleDefinition, state: str, grade: Fraction) -> StepResult:
    if state in definition.terminals:
        return StepResult(None, state)
    for transition in definition.states[state]:
        if transition.band.contains(grade):
            return StepResult(transition.action, transition.next_state)
    raise ValueError(f'no transition for grade {grade} at {state!r}')
