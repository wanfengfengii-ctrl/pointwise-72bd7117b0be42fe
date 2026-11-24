from types import MappingProxyType

from rules.grade import GradeBand, parse_rational, validate_partition
from rules.revisions import RuleDefinition, Transition


class InvalidRules(ValueError):
    pass


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f'{field} must be text' + ('' if allow_empty else ' with content'))
    value.encode('utf-8')
    return value


def _transitions(state: str, rows: object, places: set[str]) -> tuple[Transition, ...]:
    if not isinstance(rows, list):
        raise ValueError(f'{state}: expected a list of transitions')
    transitions = []
    for row in rows:
        if not isinstance(row, dict) or row.keys() != {'lower', 'upper', 'action', 'next'}:
            raise ValueError(f'{state}: malformed transition')
        destination = _text(row['next'], 'next')
        if destination not in places:
            raise ValueError(f'{state}: unknown next state {destination!r}')
        transitions.append(
            Transition(
                GradeBand(parse_rational(row['lower']), parse_rational(row['upper'])),
                _text(row['action'], 'action'),
                destination,
            )
        )
    transitions.sort(key=lambda transition: transition.band.lower)
    try:
        validate_partition(transition.band for transition in transitions)
    except ValueError as error:
        raise ValueError(f'{state}: {error}') from error
    return tuple(transitions)


def validate_rules(code: object, raw: object) -> RuleDefinition:
    try:
        rule_code = _text(code, 'rule code')
        required = {'start', 'terminals', 'states'}
        if not isinstance(raw, dict) or not required <= raw.keys() <= required | {'note'}:
            raise ValueError('expected start, terminals, states and optional note')
        start = _text(raw['start'], 'start')
        note = _text(raw.get('note', ''), 'note', allow_empty=True)
        if not isinstance(raw['terminals'], list) or not isinstance(raw['states'], dict):
            raise ValueError('expected a terminal list and a state mapping')
        terminal_list = [_text(value, 'terminal') for value in raw['terminals']]
        terminals = frozenset(terminal_list)
        if len(terminals) != len(terminal_list):
            raise ValueError('duplicate terminal state')
        executing = {_text(name, 'state') for name in raw['states']}
        if terminals & executing:
            raise ValueError('terminal states cannot have transitions')
        places = set(terminals | executing)
        if start not in places:
            raise ValueError('unknown start state')
        states = {
            state: _transitions(state, rows, places)
            for state, rows in raw['states'].items()
        }
        return RuleDefinition(rule_code, start, terminals, MappingProxyType(states), note)
    except ValueError as error:
        raise InvalidRules(str(error)) from error
