import unittest

from css_unicode_range_parser import (
    CodePointRange,
    UnicodeRange,
    UnicodeRangeError,
    UnicodeRangeSet,
    MAX_CODE_POINT,
    parse,
)


class TestSingleCodePoint(unittest.TestCase):
    def test_basic_single(self):
        result = parse("U+416")
        self.assertEqual(len(result), 1)
        r = result.ranges[0]
        self.assertEqual(r.start, 0x416)
        self.assertEqual(r.end, 0x416)
        self.assertEqual(r.to_css(), "U+0416")

    def test_lowercase_u(self):
        r = parse("u+30").ranges[0]
        self.assertEqual(r.start, 0x30)

    def test_single_with_many_digits(self):
        r = parse("U+10FFFF").ranges[0]
        self.assertEqual(r.start, MAX_CODE_POINT)
        self.assertEqual(r.to_css(), "U+10FFFF")

    def test_above_max_rejected(self):
        with self.assertRaises(UnicodeRangeError):
            parse("U+110000")


class TestExplicitRange(unittest.TestCase):
    def test_basic_range(self):
        r = parse("U+400-4FF").ranges[0]
        self.assertEqual(r.start, 0x400)
        self.assertEqual(r.end, 0x4FF)
        self.assertEqual(r.to_css(), "U+0400-04FF")

    def test_inverted_range_normalised(self):
        r = parse("U+4FF-400").ranges[0]
        self.assertEqual(r.start, 0x400)
        self.assertEqual(r.end, 0x4FF)

    def test_range_at_boundary(self):
        r = parse("U+10FFFE-10FFFF").ranges[0]
        self.assertEqual(r.end, MAX_CODE_POINT)

    def test_range_above_max_rejected(self):
        with self.assertRaises(UnicodeRangeError):
            parse("U+10FFFF-110000")

    def test_range_with_wildcard_rejected(self):
        with self.assertRaises(UnicodeRangeError):
            parse("U+40?-4FF")


class TestWildcard(unittest.TestCase):
    def test_double_wildcard(self):
        r = parse("U+4??").ranges[0]
        self.assertEqual(r.start, 0x400)
        self.assertEqual(r.end, 0x4FF)

    def test_single_wildcard(self):
        r = parse("U+4?").ranges[0]
        self.assertEqual(r.start, 0x40)
        self.assertEqual(r.end, 0x4F)

    def test_mixed_wildcard(self):
        r = parse("U+4?2?").ranges[0]
        self.assertEqual(r.start, 0x4020)
        self.assertEqual(r.end, 0x4F2F)

    def test_wildcard_above_max_rejected(self):
        with self.assertRaises(UnicodeRangeError):
            parse("U+11????")


class TestMultipleClauses(unittest.TestCase):
    def test_three_clauses(self):
        result = parse("U+416, U+400-4FF, U+4??")
        self.assertEqual(len(result), 3)
        self.assertEqual(result.ranges[0].start, 0x416)
        self.assertEqual(result.ranges[1].start, 0x400)
        self.assertEqual(result.ranges[1].end, 0x4FF)
        self.assertEqual(result.ranges[2].start, 0x400)
        self.assertEqual(result.ranges[2].end, 0x4FF)

    def test_whitespace_around_commas(self):
        result = parse("U+416 , U+400-4FF")
        self.assertEqual(len(result), 2)

    def test_clause_order_preserved(self):
        result = parse("U+500, U+100, U+300")
        starts = [r.start for r in result.ranges]
        self.assertEqual(starts, [0x500, 0x100, 0x300])

    def test_to_css_roundtrip(self):
        css = "U+0416, U+0400-04FF, U+0400-04FF"
        result = parse("U+416, U+400-4FF, U+4??")
        self.assertEqual(result.to_css(), css)


class TestCodePointRange(unittest.TestCase):
    def test_contains(self):
        r = CodePointRange(0x400, 0x4FF)
        self.assertIn(0x400, r)
        self.assertIn(0x4FF, r)
        self.assertIn(0x480, r)
        self.assertNotIn(0x3FF, r)
        self.assertNotIn(0x500, r)

    def test_contains_non_int(self):
        r = CodePointRange(0, 1)
        with self.assertRaises(TypeError):
            "x" in r  # type: ignore[operator]

    def test_overlaps(self):
        a = CodePointRange(0x400, 0x4FF)
        b = CodePointRange(0x4F0, 0x500)
        self.assertTrue(a.overlaps(b))
        c = CodePointRange(0x500, 0x5FF)
        self.assertFalse(a.overlaps(c))

    def test_iteration(self):
        r = CodePointRange(0x10, 0x12)
        self.assertEqual(list(r), [0x10, 0x11, 0x12])

    def test_invalid_start(self):
        with self.assertRaises(UnicodeRangeError):
            CodePointRange(-1, 0)

    def test_invalid_end(self):
        with self.assertRaises(UnicodeRangeError):
            CodePointRange(0, MAX_CODE_POINT + 1)


class TestMerged(unittest.TestCase):
    def test_overlapping_merged(self):
        result = parse("U+400-4FF, U+4F0-5FF")
        merged = result.merged()
        self.assertEqual(merged, [CodePointRange(0x400, 0x5FF)])

    def test_adjacent_merged(self):
        result = parse("U+400-4FF, U+500-5FF")
        merged = result.merged()
        self.assertEqual(merged, [CodePointRange(0x400, 0x5FF)])

    def test_disjoint_kept(self):
        result = parse("U+400-4FF, U+600-6FF")
        merged = result.merged()
        self.assertEqual(merged, [CodePointRange(0x400, 0x4FF), CodePointRange(0x600, 0x6FF)])

    def test_unordered_merged(self):
        result = parse("U+600-6FF, U+400-4FF, U+500-5FF")
        merged = result.merged()
        self.assertEqual(merged, [CodePointRange(0x400, 0x6FF)])


class TestErrors(unittest.TestCase):
    def test_empty_string(self):
        with self.assertRaises(UnicodeRangeError):
            parse("")

    def test_whitespace_only(self):
        with self.assertRaises(UnicodeRangeError):
            parse("   ")

    def test_missing_u_prefix(self):
        with self.assertRaises(UnicodeRangeError):
            parse("+416")

    def test_missing_plus(self):
        with self.assertRaises(UnicodeRangeError):
            parse("U416")

    def test_non_hex(self):
        with self.assertRaises(UnicodeRangeError):
            parse("U+GGG")

    def test_multiple_hyphens(self):
        with self.assertRaises(UnicodeRangeError):
            parse("U+400-4FF-500")

    def test_trailing_comma(self):
        with self.assertRaises(UnicodeRangeError):
            parse("U+416,")

    def test_bad_type(self):
        with self.assertRaises(UnicodeRangeError):
            parse(123)  # type: ignore[arg-type]


class TestIdempotence(unittest.TestCase):
    def test_parse_rangeset_returns_self(self):
        first = parse("U+416")
        second = parse(first)
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
