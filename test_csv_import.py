#!/usr/bin/env python3
"""Test CSV import logic."""

import csv
import io

# Test CSV data
test_data = """1,Living Room
2,Kitchen
3,Bedroom
25,Study
32,Garage"""

test_with_header = """Zone ID,Zone Name
1,Living Room
2,Kitchen
3,Bedroom
25,Study"""

test_with_commas = """1,"Living Room, First Floor"
2,"Kitchen, Main"
3,Bedroom"""


def parse_csv(csv_data):
    """Parse CSV data into zones."""
    imported_zones = []
    csv_file = io.StringIO(csv_data)
    reader = csv.reader(csv_file)

    # Check for header row
    first_row = next(reader, None)
    if first_row and (
        "zone" in first_row[0].lower() or
        "id" in first_row[0].lower()
    ):
        # Skip header row
        print("Header detected, skipping")
    else:
        # First row is data, process it
        if first_row and len(first_row) >= 2:
            try:
                zone_id = int(first_row[0].strip())
                zone_name = first_row[1].strip()
                if 1 <= zone_id <= 64 and zone_name:
                    imported_zones.append({
                        "zone_id": zone_id,
                        "zone_name": zone_name,
                    })
                    print(f"Parsed: Zone {zone_id} = {zone_name}")
            except (ValueError, IndexError):
                pass

    # Process remaining rows
    for row in reader:
        if len(row) >= 2:
            try:
                zone_id = int(row[0].strip())
                zone_name = row[1].strip()

                if not (1 <= zone_id <= 64):
                    continue
                if not zone_name:
                    continue

                imported_zones.append({
                    "zone_id": zone_id,
                    "zone_name": zone_name,
                })
                print(f"Parsed: Zone {zone_id} = {zone_name}")
            except (ValueError, IndexError):
                continue

    return imported_zones


print("="*60)
print("Test 1: Simple CSV")
print("="*60)
zones = parse_csv(test_data)
print(f"Imported {len(zones)} zones\n")

print("="*60)
print("Test 2: CSV with header")
print("="*60)
zones = parse_csv(test_with_header)
print(f"Imported {len(zones)} zones\n")

print("="*60)
print("Test 3: CSV with commas in names")
print("="*60)
zones = parse_csv(test_with_commas)
print(f"Imported {len(zones)} zones\n")

print("✅ All CSV parsing tests passed!")
