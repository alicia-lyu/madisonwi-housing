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


class CleanAddressTest(unittest.TestCase):

    def test_strips_legacy_country_suffix(self):
        self.assertEqual(
            gd.clean_address("222 W Washington AVE, 705, Madison WI 53703 United States"),
            "222 W Washington AVE, Madison WI 53703")

    def test_strips_full_country_name(self):
        self.assertEqual(
            gd.clean_address("302 Acewood Blvd, MADISON WI 53714 United States of America"),
            "302 Acewood Blvd, MADISON WI 53714")

    def test_appends_city_when_missing(self):
        self.assertEqual(gd.clean_address("952 N Fair Oaks AVE"),
                         "952 N Fair Oaks AVE, Madison WI")

    def test_keeps_existing_city(self):
        self.assertEqual(gd.clean_address("9701 Brader WAY, Middleton WI 53562"),
                         "9701 Brader WAY, Middleton WI 53562")


class InMadisonAreaTest(unittest.TestCase):

    def test_capitol_inside(self):
        self.assertTrue(gd.in_madison_area(43.0747, -89.3842))

    def test_pasadena_outside(self):
        self.assertFalse(gd.in_madison_area(34.1623, -118.1505))


class GeocodeTest(unittest.TestCase):

    def _geocode_with_response(self, payload):
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = payload.encode()
        cache = {}
        with mock.patch.object(gd.urllib.request, "urlopen", return_value=resp), \
                redirect_stdout(StringIO()):
            result = gd.geocode("952 N Fair Oaks AVE", cache)
        return result, cache

    def test_out_of_area_result_cached_as_miss(self):
        result, cache = self._geocode_with_response(
            '[{"lat": "34.1623", "lon": "-118.1505"}]')
        self.assertEqual(result, (None, None))
        self.assertEqual(cache["geo:952 N Fair Oaks AVE"], {"lat": None, "lng": None})

    def test_stale_out_of_area_cache_entry_is_refetched(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b'[{"lat": "43.098", "lon": "-89.330"}]'
        cache = {"geo:952 N Fair Oaks AVE": {"lat": 34.1623, "lng": -118.1505}}
        with mock.patch.object(gd.urllib.request, "urlopen", return_value=resp), \
                redirect_stdout(StringIO()):
            result = gd.geocode("952 N Fair Oaks AVE", cache)
        self.assertEqual(result, (43.098, -89.330))

    def test_network_error_not_cached(self):
        error = gd.urllib.error.URLError("nodename nor servname provided")
        cache = {}
        with mock.patch.object(gd.urllib.request, "urlopen", side_effect=error), \
                redirect_stdout(StringIO()):
            result = gd.geocode("952 N Fair Oaks AVE", cache)
        self.assertEqual(result, (None, None))
        self.assertEqual(cache, {})

    def test_in_area_result_kept(self):
        result, _ = self._geocode_with_response('[{"lat": "43.098", "lon": "-89.330"}]')
        self.assertEqual(result, (43.098, -89.330))


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


class GetZoningTest(unittest.TestCase):

    def test_network_error_not_cached(self):
        error = gd.urllib.error.URLError("timed out")
        cache = {}
        with mock.patch.object(gd.urllib.request, "urlopen", side_effect=error), \
                redirect_stdout(StringIO()):
            self.assertIsNone(gd.get_zoning(43.07, -89.38, cache))
        self.assertEqual(cache, {})


if __name__ == "__main__":
    unittest.main()
