#!/usr/bin/env python3

import sys
import json
import math
import requests
import gspread

from shapely.geometry import shape, Point
from shapely.ops import nearest_points

from datetime import datetime
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials


# ==================================================
# INPUT PAYLOAD
# ==================================================

if len(sys.argv) < 2:
    raise ValueError("Missing JSON payload argument")


def get_payload():
    raw = sys.argv[1]

    print("\n================ INPUT DEBUG ================\n")
    print(raw)
    print("\n=============================================\n")

    return json.loads(raw)


payload = get_payload()

context = payload.get("context", {})
locations = payload.get("locations", [])

DAY = str(context.get("day"))
OUTLOOK_TYPE = context.get("outlook_type", "")
OUTLOOK_SOURCE = context.get("outlook_source", "")
ISSUE = context.get("issue", "")

print("\n================ CONTEXT ================\n")
print(json.dumps(context, indent=2))
print("\n=========================================\n")


# ==================================================
# GOOGLE SHEETS
# ==================================================

SHEET_ID = "1HSLnDqg243qkgVJb7tpsnKLEDiaLFM0cCLwU5LQndsg"
SHEET_NAME = "Log"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets"
]


def get_sheet():
    creds = Credentials.from_service_account_file(
        "credentials.json",
        scopes=SCOPES
    )

    gc = gspread.authorize(creds)

    return gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)


# ==================================================
# SPC URLS
# ==================================================

DAY_URLS = {

    "1": {
        "Category": "https://www.spc.noaa.gov/products/outlook/day1otlk_cat.nolyr.geojson",
        "Tornado": "https://www.spc.noaa.gov/products/outlook/day1otlk_torn.nolyr.geojson",
        "Hail": "https://www.spc.noaa.gov/products/outlook/day1otlk_hail.nolyr.geojson",
        "Wind": "https://www.spc.noaa.gov/products/outlook/day1otlk_wind.nolyr.geojson"
    },

    "2": {
        "Category": "https://www.spc.noaa.gov/products/outlook/day2otlk_cat.nolyr.geojson",
        "Tornado": "https://www.spc.noaa.gov/products/outlook/day2otlk_torn.nolyr.geojson",
        "Hail": "https://www.spc.noaa.gov/products/outlook/day2otlk_hail.nolyr.geojson",
        "Wind": "https://www.spc.noaa.gov/products/outlook/day2otlk_wind.nolyr.geojson"
    },

    "3": {
        "Category": "https://www.spc.noaa.gov/products/outlook/day3otlk_cat.nolyr.geojson",
        "Any": "https://www.spc.noaa.gov/products/outlook/day3otlk_prob.nolyr.geojson"
    }
}


CATEGORY_MAP = {
    "MRGL": "Marginal",
    "SLGT": "Slight",
    "ENH": "Enhanced",
    "MDT": "Moderate",
    "HIGH": "High",
    "TSTM": "None"
}


# ==================================================
# HELPERS
# ==================================================

def fetch_geojson(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def calculate_direction(lat1, lon1, lat2, lon2):

    dlon = math.radians(lon2 - lon1)

    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    x = math.sin(dlon) * math.cos(lat2)
    y = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    )

    bearing = (math.degrees(math.atan2(x, y)) + 360) % 360

    dirs = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW"
    ]

    return dirs[round(bearing / 22.5) % 16]


# ==================================================
# CORE ANALYSIS
# ==================================================

def analyze_risk(lat, lon, geojson, radius_miles):

    point = Point(lon, lat)
    radius_deg = radius_miles / 69.0
    search_area = point.buffer(radius_deg)

    best_dn = -1
    best_label = None
    best_indicator = "None"
    best_distance = ""
    best_direction = ""

    for feature in geojson.get("features", []):

        geom = feature.get("geometry")
        if not geom or geom.get("type") == "GeometryCollection":
            continue

        polygon = shape(geom)
        props = feature.get("properties", {})

        dn = props.get("DN", 0)
        label = props.get("LABEL")

        # POINT
        if polygon.contains(point):
            if dn > best_dn:
                best_dn = dn
                best_label = label
                best_indicator = "Point"
                best_distance = ""
                best_direction = ""

        # RADIUS
        elif polygon.intersects(search_area):
            if dn > best_dn:
                best_dn = dn
                best_label = label
                best_indicator = "Radius"

                nearest = nearest_points(point, polygon)[1]

                distance_miles = round(point.distance(nearest) * 69)

                direction = calculate_direction(
                    lat, lon,
                    nearest.y, nearest.x
                )

                best_distance = distance_miles
                best_direction = direction

    return {
        "label": best_label,
        "indicator": best_indicator,
        "distance": best_distance,
        "direction": best_direction
    }


# ==================================================
# DAY PROCESSOR (1 & 2)
# ==================================================

def process_day_1_or_2(day, lat, lon, radius):

    urls = DAY_URLS[day]

    results = {}

    overall_indicator = "None"
    overall_distance = ""
    overall_direction = ""

    # CATEGORY
    category_geo = fetch_geojson(urls["Category"])

    category = analyze_risk(lat, lon, category_geo, radius)

    results["category"] = CATEGORY_MAP.get(category["label"], "None")

    # ==================================================
    # HARD RULE (YOUR FIX)
    # ==================================================
    if results["category"] == "None":

        for hazard in ["Tornado", "Hail", "Wind"]:
            geo = fetch_geojson(urls[hazard])
            r = analyze_risk(lat, lon, geo, radius)
            results[hazard] = str(r["label"])

        results["indicator"] = "None"
        results["distance"] = ""
        results["direction"] = ""

        return results

    # HAZARDS (only if category exists)
    for hazard in ["Tornado", "Hail", "Wind"]:

        geo = fetch_geojson(urls[hazard])
        r = analyze_risk(lat, lon, geo, radius)

        results[hazard] = str(r["label"])

        if r["indicator"] == "Point":
            overall_indicator = "Point"
            overall_distance = ""
            overall_direction = ""

        elif r["indicator"] == "Radius" and overall_indicator != "Point":
            overall_indicator = "Radius"
            overall_distance = r["distance"]
            overall_direction = r["direction"]

    results["indicator"] = overall_indicator
    results["distance"] = overall_distance
    results["direction"] = overall_direction

    return results


# ==================================================
# DAY 3
# ==================================================

def process_day_3(lat, lon, radius):

    urls = DAY_URLS["3"]

    category_geo = fetch_geojson(urls["Category"])
    category = analyze_risk(lat, lon, category_geo, radius)

    any_geo = fetch_geojson(urls["Any"])
    any_r = analyze_risk(lat, lon, any_geo, radius)

    if category["indicator"] == "Point" or any_r["indicator"] == "Point":
        return {"indicator": "Point", "distance": "", "direction": ""}

    if category["indicator"] == "Radius":
        return category

    if any_r["indicator"] == "Radius":
        return any_r

    return {"indicator": "None", "distance": "", "direction": ""}


# ==================================================
# MAIN
# ==================================================

def main():

    if not locations:
        raise ValueError("No locations received")

    sheet = get_sheet()

    timestamp = datetime.now(
        ZoneInfo("America/New_York")
    ).strftime("%m/%d/%Y %H:%M")

    print(f"Loaded {len(locations)} locations\n")

    for loc in locations:

        name = loc.get("name")
        wfo = loc.get("wfo")
        region = loc.get("region", "")

        lat = float(loc.get("lat"))
        lon = float(loc.get("lon"))
        radius = float(loc.get("radius"))

        print(f"Processing {name} ({wfo})")

        d1 = process_day_1_or_2("1", lat, lon, radius)

        final_indicator = d1.get("indicator", "None")
        final_distance = d1.get("distance", "")
        final_direction = d1.get("direction", "")

        row = [

            timestamp,
            name,
            wfo,
            OUTLOOK_TYPE,
            OUTLOOK_SOURCE,
            DAY,
            ISSUE,

            "", "", "", "",

            region,
            "",
            "",

            "NEW",   # STATUS (NEW COLUMN ADDED)

            final_indicator,
            final_distance,
            final_direction,

            d1.get("category", ""),
            d1.get("Tornado", ""),
            d1.get("Hail", ""),
            d1.get("Wind", "")
        ]

        sheet.insert_row(row, 2)

        print(f"Inserted {name}")

    print("Run complete.")


if __name__ == "__main__":
    main()
