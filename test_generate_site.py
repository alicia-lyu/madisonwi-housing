"""Unit tests for generate_site.py (stdlib unittest; run: python3 -m unittest)."""

import unittest

import generate_site as gs

APPROX_NOTE = "Location approximate"


def _row(**overrides):
    row = {"project_name": "", "address": "9451 Spirit ST, Middleton WI", "units": "8",
           "zoning": "SR-C3", "status": "Issued", "use_type": "UNKNOWN",
           "outcome": "ACTIVE", "housing_type": "Multiplex", "date": "2026-05-01",
           "record_number": "BLDNCC-2026-00001", "description": "new 8 unit apartment",
           "lat": "43.1", "lng": "-89.5", "geocode_source": "nominatim"}
    row.update(overrides)
    return row


class PopupApproximateNoteTest(unittest.TestCase):

    def test_note_for_nearest_parcel(self):
        self.assertIn(APPROX_NOTE, gs.build_popup_html(_row(geocode_source="parcel_nearest")))

    def test_no_note_for_exact_locations(self):
        for source in ("nominatim", "parcel", ""):
            with self.subTest(source=source):
                self.assertNotIn(APPROX_NOTE, gs.build_popup_html(_row(geocode_source=source)))

    def test_no_note_for_legacy_rows_without_column(self):
        row = _row()
        del row["geocode_source"]
        self.assertNotIn(APPROX_NOTE, gs.build_popup_html(row))


if __name__ == "__main__":
    unittest.main()
