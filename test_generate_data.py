"""Unit tests for generate_data.py (stdlib unittest; run: python3 -m unittest)."""

import csv
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

import generate_data as gd


class ExtractUnitsTest(unittest.TestCase):

    def test_digit_count(self):
        self.assertEqual(gd.extract_units("New 48 unit apartment building"), 48)

    def test_compound_hyphenated(self):
        self.assertEqual(gd.extract_units("Construct sixty-six unit apartment"), 66)

    def test_compound_spaced_dwelling_units(self):
        self.assertEqual(gd.extract_units("twenty one dwelling units"), 21)

    def test_compound_not_shadowed_by_ones_word(self):
        # "six unit" must not win over the full "twenty-six unit"
        self.assertEqual(gd.extract_units("twenty-six units"), 26)

    def test_plain_tens_word(self):
        self.assertEqual(gd.extract_units("seventy units of housing"), 70)

    def test_simple_word(self):
        self.assertEqual(gd.extract_units("two apartment units"), 2)

    def test_single_unit_rejected(self):
        self.assertIsNone(gd.extract_units("one unit addition"))

    def test_no_count(self):
        self.assertIsNone(gd.extract_units("interior remodel of kitchen"))


class StockChangeRegexTest(unittest.TestCase):

    def test_matches_stock_changing_language(self):
        for desc in ("Convert office to apartments",
                     "split single family into duplex",
                     "add two apartment units in basement",
                     "Add 1 dwelling unit"):
            with self.subTest(desc=desc):
                self.assertIsNotNone(gd._STOCK_CHANGE_RE.search(desc))

    def test_ignores_renovation_only(self):
        for desc in ("interior remodel of units",
                     "alteration to fire alarm system",
                     "conversion of boiler"):
            with self.subTest(desc=desc):
                self.assertIsNone(gd._STOCK_CHANGE_RE.search(desc))


class FilterAlterationsTest(unittest.TestCase):

    def _project(self, rec, housing_type, desc):
        return {"record_number": rec, "housing_type": housing_type,
                "description": desc}

    def _run(self, projects, overrides):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "alteration_overrides.csv")
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["record_number", "action", "reason"])
                writer.writerows(overrides)
            with mock.patch.object(gd, "ALTERATION_OVERRIDES_CSV", path), \
                    redirect_stdout(StringIO()):
                kept = gd._step_filter_alterations(projects)
        return [p["record_number"] for p in kept]

    def test_rule_drops_renovation_only_alteration(self):
        projects = [
            self._project("A", "Alteration", "interior remodel"),
            self._project("B", "Alteration", "convert to 3 units"),
            self._project("C", "Multiplex", "interior remodel"),
        ]
        self.assertEqual(self._run(projects, []), ["B", "C"])

    def test_include_override_beats_rule(self):
        projects = [self._project("A", "Alteration", "relocate building")]
        self.assertEqual(self._run(projects, [["A", "include", "adds"]]), ["A"])

    def test_exclude_override_beats_rule(self):
        projects = [self._project("A", "Multiplex", "convert 4-unit to 3-unit")]
        self.assertEqual(self._run(projects, [["A", " Exclude ", "loss"]]), [])

    def test_missing_overrides_file(self):
        projects = [self._project("A", "Alteration", "split unit")]
        with mock.patch.object(gd, "ALTERATION_OVERRIDES_CSV", "/nonexistent.csv"), \
                redirect_stdout(StringIO()):
            kept = gd._step_filter_alterations(projects)
        self.assertEqual([p["record_number"] for p in kept], ["A"])


if __name__ == "__main__":
    unittest.main()
