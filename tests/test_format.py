"""Unit tests for ``ui.format``.

Stdlib unittest so this runs with ``py -3.11 -m unittest tests.test_format``
without pulling in pytest. Covers the canonical-rule helpers added in
sprint 2 plus regression coverage for the existing ``fmt_delay`` /
``parse_delay`` pair.
"""

from __future__ import annotations

import os
import sys
import unittest

# Allow `python -m unittest tests.test_format` from the project root by
# putting the repo on sys.path before the `ui.` import resolves.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ui.format import (  # noqa: E402
    fmt_count, fmt_delay, fmt_position, fmt_rate, parse_delay,
)


class FmtCountTests(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(fmt_count(0), "0")

    def test_small(self):
        self.assertEqual(fmt_count(42), "42")

    def test_thousand_boundary(self):
        self.assertEqual(fmt_count(999), "999")
        self.assertEqual(fmt_count(1000), "1,000")
        self.assertEqual(fmt_count(1234), "1,234")

    def test_million(self):
        self.assertEqual(fmt_count(1_500_000), "1,500,000")

    def test_negative(self):
        self.assertEqual(fmt_count(-1234), "-1,234")


class FmtPositionTests(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(fmt_position(1607, 679), "(1607, 679)")

    def test_origin(self):
        self.assertEqual(fmt_position(0, 0), "(0, 0)")

    def test_negative_coords(self):
        # Multi-monitor setups can put the secondary screen at negative x.
        self.assertEqual(fmt_position(-1920, 100), "(-1920, 100)")

    def test_floats_truncated_to_int(self):
        # Cursor pos can arrive as float from Qt; we always render integer.
        self.assertEqual(fmt_position(123.7, 456.2), "(123, 456)")


class FmtRateTests(unittest.TestCase):
    def test_default_one_decimal(self):
        self.assertEqual(fmt_rate(125.34, "CPM"), "125.3 CPM")

    def test_zero(self):
        self.assertEqual(fmt_rate(0.0, "CPM"), "0.0 CPM")

    def test_zero_decimals(self):
        self.assertEqual(fmt_rate(125.6, "Hz", decimals=0), "126 Hz")

    def test_three_decimals(self):
        self.assertEqual(fmt_rate(0.04567, "Hz", decimals=3), "0.046 Hz")

    def test_high_value(self):
        self.assertEqual(fmt_rate(12345.6, "CPM"), "12345.6 CPM")


class FmtDelayTests(unittest.TestCase):
    def test_sub_second(self):
        self.assertEqual(fmt_delay(0.075), "0.075 s")

    def test_sub_ten_three_decimals(self):
        self.assertEqual(fmt_delay(1.41), "1.410 s")
        self.assertEqual(fmt_delay(9.5), "9.500 s")

    def test_at_ten_drops_decimal(self):
        self.assertEqual(fmt_delay(10.0), "10.00 s")

    def test_above_ten_two_decimals(self):
        self.assertEqual(fmt_delay(42.5), "42.50 s")
        self.assertEqual(fmt_delay(240.0), "240.00 s")

    def test_zero(self):
        self.assertEqual(fmt_delay(0.0), "0.000 s")


class ParseDelayTests(unittest.TestCase):
    def test_seconds_suffix(self):
        self.assertAlmostEqual(parse_delay("0.05s"), 0.05)

    def test_milliseconds_suffix(self):
        self.assertAlmostEqual(parse_delay("50ms"), 0.05)

    def test_bare_number_is_seconds(self):
        self.assertAlmostEqual(parse_delay("0.05"), 0.05)

    def test_whitespace_tolerant(self):
        self.assertAlmostEqual(parse_delay("  50 ms "), 0.05)

    def test_case_insensitive(self):
        self.assertAlmostEqual(parse_delay("50MS"), 0.05)

    def test_empty_returns_none(self):
        self.assertIsNone(parse_delay(""))
        self.assertIsNone(parse_delay("   "))

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_delay("abc"))
        self.assertIsNone(parse_delay("--"))

    def test_none_input_returns_none(self):
        self.assertIsNone(parse_delay(None))


if __name__ == "__main__":
    unittest.main()
