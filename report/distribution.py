from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction

from issue.evidence import read_evidence
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
