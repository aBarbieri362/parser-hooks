"""Parser and normaliser for CSS ``unicode-range`` values.

This module understands the three value forms permitted by the CSS Fonts
specification (`U+416`, `U+400-4FF`, and ``U+4??`` wildcard notation) and the
``?`` per-digit wildcard. It produces a small, typed representation that
makes ranges easy to merge, serialise, or feed into font subsetting tools.

Design choices
--------------

The CSS spec is genuinely ambiguous in a couple of corners; the decisions
below are baked into this module and documented in the README so callers
can rely on them:

* **Maximal code points**. Values above ``U+10FFFF`` (the Unicode maximum)
  are rejected with :class:`UnicodeRangeError`, even though the CSS syntax
  would otherwise accept long hex runs. CSS itself delegates the validity
  question to Unicode, so this is the least surprising reading.
* **Surrogates are allowed through**. ``U+D800-DFFF`` is syntactically
  valid as a CSS unicode-range and browsers accept it (font files may encode
  private-use mappings there). We do not silently strip surrogates.
* **Range inversion**. ``U+4FF-400`` is normalised to ``U+400-4FF`` rather
  than rejected. Spec wording is loose here; normalising is friendlier than
  throwing and is what every consumer we have seen does in practice.
* **Whitespace**. The grammar technically forbids internal spaces, but we
  tolerate whitespace around the comma separators because real-world
  ``@font-face`` blocks are often multi-line.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Union

MAX_CODE_POINT: int = 0x10FFFF
"""Highest code point permitted by the Unicode standard.

We reject anything above this rather than letting it through, because the
CSS spec defers code-point validity to Unicode and a value such as
``U+10FFFFF`` is almost always a typo rather than intent.
"""

__all__ = [
    "MAX_CODE_POINT",
    "CodePointRange",
    "UnicodeRange",
    "UnicodeRangeError",
    "UnicodeRangeSet",
    "parse",
]


class UnicodeRangeError(ValueError):
    """Raised when a ``unicode-range`` value cannot be parsed.

    Subclasses ``ValueError`` so callers catching the broader class still
    work.
    """


@dataclass(frozen=True)
class CodePointRange:
    """An inclusive range of Unicode code points ``[start, end]``.

    Both ends are always valid scalar code points (``0..MAX_CODE_POINT``)
    and ``start <= end`` is guaranteed by construction.
    """

    start: int
    end: int

    def __post_init__(self) -> None:
        if not (0 <= self.start <= MAX_CODE_POINT):
            raise UnicodeRangeError(
                f"start code point {self.start:#x} is outside 0..{MAX_CODE_POINT:#x}"
            )
        if not (0 <= self.end <= MAX_CODE_POINT):
            raise UnicodeRangeError(
                f"end code point {self.end:#x} is outside 0..{MAX_CODE_POINT:#x}"
            )
        if self.start > self.end:
            raise UnicodeRangeError(
                f"range start {self.start:#x} is greater than end {self.end:#x}"
            )

    def __iter__(self):
        # Iteration yields the inclusive span. Useful for subsetters that
        # want to walk every covered code point without materialising a
        # list.
        yield from range(self.start, self.end + 1)

    def __contains__(self, code_point: object) -> bool:
        if not isinstance(code_point, int):
            raise TypeError(
                f"CodePointRange membership requires int, got {type(code_point).__name__}"
            )
        return self.start <= code_point <= self.end

    def overlaps(self, other: "CodePointRange") -> bool:
        """Return ``True`` when the two ranges share any code point."""
        return self.start <= other.end and other.start <= self.end

    def to_css(self) -> str:
        """Serialise back to the canonical ``U+XXXX-XXXX`` form.

        We always emit four hex digits minimum so the output is stable and
        greppable, then let Python widen as needed for large code points.
        Single-point ranges collapse to ``U+XXXX``.
        """
        if self.start == self.end:
            return f"U+{self.start:04X}"
        return f"U+{self.start:04X}-{self.end:04X}"


@dataclass(frozen=True)
class UnicodeRange:
    """A single parsed ``unicode-range`` clause.

    The ``clause`` attribute records the exact source text (trimmed) so
    error messages can point back at what the user wrote.
    """

    range: CodePointRange
    clause: str

    @property
    def start(self) -> int:
        return self.range.start

    @property
    def end(self) -> int:
        return self.range.end

    def to_css(self) -> str:
        return self.range.to_css()


@dataclass(frozen=True)
class UnicodeRangeSet:
    """A parsed ``unicode-range`` declaration: one or more clauses.

    Ranges are kept in the order they appeared in the source. We deliberately
    do **not** merge adjacent or overlapping ranges on construction; merging
    loses information about the original author intent and is a job better
    done by a dedicated consumer if it wants it. The :meth:`merged` method
    is provided for callers that do want a coalesced view.
    """

    ranges: Tuple[UnicodeRange, ...]

    def __iter__(self):
        return iter(self.ranges)

    def __len__(self) -> int:
        return len(self.ranges)

    def __bool__(self) -> bool:
        return bool(self.ranges)

    def to_css(self) -> str:
        return ", ".join(r.to_css() for r in self.ranges)

    def merged(self) -> List[CodePointRange]:
        """Return a minimal list of non-overlapping, ascending ranges.

        Adjacent ranges (``end + 1 == next.start``) are also coalesced,
        because for subsetting purposes they cover an unbroken span.
        """
        if not self.ranges:
            return []
        ordered = sorted((r.range for r in self.ranges), key=lambda c: c.start)
        merged: List[CodePointRange] = [ordered[0]]
        for current in ordered[1:]:
            last = merged[-1]
            if current.start <= last.end + 1:
                # Overlap or adjacency: extend the tail. Constructing a new
                # CodePointRange keeps the invariant checks in one place.
                merged[-1] = CodePointRange(last.start, max(last.end, current.end))
            else:
                merged.append(current)
        return merged


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _split_clauses(value: str) -> List[str]:
    """Split a unicode-range declaration into individual clauses.

    Whitespace around commas is tolerated; whitespace *inside* a clause is
    not, because the CSS grammar has no place to put it and it almost always
    indicates a copy-paste error. Empty clauses (e.g. from a trailing
    comma) are rejected.
    """
    if not value or not value.strip():
        raise UnicodeRangeError("unicode-range value is empty")
    parts = [p.strip() for p in value.split(",")]
    clauses = []
    for p in parts:
        if not p:
            raise UnicodeRangeError("unicode-range value contains an empty clause")
        clauses.append(p)
    if not clauses:
        raise UnicodeRangeError("unicode-range value contains no clauses")
    return clauses


def _expand_wildcard(hex_part: str) -> int:
    """Expand a hex string that may contain ``?`` wildcards.

    ``U+4??`` matches every code point whose first hex digit is 4, i.e.
    ``0x400`` through ``0x4FF``. Each ``?`` stands in for "any single hex
    digit". We expand the wildcard to its *maximum* value by treating each
    ``?`` as ``F``; the caller pairs this with the minimum (``?`` as ``0``)
    to form a range.

    Raises if the string contains anything other than hex digits and ``?``.
    """
    if not hex_part:
        raise UnicodeRangeError("empty hex run after 'U+'")
    upper = []
    for ch in hex_part:
        if ch == "?":
            upper.append("F")
        elif ch in "0123456789ABCDEFabcdef":
            upper.append(ch.upper())
        else:
            raise UnicodeRangeError(
                f"invalid character {ch!r} in hex run {hex_part!r}"
            )
    return int("".join(upper), 16)


def _parse_single_clause(clause: str) -> UnicodeRange:
    """Parse one ``unicode-range`` clause into a :class:`UnicodeRange`.

    Accepted forms:
      * ``U+416``          — a single code point
      * ``U+400-4FF``      — an explicit range
      * ``U+4??``          — wildcard (``?`` stands for any hex digit)
      * ``U+4?2?``         — wildcards mixed with literal digits

    The ``U`` may be lowercase. The ``+`` is mandatory.
    """
    original = clause
    clause = clause.strip()
    if not clause:
        raise UnicodeRangeError("empty clause")

    # Accept U+ or u+; reject anything else so we don't silently swallow a
    # stray prefix that the caller thought was valid.
    if clause[0] not in ("U", "u"):
        raise UnicodeRangeError(f"clause {original!r} does not start with U+")
    if len(clause) < 3 or clause[1] != "+":
        raise UnicodeRangeError(f"clause {original!r} is missing the '+' after U")
    body = clause[2:]

    if not body:
        raise UnicodeRangeError(f"clause {original!r} has nothing after U+")

    # Range form: split on the single allowed hyphen. Anything more is an
    # error — we don't try to be clever about stray hyphens.
    if "-" in body:
        segments = body.split("-")
        if len(segments) != 2:
            raise UnicodeRangeError(
                f"clause {original!r} contains multiple hyphens"
            )
        left, right = segments
        if not left or not right:
            raise UnicodeRangeError(
                f"clause {original!r} has an empty side of the range"
            )
        # ``?`` is not permitted inside an explicit range per the spec; only
        # the single-token wildcard form allows it. We honour that.
        if "?" in left or "?" in right:
            raise UnicodeRangeError(
                f"clause {original!r} mixes wildcards with a hyphen range"
            )
        try:
            start = int(left, 16)
            end = int(right, 16)
        except ValueError as exc:
            raise UnicodeRangeError(
                f"clause {original!r} has non-hex range bounds"
            ) from exc
        if start > end:
            # Inverted ranges are normalised rather than rejected. See the
            # module docstring for the rationale.
            start, end = end, start
        if end > MAX_CODE_POINT:
            raise UnicodeRangeError(
                f"clause {original!r} exceeds U+{MAX_CODE_POINT:04X}"
            )
        return UnicodeRange(CodePointRange(start, end), original)

    # Single token: may contain ``?`` wildcards.
    if "?" in body:
        # Lower bound: every ``?`` becomes 0.
        lower_hex = body.replace("?", "0").upper()
        upper = _expand_wildcard(body)
        try:
            lower = int(lower_hex, 16)
        except ValueError as exc:
            raise UnicodeRangeError(
                f"clause {original!r} has invalid hex digits"
            ) from exc
        if upper > MAX_CODE_POINT:
            raise UnicodeRangeError(
                f"clause {original!r} exceeds U+{MAX_CODE_POINT:04X}"
            )
        return UnicodeRange(CodePointRange(lower, upper), original)

    # Plain single code point.
    try:
        cp = int(body, 16)
    except ValueError as exc:
        raise UnicodeRangeError(
            f"clause {original!r} is not valid hex"
        ) from exc
    if cp > MAX_CODE_POINT:
        raise UnicodeRangeError(
            f"clause {original!r} exceeds U+{MAX_CODE_POINT:04X}"
        )
    return UnicodeRange(CodePointRange(cp, cp), original)


def parse(value: Union[str, UnicodeRangeSet]) -> UnicodeRangeSet:
    """Parse a CSS ``unicode-range`` declaration.

    Args:
        value: The raw declaration text, e.g. ``"U+416, U+400-4FF, U+4??"``.
            Passing an existing :class:`UnicodeRangeSet` returns it unchanged
            so callers can accept either form conveniently.

    Returns:
        A :class:`UnicodeRangeSet` preserving clause order.

    Raises:
        UnicodeRangeError: If any clause is malformed or out of range.
    """
    if isinstance(value, UnicodeRangeSet):
        return value
    if not isinstance(value, str):
        raise UnicodeRangeError(
            f"expected str or UnicodeRangeSet, got {type(value).__name__}"
        )

    clauses = _split_clauses(value)
    ranges: List[UnicodeRange] = []
    for clause in clauses:
        ranges.append(_parse_single_clause(clause))
    return UnicodeRangeSet(tuple(ranges))
