# CSS Unicode Range Parser

Parses and normalises CSS `unicode-range` declarations — the `U+` notation, explicit ranges like `U+400-4FF`, and `?` wildcard syntax like `U+4??` — into typed Python objects you can merge, serialise, or feed to a font subsetting tool.

```python
from css_unicode_range_parser import parse

result = parse("U+416, U+400-4FF, U+4??")
for r in result:
    print(r.to_css())
# U+0416
# U+0400-04FF
# U+0400-04FF

merged = result.merged()
# [CodePointRange(start=0x400, end=0x4ff), CodePointRange(start=0x416, end=0x416)]
```

## Why this exists

Font subsetting tools want a concrete set of code points. CSS `unicode-range` gives authors a compact, human-readable way to express those sets, but the syntax has three forms and a handful of ambiguous edges that are easy to get wrong. This library does one job: turn that string into a structure you can reason about, with the awkward cases handled explicitly rather than silently dropped.

The trade-off is scope. This is a parser, not a font tool. It does not fetch `@font-face` blocks out of a stylesheet, does not validate ranges against an actual font's cmap, and does not attempt to merge overlapping ranges at construction time (call `UnicodeRangeSet.merged()` if you want that). Keeping the surface small means the behaviour is predictable.

## Edge cases worth knowing

- **Above `U+10FFFF` is rejected.** The CSS grammar would accept the hex, but Unicode defines no code points above `10FFFF`, so such a value is almost always a typo.
- **Surrogates (`U+D800-DFFF`) pass through.** They are syntactically valid and browsers accept them; we do not silently strip them.
- **Inverted ranges (`U+4FF-400`) are normalised** to `U+400-4FF` rather than rejected. The spec is loose here and every consumer we checked does the same.
- **Whitespace is tolerated around commas** but not inside a clause. `U+416 , U+400-4FF` parses; `U+41 6` does not.
- **Wildcards are not allowed inside an explicit range.** `U+40?-4FF` is rejected; only the single-token form (`U+4??`) supports `?`.

## Exports

- `parse(value)` — parse a `unicode-range` string into a `UnicodeRangeSet`. Passing an existing `UnicodeRangeSet` returns it unchanged.
- `UnicodeRangeSet` — frozen collection of `UnicodeRange` clauses, in source order. Has `.merged()` returning a minimal list of `CodePointRange`, and `.to_css()`.
- `UnicodeRange` — a single clause; `.start`, `.end`, `.to_css()`.
- `CodePointRange` — inclusive `[start, end]`; supports `in`, iteration, `.overlaps()`, `.to_css()`.
- `UnicodeRangeError` — subclass of `ValueError`, raised on any parse failure.
- `MAX_CODE_POINT` — the integer `0x10FFFF`.

## Running the tests

```
PYTHONPATH=src python -m unittest discover -s tests
```
