from dataclasses import dataclass


@dataclass(frozen=True)
class PublicTrace:
    actions: tuple[str, ...]
    repeat_from: int | None

    def action_at(self, position: int) -> str | None:
        return self.actions[position] if position < len(self.actions) else None

    def advance(self, position: int) -> int:
        following = position + 1
        if following == len(self.actions) and self.repeat_from is not None:
            return self.repeat_from
        return following


def first_difference(left: PublicTrace, right: PublicTrace) -> int | None:
    left_position = right_position = 0
    beat = 1
    seen = set()
    while (left_position, right_position) not in seen:
        left_action = left.action_at(left_position)
        right_action = right.action_at(right_position)
        if left_action != right_action:
            return beat
        if left_action is None:
            return None
        seen.add((left_position, right_position))
        left_position = left.advance(left_position)
        right_position = right.advance(right_position)
        beat += 1
    return None
