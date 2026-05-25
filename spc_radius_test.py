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

    spreadsheet = gc.open_by_key(SHEET_ID)

    return spreadsheet.worksheet(SHEET_NAME)


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

DAY48_URL = "https://www.spc.noaa.gov/products/exper/day4-8/day{}prob.nolyr.geojson"


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

    response = requests.get(url, timeout=30)

    response.raise_for_status()

    return response.json()


def format_probability(label):

    if not label:
        return "None"

    try:
        return f"{float(label) * 100:.0f}%"

    except:
        return str(label)


def calculate_direction(lat1, lon1, lat2, lon2):

    dlon = math.radians(lon2 - lon1)

    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    x = math.sin(dlon) * math.cos(lat2)

    y = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    )

    initial_bearing = math.atan2(x, y)

    bearing = (math.degrees(initial_bearing) + 360) % 360

    directions = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW"
    ]

    index = round(bearing / 22.5) % 16

    return directions[index]


# ==================================================
# CORE CHECK LOGIC
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

        if not geom:
            continue

        if geom.get("type") == "GeometryCollection":
            continue

        polygon = shape(geom)

        props = feature.get("properties", {})

        dn = props.get("DN", 0)

        label = props.get("LABEL")

        # ------------------------------------------
        # POINT HIT
        # ------------------------------------------

        if polygon.contains(point):

            if dn > best_dn:

                best_dn = dn

                best_label = label

                best_indicator = "Point"

                best_distance = ""

                best_direction = ""

        # ------------------------------------------
        # RADIUS HIT
        # ------------------------------------------

        elif polygon.intersects(search_area):

            if dn > best_dn:

                best_dn = dn

                best_label = label

                best_indicator = "Radius"

                nearest_geom = nearest_points(point, polygon)[1]

                nearest_lon = nearest_geom.x
                nearest_lat = nearest_geom.y

                distance_deg = point.distance(nearest_geom)

                distance_miles = round(distance_deg * 69)

                direction = calculate_direction(
                    lat,
                    lon,
                    nearest_lat,
                    nearest_lon
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
# DAY PROCESSORS
# ==================================================

def process_day_1_or_2(day, lat, lon, radius):

    urls = DAY_URLS[day]

    results = {}

    overall_indicator = "None"
    overall_distance = ""
    overall_direction = ""

    # -----------------------------
    # CATEGORY
    # -----------------------------

    category_geo = fetch_geojson(urls["Category"])

    category = analyze_risk(
        lat,
        lon,
        category_geo,
        radius
    )

    results["category"] = CATEGORY_MAP.get(
        category["label"],
        "None"
    )

    overall_indicator = category["indicator"]
    overall_distance = category["distance"]
    overall_direction = category["direction"]

    # -----------------------------
    # HAZARDS
    # -----------------------------

    for hazard in ["Tornado", "Hail", "Wind"]:

        geo = fetch_geojson(urls[hazard])

        result = analyze_risk(
            lat,
            lon,
            geo,
            radius
        )

        results[hazard] = format_probability(
            result["label"]
        )

        # PRIORITY:
        # Point > Radius > None

        if result["indicator"] == "Point":

            overall_indicator = "Point"
            overall_distance = ""
            overall_direction = ""

        elif (
            result["indicator"] == "Radius"
            and overall_indicator != "Point"
        ):

            overall_indicator = "Radius"
            overall_distance = result["distance"]
            overall_direction = result["direction"]

    results["indicator"] = overall_indicator
    results["distance"] = overall_distance
    results["direction"] = overall_direction

    return results


def process_day_3(lat, lon, radius):

    urls = DAY_URLS["3"]

    results = {}

    category_geo = fetch_geojson(urls["Category"])

    category = analyze_risk(
        lat,
        lon,
        category_geo,
        radius
    )

    results["category"] = CATEGORY_MAP.get(
        category["label"],
        "None"
    )

    any_geo = fetch_geojson(urls["Any"])

    any_result = analyze_risk(
        lat,
        lon,
        any_geo,
        radius
    )

    results["Any"] = format_probability(
        any_result["label"]
    )

    # PRIORITY

    if category["indicator"] == "Point" or any_result["indicator"] == "Point":

        results["indicator"] = "Point"
        results["distance"] = ""
        results["direction"] = ""

    elif category["indicator"] == "Radius":

        results["indicator"] = "Radius"
        results["distance"] = category["distance"]
        results["direction"] = category["direction"]

    elif any_result["indicator"] == "Radius":

        results["indicator"] = "Radius"
        results["distance"] = any_result["distance"]
        results["direction"] = any_result["direction"]

    else:

        results["indicator"] = "None"
        results["distance"] = ""
        results["direction"] = ""

    return results


def process_day_4_to_8(day, lat, lon, radius):

    url = DAY48_URL.format(day)

    geo = fetch_geojson(url)

    result = analyze_risk(
        lat,
        lon,
        geo,
        radius
    )

    return {
        "Any": format_probability(result["label"]),
        "indicator": result["indicator"],
        "distance": result["distance"],
        "direction": result["direction"]
    }


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

        # ==================================================
        # DAY-SPECIFIC PROCESSING
        # ==================================================

        d1 = d2 = d3 = d4 = d5 = d6 = d7 = d8 = {}

        if DAY == "1":
            d1 = process_day_1_or_2("1", lat, lon, radius)

        elif DAY == "2":
            d2 = process_day_1_or_2("2", lat, lon, radius)

        elif DAY == "3":
            d3 = process_day_3(lat, lon, radius)

        elif DAY in ["4", "5", "6", "7", "8"]:

            result = process_day_4_to_8(
                DAY,
                lat,
                lon,
                radius
            )

            if DAY == "4":
                d4 = result

            elif DAY == "5":
                d5 = result

            elif DAY == "6":
                d6 = result

            elif DAY == "7":
                d7 = result

            elif DAY == "8":
                d8 = result

        # ==================================================
        # FINAL INDICATOR
        # ==================================================

        final_indicator = "None"
        final_distance = ""
        final_direction = ""

        for dataset in [d1, d2, d3, d4, d5, d6, d7, d8]:

            if not dataset:
                continue

            if dataset.get("indicator") == "Point":

                final_indicator = "Point"
                final_distance = ""
                final_direction = ""

                break

            elif (
                dataset.get("indicator") == "Radius"
                and final_indicator != "Point"
            ):

                final_indicator = "Radius"
                final_distance = dataset.get("distance", "")
                final_direction = dataset.get("direction", "")

        # ==================================================
        # BUILD FINAL ROW
        # ==================================================

        row = [

            # ------------------------------------------
            # CORE
            # ------------------------------------------

            timestamp,
            name,
            wfo,
            OUTLOOK_TYPE,
            OUTLOOK_SOURCE,
            DAY,
            ISSUE,

            # ------------------------------------------
            # RESERVED
            # ------------------------------------------

            "",     # Threat Emoji
            "",     # Day Emoji
            "",     # Outlook Type Emoji
            "",     # Outlook Threat Type

            # ------------------------------------------
            # REGION / TITLE / TOGGLE
            # ------------------------------------------

            region,
            "",     # Title
            "",     # Toggle

            # ------------------------------------------
            # INDICATOR
            # ------------------------------------------

            final_indicator,
            final_distance,
            final_direction,

            # ------------------------------------------
            # DAY 1
            # ------------------------------------------

            d1.get("category", ""),
            d1.get("Tornado", ""),
            d1.get("Hail", ""),
            d1.get("Wind", ""),

            # ------------------------------------------
            # DAY 2
            # ------------------------------------------

            d2.get("category", ""),
            d2.get("Tornado", ""),
            d2.get("Hail", ""),
            d2.get("Wind", ""),

            # ------------------------------------------
            # DAY 3
            # ------------------------------------------

            d3.get("category", ""),
            d3.get("Any", ""),

            # ------------------------------------------
            # DAY 4-8
            # ------------------------------------------

            d4.get("Any", ""),
            d5.get("Any", ""),
            d6.get("Any", ""),
            d7.get("Any", ""),
            d8.get("Any", "")
        ]

        sheet.insert_row(row, index=2)

        print(f"Inserted row for {name}\n")

    print("Run complete.")


# ==================================================
# ENTRY POINT
# ==================================================

if __name__ == "__main__":
    main()
