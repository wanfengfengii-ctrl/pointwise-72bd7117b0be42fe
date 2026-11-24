from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction

from issue.evidence import GradeTrace, read_evidence
from rules.grade import GradeBand
from report.sequence import PublicTrace, first_difference


class InvalidEvidence(ValueError):
    pass


@dataclass(frozen=True)
class DifferenceDistribution:
    first_differences: tuple[tuple[int, Fraction], ...]
    always_same: Fraction


def compare_distribution(left_body: bytes, right_body: bytes) -> DifferenceDistribution:
    try:
        left = read_evidence(left_body)
        right = read_evidence(right_body)
    except ValueError as error:
        raise InvalidEvidence(str(error)) from error
    differences = defaultdict(Fraction)
    same = Fraction(0)
    left_index = right_index = 0
    while left_index < len(left) and right_index < len(right):
        a = left[left_index]
        b = right[right_index]
        joint = GradeBand(max(a.band.lower, b.band.lower), min(a.band.upper, b.band.upper))
        if joint.length <= 0:
            raise InvalidEvidence('common grade partitions do not advance together')
        beat = first_difference(
            PublicTrace(a.actions, a.repeat_from), PublicTrace(b.actions, b.repeat_from)
        )
        if beat is None:
            same += joint.length
        else:
            differences[beat] += joint.length
        if a.band.upper <= b.band.upper:
            left_index += 1
        if b.band.upper <= a.band.upper:
            right_index += 1
    if same + sum(differences.values()) != 1:
        raise InvalidEvidence('grade probabilities do not cover the whole population')
    return DifferenceDistribution(tuple(sorted(differences.items())), same)


def compare_window_distribution(
    left_traces: tuple[GradeTrace, ...],
    right_traces: tuple[GradeTrace, ...],
    window: tuple[Fraction, Fraction],
) -> DifferenceDistribution:
    """Compare the delivered original segments over ``[lo, hi)`` only.

    Segment mass is the length of the segment's intersection with the window
    divided by the window length.  Segments crossing a window edge keep their
    original boundaries and are truncated only here, at computation time.
    """
    low, high = window
    span = high - low
    if span <= 0:
        raise InvalidEvidence('window must have a positive length')
    differences = defaultdict(Fraction)
    same = Fraction(0)
    for a in left_traces:
        for b in right_traces:
            joint_lower = max(a.band.lower, b.band.lower, low)
            joint_upper = min(a.band.upper, b.band.upper, high)
            if joint_upper <= joint_lower:
                continue
            mass = (joint_upper - joint_lower) / span
            beat = first_difference(
                PublicTrace(a.actions, a.repeat_from), PublicTrace(b.actions, b.repeat_from)
            )
            if beat is None:
                same += mass
            else:
                differences[beat] += mass
    if same + sum(differences.values()) != 1:
        raise InvalidEvidence('window probabilities do not cover the whole window')
    return DifferenceDistribution(
        tuple(sorted((beat, mass) for beat, mass in differences.items() if mass > 0)),
        same,
    )
