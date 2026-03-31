#!/usr/bin/env python3
"""Merge manually-downloaded ELAM permit CSV files into permits_merged.csv.

Input files must follow the naming pattern MMDDYYYY-MMDDYYYY.csv
(e.g. 01012015-03152026.csv). Files are merged oldest-to-newest by end date;
when the same Record Number appears in multiple files, the row from the
latest-end-date file wins (preserves most up-to-date status).

Usage:
    python merge_permits.py
"""

import csv
import glob
import os
import re
import sys
from datetime import datetime

OUTPUT_FILE = "permits_merged.csv"
FILENAME_RE = re.compile(r"^(\d{8})-(\d{8})\.csv$")
FIELDS = ["Date", "Record Number", "Record Type", "Address", "Status",
          "Description", "Project Name", "Short Notes"]


def parse_filename_date(datestr):
    """Parse MMDDYYYY string to a datetime for sorting."""
    return datetime.strptime(datestr, "%m%d%Y")


def find_input_files():
    files = []
    for path in glob.glob("*.csv"):
        name = os.path.basename(path)
        m = FILENAME_RE.match(name)
        if not m:
            continue
        try:
            end_date = parse_filename_date(m.group(2))
        except ValueError:
            print(f"  warning: skipping {name} (unparseable date)", file=sys.stderr)
            continue
        files.append((end_date, path))
    files.sort()  # oldest end date first → newest wins on conflict
    return files


def main():
    files = find_input_files()
    if not files:
        sys.exit("error: no MMDDYYYY-MMDDYYYY.csv files found in current directory")

    print(f"Found {len(files)} file(s):")
    for end_date, path in files:
        print(f"  {path}  (end {end_date.strftime('%Y-%m-%d')})")

    records = {}   # Record Number → row dict
    total_rows = 0

    for _end_date, path in files:
        file_rows = 0
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = row.get("Record Number", "").strip()
                if not key:
                    continue
                records[key] = row
                file_rows += 1
        total_rows += file_rows
        print(f"  {path}: {file_rows} rows")

    unique = len(records)
    duplicates = total_rows - unique
    print(f"\n{total_rows} total rows → {unique} unique records, {duplicates} duplicate(s) removed")

    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records.values())
    os.replace(tmp, OUTPUT_FILE)
    print(f"Written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
