from dataclasses import dataclass
from fractions import Fraction
import json

from rules.grade import GradeBand, parse_rational, validate_partition
from rules.revisions import RuleDefinition
from trial.step import step


@dataclass(frozen=True)
class GradeTrace:
    band: GradeBand
    actions: tuple[str, ...]
    repeat_from: int | None


def _freeze_band(definition: RuleDefinition, band: GradeBand) -> GradeTrace:
    positions = {}
    actions = []
    position = definition.start
    while position not in positions:
        result = step(definition, position, band.lower)
        if result.action is None:
            return GradeTrace(band, tuple(actions), None)
        positions[position] = len(actions)
        actions.append(result.action)
        position = result.next_state
    return GradeTrace(band, tuple(actions), positions[position])


def build_evidence(definition: RuleDefinition) -> tuple[GradeTrace, ...]:
    cuts = {Fraction(0), Fraction(1)}
    for transitions in definition.states.values():
        for transition in transitions:
            cuts.add(transition.band.lower)
            cuts.add(transition.band.upper)
    ordered = sorted(cuts)
    return tuple(
        _freeze_band(definition, GradeBand(lower, upper))
        for lower, upper in zip(ordered, ordered[1:])
    )


def evidence_payload(traces: tuple[GradeTrace, ...]) -> dict:
    return {
        'traces': [
            {
                'lower': str(trace.band.lower),
                'upper': str(trace.band.upper),
                'actions': list(trace.actions),
                'repeat_from': trace.repeat_from,
            }
            for trace in traces
        ]
    }


def _read_bound(value: object) -> Fraction:
    if not isinstance(value, str):
        raise ValueError('grade bound must be a rational string')
    bound = parse_rational(value)
    if str(bound) != value:
        raise ValueError('grade bound must be in canonical form')
    return bound


def _read_row(row: object) -> GradeTrace:
    if not isinstance(row, dict) or row.keys() != {'lower', 'upper', 'actions', 'repeat_from'}:
        raise ValueError('invalid grade trace fields')
    band = GradeBand(_read_bound(row['lower']), _read_bound(row['upper']))
    actions = row['actions']
    if not isinstance(actions, list) or any(
        not isinstance(action, str) or not action.strip() for action in actions
    ):
        raise ValueError('actions must be a list of public action codes')
    repeat = row['repeat_from']
    if repeat is not None and (type(repeat) is not int or not 0 <= repeat < len(actions)):
        raise ValueError('invalid public trace cycle entry')
    return GradeTrace(band, tuple(actions), repeat)


def read_evidence(body: bytes) -> tuple[GradeTrace, ...]:
    data = json.loads(body)
    if not isinstance(data, dict) or data.keys() != {'traces'} or not isinstance(data['traces'], list):
        raise ValueError('expected a public grade trace partition')
    traces = tuple(_read_row(row) for row in data['traces'])
    bands = tuple(trace.band for trace in traces)
    if validate_partition(bands) != bands:
        raise ValueError('grade traces must be ordered by lower bound')
    return traces
