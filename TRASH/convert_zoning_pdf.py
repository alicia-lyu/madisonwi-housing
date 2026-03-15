#!/usr/bin/env python3
"""Convert ZoningTable.pdf to zoning_districts.csv.

Uses pdftotext (from poppler) with -layout flag to preserve column positions,
then parses the fixed-width layout into structured CSV.
"""

import csv
import os
import re
import subprocess
import sys

PDF_FILE = "ZoningTable.pdf"
OUTPUT_CSV = "zoning_districts.csv"

# Known district codes (used as line anchors to identify row starts)
KNOWN_CODES = [
    "TR-R", "SR-C1", "SR-C2", "SR-C3", "TR-C1", "TR-C2", "TR-C3", "TR-C4",
    "SR-V1", "TR-V1", "SR-V2", "TR-V2", "TR-U1", "TR-U2", "TR-P",
    "LMX", "NMX", "TSS", "CC-T", "CC", "RMX", "MXC", "THV",
    "DR1", "DR2", "UOR", "UMX", "DC",
    "SE", "TE", "EC", "SEC", "IL", "IG",
    "A", "UA", "CN", "PR", "AP", "ME", "MC", "CI", "PD", "PMHP",
]

# Category headers that appear in the PDF
CATEGORY_HEADERS = {
    "Residential Districts": "Residential",
    "Mixed Use and Commercial Districts": "Mixed-Use & Commercial",
    "Downtown and Urban District": "Downtown & Urban",
    "Employment Districts": "Employment",
    "Special Districts": "Special",
}

# Build regex to match district code at line start
CODE_RE = re.compile(
    r"^(" + "|".join(re.escape(c) for c in sorted(KNOWN_CODES, key=len, reverse=True)) + r")\b"
)


def extract_text():
    """Run pdftotext -layout and return the text."""
    result = subprocess.run(
        ["pdftotext", "-layout", PDF_FILE, "-"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def find_column_positions(lines):
    """Find approximate column boundaries from header lines.
    Returns dict of page-section column positions."""
    # Default column positions (character offsets) observed in the PDF layout
    # These are approximate — we'll use them as guides
    return {
        "name_start": 10,
        "desc_start": 48,
        "permitted_start": 115,
        "conditional_start": 165,
        "stories_start": 215,
        "density_start": 235,
    }


def extract_field(line, start, end):
    """Extract a field from a fixed-width line, handling short lines."""
    if start >= len(line):
        return ""
    return line[start:end].strip() if end else line[start:].strip()


def clean_text(text):
    """Normalize whitespace and dashes."""
    text = re.sub(r"\s+", " ", text).strip()
    # Normalize unicode dashes to ASCII
    text = text.replace("\u2013", "-").replace("\u2012", "-").replace("\u2010", "-")
    return text


def parse_pages(text):
    """Parse the pdftotext layout output into zoning district records."""
    lines = text.split("\n")
    records = []
    current_category = ""
    current_record = None

    # Track column positions - they vary slightly by page
    cols = find_column_positions(lines)

    i = 0
    while i < len(lines):
        line = lines[i]
        raw_line = line

        # Check for category headers
        stripped = line.strip()
        for header, cat_name in CATEGORY_HEADERS.items():
            if stripped == header:
                current_category = cat_name
                break

        # Skip page headers, footers, footnotes, blank lines
        if (stripped.startswith("Page ") or
            stripped.startswith("Zoning District Summary") or
            stripped.startswith("*") or
            stripped.startswith("^") or
            stripped.startswith("feet of") or
            stripped.startswith("single family") or
            not stripped or
            stripped.startswith("District") or
            stripped.startswith("Max.") or
            stripped.startswith("Units per") or
            stripped.startswith("October") or
            stripped.startswith("Please") or
            stripped.startswith("This document") or
            stripped.startswith("(lot size") or
            stripped.startswith("(Chapter") or
            stripped.startswith("Permitted Use") or
            stripped.startswith("Conditional Use") or
            stripped.startswith("with the use")):
            i += 1
            continue

        # Check if line starts with a known district code
        m = CODE_RE.match(stripped)
        if m:
            # Save previous record
            if current_record:
                records.append(current_record)

            code = m.group(1)

            # Find the code position in the raw line
            code_pos = raw_line.find(code)
            after_code = code_pos + len(code)

            # Extract fields using approximate column positions
            # Adjust positions relative to actual line content
            name_text = extract_field(raw_line, after_code, after_code + 45)
            desc_text = extract_field(raw_line, cols["desc_start"], cols["permitted_start"])
            permitted_text = extract_field(raw_line, cols["permitted_start"], cols["conditional_start"])
            conditional_text = extract_field(raw_line, cols["conditional_start"], cols["stories_start"])
            stories_text = extract_field(raw_line, cols["stories_start"], cols["density_start"])
            density_text = extract_field(raw_line, cols["density_start"], None)

            current_record = {
                "category": current_category,
                "code": code,
                "name": name_text,
                "description": desc_text,
                "permitted": permitted_text,
                "conditional": conditional_text,
                "max_stories": stories_text,
                "max_density": density_text,
            }
        elif current_record and stripped and not any(
            stripped.startswith(h) for h in CATEGORY_HEADERS
        ):
            # Continuation line — append to relevant fields based on position
            # Find first non-space character position
            first_char = len(raw_line) - len(raw_line.lstrip())

            if first_char < cols["desc_start"]:
                # Could be name or description continuation
                if first_char < 45:
                    current_record["name"] += " " + stripped
                else:
                    current_record["description"] += " " + stripped
            elif first_char < cols["permitted_start"]:
                current_record["description"] += " " + extract_field(
                    raw_line, cols["desc_start"], cols["permitted_start"])
                p = extract_field(raw_line, cols["permitted_start"], cols["conditional_start"])
                if p:
                    current_record["permitted"] += " " + p
                c = extract_field(raw_line, cols["conditional_start"], cols["stories_start"])
                if c:
                    current_record["conditional"] += " " + c
                s = extract_field(raw_line, cols["stories_start"], cols["density_start"])
                if s:
                    current_record["max_stories"] += " " + s
                d = extract_field(raw_line, cols["density_start"], None)
                if d:
                    current_record["max_density"] += " " + d
            elif first_char < cols["conditional_start"]:
                p = extract_field(raw_line, cols["permitted_start"], cols["conditional_start"])
                if p:
                    current_record["permitted"] += " " + p
                c = extract_field(raw_line, cols["conditional_start"], cols["stories_start"])
                if c:
                    current_record["conditional"] += " " + c
                s = extract_field(raw_line, cols["stories_start"], cols["density_start"])
                if s:
                    current_record["max_stories"] += " " + s
                d = extract_field(raw_line, cols["density_start"], None)
                if d:
                    current_record["max_density"] += " " + d
            elif first_char < cols["stories_start"]:
                c = extract_field(raw_line, cols["conditional_start"], cols["stories_start"])
                if c:
                    current_record["conditional"] += " " + c
                s = extract_field(raw_line, cols["stories_start"], cols["density_start"])
                if s:
                    current_record["max_stories"] += " " + s
                d = extract_field(raw_line, cols["density_start"], None)
                if d:
                    current_record["max_density"] += " " + d
            else:
                s = extract_field(raw_line, cols["stories_start"], cols["density_start"])
                if s:
                    current_record["max_stories"] += " " + s
                d = extract_field(raw_line, cols["density_start"], None)
                if d:
                    current_record["max_density"] += " " + d

        i += 1

    # Don't forget the last record
    if current_record:
        records.append(current_record)

    # Clean up all fields
    for r in records:
        for key in r:
            r[key] = clean_text(r[key])

    return records


def main():
    if not os.path.exists(PDF_FILE):
        print(f"Error: {PDF_FILE} not found")
        sys.exit(1)

    print(f"Extracting text from {PDF_FILE}...")
    text = extract_text()

    print("Parsing zoning districts...")
    records = parse_pages(text)

    print(f"Found {len(records)} districts")
    print()

    # Print summary for verification
    for r in records:
        permitted_short = (r["permitted"][:40] + "...") if len(r["permitted"]) > 40 else r["permitted"]
        conditional_short = (r["conditional"][:40] + "...") if len(r["conditional"]) > 40 else r["conditional"]
        print(f"  {r['code']:6s} | {r['category']:25s} | {r['name'][:40]:40s} | "
              f"P: {permitted_short:43s} | C: {conditional_short}")

    # Write CSV
    fieldnames = [
        "category", "code", "name", "description",
        "residential_permitted", "residential_conditional",
        "max_stories", "max_density",
    ]
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow({
                "category": r["category"],
                "code": r["code"],
                "name": r["name"],
                "description": r["description"],
                "residential_permitted": r["permitted"],
                "residential_conditional": r["conditional"],
                "max_stories": r["max_stories"],
                "max_density": r["max_density"],
            })

    print(f"\nWrote {OUTPUT_CSV} with {len(records)} districts")


if __name__ == "__main__":
    main()
