#!/usr/bin/env python3
import sys
import json
import requests
import base64

def get_payload():
    if len(sys.argv) < 2:
        raise ValueError("Missing payload")

    encoded = sys.argv[1]

    print("\n================ RAW BASE64 INPUT ================\n")
    print(encoded)
    print("\n==================================================\n")

    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except Exception as e:
        raise ValueError(f"Base64 decode failed: {e}")

    print("\n================ DECODED JSON ====================\n")
    print(decoded)
    print("\n==================================================\n")

    return json.loads(decoded)


# --------------------------------------------------
# STEP 2: FETCH SPC GEOJSON
# --------------------------------------------------
URLS = {
    "Category": "https://www.spc.noaa.gov/products/outlook/day1otlk_cat.nolyr.geojson"
}

def fetch_geojson(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------
# STEP 3: MAIN PROCESS
# --------------------------------------------------
def main():

    payload = get_payload()

    context = payload.get("context", {})
    locations = payload.get("locations", [])

    print("\n================ PARSED INPUT ================\n")

    print("Context:")
    print(json.dumps(context, indent=2))

    print(f"\nLoaded {len(locations)} locations\n")

    if not locations:
        raise ValueError("No locations received")

    print("Sample location:")
    print(json.dumps(locations[0], indent=2))
    print("\n")

    # --------------------------------------------------
    # LOAD SPC DATA ONCE (efficiency)
    # --------------------------------------------------
    cat = fetch_geojson(URLS["Category"])

    print("SPC Category data loaded successfully\n")

    # --------------------------------------------------
    # PROCESS EACH LOCATION
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

        # Placeholder for your future shapely logic
        print("  Status: OK\n")

    print("Run complete.")


# --------------------------------------------------
# ENTRY POINT
# --------------------------------------------------
if __name__ == "__main__":
    main()
