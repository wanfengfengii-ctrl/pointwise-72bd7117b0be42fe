from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
import re


_RATIONAL = re.compile(r'[+-]?(?:[0-9]+(?:/[0-9]+)?|[0-9]+\.[0-9]+)')


@dataclass(frozen=True)
class GradeBand:
    lower: Fraction
    upper: Fraction

    def contains(self, grade: Fraction) -> bool:
        return self.lower <= grade < self.upper

    @property
    def length(self) -> Fraction:
        return self.upper - self.lower


def parse_rational(value: object) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if type(value) is int:
        return Fraction(value)
    if isinstance(value, str) and _RATIONAL.fullmatch(value):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as error:
            raise ValueError('invalid rational value') from error
    raise ValueError('expected an exact rational value')


def require_grade(value: object) -> Fraction:
    grade = parse_rational(value)
    if not 0 <= grade < 1:
        raise ValueError('grade must belong to [0, 1)')
    return grade


def validate_partition(bands: Iterable[GradeBand]) -> tuple[GradeBand, ...]:
    ordered = tuple(sorted(bands, key=lambda band: band.lower))
    cursor = Fraction(0)
    for band in ordered:
        if not 0 <= band.lower < band.upper <= 1:
            raise ValueError('each grade band must be nonempty and within [0, 1)')
        if band.lower != cursor:
            raise ValueError('grade bands have an overlap or a gap')
        cursor = band.upper
    if cursor != 1:
        raise ValueError('grade bands must cover [0, 1)')
    return ordered
