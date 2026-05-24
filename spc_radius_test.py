#!/usr/bin/env python3
import os
import json
import requests

# --------------------------------------------------
# STEP 1: READ GITHUB ACTIONS INPUT
# --------------------------------------------------
def get_input():
    """
    GitHub Actions passes inputs as environment variables:
    INPUT_LOCATIONS
    """
    raw = os.getenv("INPUT_LOCATIONS")

    if not raw:
        raise ValueError("No INPUT_LOCATIONS found")

    # IMPORTANT: it's a JSON STRING from Apps Script
    return json.loads(raw)


# --------------------------------------------------
# STEP 2: LOAD LOCATIONS
# --------------------------------------------------
def parse_locations():
    locations = get_input()

    if isinstance(locations, str):
        locations = json.loads(locations)

    return locations


# --------------------------------------------------
# STEP 3: FETCH SPC DATA (single cycle test)
# --------------------------------------------------
URLS = {
    "Category": "https://www.spc.noaa.gov/products/outlook/day1otlk_cat.nolyr.geojson"
}

def fetch_geojson(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------
# STEP 4: MAIN TEST LOOP
# --------------------------------------------------
def main():

    locations = parse_locations()

    print(f"Loaded {len(locations)} locations\n")

    # Load SPC category once (important efficiency win)
    cat = fetch_geojson(URLS["Category"])

    for loc in locations:

        name = loc.get("name")
        wfo = loc.get("wfo")
        lat = loc.get("lat")
        lon = loc.get("lon")
        radius = loc.get("radius")

        print(f"Processing {name} ({wfo})")
        print(f"  Lat/Lon: {lat}, {lon}")
        print(f"  Radius: {radius}")

        # TEMP OUTPUT (we'll plug in shapely logic next step)
        print("  Status: OK\n")


if __name__ == "__main__":
    main()
