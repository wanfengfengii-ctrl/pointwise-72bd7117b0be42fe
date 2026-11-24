from collections.abc import Mapping
from dataclasses import dataclass
import json
from types import MappingProxyType

from rules.grade import GradeBand, parse_rational


@dataclass(frozen=True)
class Transition:
    band: GradeBand
    action: str
    next_state: str


@dataclass(frozen=True)
class RuleDefinition:
    code: str
    start: str
    terminals: frozenset[str]
    states: Mapping[str, tuple[Transition, ...]]
    note: str


@dataclass(frozen=True)
class RuleRevision:
    revision_id: int
    definition: RuleDefinition


def encode_revision(definition: RuleDefinition) -> str:
    states = {}
    for state, transitions in definition.states.items():
        states[state] = [
            {
                'lower': str(row.band.lower),
                'upper': str(row.band.upper),
                'action': row.action,
                'next': row.next_state,
            }
            for row in transitions
        ]
    return json.dumps(
        {
            'start': definition.start,
            'terminals': sorted(definition.terminals),
            'states': states,
            'note': definition.note,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )


def decode_revision(revision_id: int, code: str, stored: str) -> RuleRevision:
    data = json.loads(stored)
    states = {}
    for state, rows in data['states'].items():
        states[state] = tuple(
            Transition(
                GradeBand(parse_rational(row['lower']), parse_rational(row['upper'])),
                row['action'],
                row['next'],
            )
            for row in rows
        )
    definition = RuleDefinition(
        code, data['start'], frozenset(data['terminals']), MappingProxyType(states), data['note']
    )
    return RuleRevision(revision_id, definition)
