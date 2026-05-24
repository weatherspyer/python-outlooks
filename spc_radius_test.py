#!/usr/bin/env python3
import os
import json
import requests
import sys

# --------------------------------------------------
# STEP 1: READ GITHUB INPUT (RAW)
# --------------------------------------------------
def get_raw_input():
    raw = os.getenv("INPUT_LOCATIONS")

    print("\n================ INPUT DEBUG ================\n")
    print("RAW ENV INPUT:")
    print(raw)
    print("\n=============================================\n")

    if not raw:
        raise ValueError("No INPUT_LOCATIONS found")

    return raw


# --------------------------------------------------
# STEP 2: PARSE INPUT SAFELY
# --------------------------------------------------
def parse_locations():
    raw = get_raw_input()

    try:
        data = json.loads(raw)
    except Exception as e:
        print("FAILED TO PARSE JSON")
        print(f"Error: {e}")
        print(f"Raw input: {raw}")
        sys.exit(1)

    # Handles double-encoded JSON if needed
    if isinstance(data, str):
        print("Detected double-encoded JSON, decoding again...")
        data = json.loads(data)

    return data


# --------------------------------------------------
# STEP 3: FETCH SPC DATA
# --------------------------------------------------
URLS = {
    "Category": "https://www.spc.noaa.gov/products/outlook/day1otlk_cat.nolyr.geojson"
}

def fetch_geojson(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------
# STEP 4: MAIN
# --------------------------------------------------
def main():

    locations = parse_locations()

    print("\n================ PARSED INPUT ================\n")

    print(f"Type: {type(locations)}")

    if isinstance(locations, dict):
        print("Context:")
        print(json.dumps(locations.get("context", {}), indent=2))

        locations = locations.get("locations", [])

    print(f"\nLoaded {len(locations)} locations\n")

    # Preview first location for verification
    if locations:
        print("Sample location:")
        print(json.dumps(locations[0], indent=2))
        print("\n")

    # Load SPC category once
    cat = fetch_geojson(URLS["Category"])

    # --------------------------------------------------
    # PROCESS LOCATIONS
    # --------------------------------------------------
    for loc in locations:

        name = loc.get("name")
        wfo = loc.get("wfo")
        lat = loc.get("lat")
        lon = loc.get("lon")
        radius = loc.get("radius")

        print(f"Processing {name} ({wfo})")
        print(f"  Lat/Lon: {lat}, {lon}")
        print(f"  Radius: {radius}")

        print("  Status: OK\n")


if __name__ == "__main__":
    main()
