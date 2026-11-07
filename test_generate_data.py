"""Unit tests for generate_data.py (stdlib unittest; run: python3 -m unittest)."""

import csv
import json
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

    def _zoning_with_response(self, payload):
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = payload.encode()
        cache = {}
        with mock.patch.object(gd.urllib.request, "urlopen", return_value=resp), \
                redirect_stdout(StringIO()):
            result = gd.get_zoning(43.07, -89.38, cache)
        return result, cache

    def test_feature_returns_code(self):
        result, cache = self._zoning_with_response(
            '{"features": [{"attributes": {"ZONING_CODE": "UMX"}}]}')
        self.assertEqual(result, "UMX")
        self.assertEqual(cache, {"zone:43.07,-89.38": "UMX"})

    def test_empty_result_cached_as_miss(self):
        result, cache = self._zoning_with_response('{"features": []}')
        self.assertIsNone(result)
        self.assertEqual(cache, {"zone:43.07,-89.38": None})

    def test_api_error_body_not_cached(self):
        result, cache = self._zoning_with_response(
            '{"error": {"code": 400, "message": "Failed to execute query."}}')
        self.assertIsNone(result)
        self.assertEqual(cache, {})

    def test_network_error_not_cached(self):
        error = gd.urllib.error.URLError("timed out")
        cache = {}
        with mock.patch.object(gd.urllib.request, "urlopen", side_effect=error), \
                redirect_stdout(StringIO()):
            self.assertIsNone(gd.get_zoning(43.07, -89.38, cache))
        self.assertEqual(cache, {})


def _square(lat, lng, d=0.0002):
    """Tiny parcel polygon centered on (lat, lng), ArcGIS ring order (x=lng, y=lat)."""
    return {"rings": [[[lng - d, lat - d], [lng + d, lat - d],
                       [lng + d, lat + d], [lng - d, lat + d]]]}


class ParseStreetAddressTest(unittest.TestCase):

    def test_plain(self):
        self.assertEqual(
            gd.parse_street_address("8113 Grotto LN, Madison WI 53711 United States"),
            (8113, None, "Grotto"))

    def test_direction_and_multiword_name(self):
        self.assertEqual(gd.parse_street_address("952 N Fair Oaks AVE, Madison WI"),
                         (952, "N", "Fair Oaks"))

    def test_city_less(self):
        self.assertEqual(gd.parse_street_address("4205 Gallatin Range RD"),
                         (4205, None, "Gallatin Range"))

    def test_unparseable(self):
        self.assertIsNone(gd.parse_street_address("Lot 12, Madison WI"))


class GeocodeParcelTest(unittest.TestCase):

    ADDRESS = "9451 Spirit ST, Middleton WI 53562 United States"

    def _run(self, payload=None, error=None, cache=None):
        cache = {} if cache is None else cache
        if error is not None:
            patch = mock.patch.object(gd.urllib.request, "urlopen", side_effect=error)
        else:
            resp = mock.MagicMock()
            resp.__enter__.return_value.read.return_value = json.dumps(payload).encode()
            patch = mock.patch.object(gd.urllib.request, "urlopen", return_value=resp)
        with patch as urlopen, redirect_stdout(StringIO()):
            result = gd.geocode_parcel(self.ADDRESS, cache)
        return result, cache, urlopen

    def _features(self, *numbers_and_points):
        return {"features": [{"attributes": {"HouseNbr": n}, "geometry": _square(lat, lng)}
                             for n, lat, lng in numbers_and_points]}

    def test_exact_match_wins(self):
        (lat, lng, match), cache, _ = self._run(self._features(
            (9454, 43.10, -89.50), (9451, 43.11, -89.51)))
        self.assertEqual(match, "parcel")
        self.assertAlmostEqual(lat, 43.11)
        self.assertAlmostEqual(lng, -89.51)
        self.assertEqual(cache[f"parcel:{self.ADDRESS}"]["match"], "parcel")

    def test_nearest_within_window(self):
        (lat, _, match), _, urlopen = self._run(self._features(
            (9480, 43.12, -89.50), (9454, 43.10, -89.50)))
        self.assertEqual(match, "parcel_nearest")
        self.assertAlmostEqual(lat, 43.10)
        # The query itself enforces the half-block window
        url = urlopen.call_args[0][0].full_url
        self.assertIn("BETWEEN+9401+AND+9501", url)

    def test_no_parcels_cached_as_miss(self):
        result, cache, _ = self._run({"features": []})
        self.assertEqual(result, (None, None, None))
        self.assertEqual(cache[f"parcel:{self.ADDRESS}"],
                         {"lat": None, "lng": None, "match": None})

    def test_out_of_area_parcel_rejected(self):
        result, _, _ = self._run(self._features((9451, 34.16, -118.15)))
        self.assertEqual(result, (None, None, None))

    def test_api_error_body_not_cached(self):
        result, cache, _ = self._run({"error": {"code": 400}})
        self.assertEqual(result, (None, None, None))
        self.assertEqual(cache, {})

    def test_network_error_not_cached(self):
        result, cache, _ = self._run(error=gd.urllib.error.URLError("down"))
        self.assertEqual(result, (None, None, None))
        self.assertEqual(cache, {})

    def test_cached_result_skips_request(self):
        cache = {f"parcel:{self.ADDRESS}": {"lat": 43.1, "lng": -89.5, "match": "parcel"}}
        result, _, urlopen = self._run({"features": []}, cache=cache)
        self.assertEqual(result, (43.1, -89.5, "parcel"))
        urlopen.assert_not_called()


class StepGeocodeTest(unittest.TestCase):

    def _run(self, nominatim, parcel):
        project = {"address": "8113 Grotto LN, Madison WI 53711"}
        cache = {f"geo:{project['address']}": {"lat": None, "lng": None}}
        with mock.patch.object(gd, "geocode", return_value=nominatim), \
                mock.patch.object(gd, "geocode_parcel", return_value=parcel) as fallback, \
                mock.patch.object(gd, "save_cache"), mock.patch.object(gd.time, "sleep"), \
                redirect_stdout(StringIO()):
            gd._step_geocode([project], cache)
        return project, fallback

    def test_nominatim_hit_skips_parcel_fallback(self):
        project, fallback = self._run((43.07, -89.38), (None, None, None))
        self.assertEqual(project["geocode_source"], "nominatim")
        fallback.assert_not_called()

    def test_falls_back_to_parcel(self):
        project, _ = self._run((None, None), (43.03, -89.52, "parcel_nearest"))
        self.assertEqual((project["lat"], project["geocode_source"]), (43.03, "parcel_nearest"))

    def test_unlocated_has_empty_source(self):
        project, _ = self._run((None, None), (None, None, None))
        self.assertEqual((project["lat"], project["geocode_source"]), (None, ""))


if __name__ == "__main__":
    unittest.main()
