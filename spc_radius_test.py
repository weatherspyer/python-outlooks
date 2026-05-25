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
# INPUT
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

DAY = str(context.get("day", ""))
OUTLOOK_TYPE = context.get("outlook_type", "")
OUTLOOK_SOURCE = context.get("outlook_source", "")
ISSUE = context.get("issue", "")


# ==================================================
# SHEETS
# ==================================================

SHEET_ID = "1HSLnDqg243qkgVJb7tpsnKLEDiaLFM0cCLwU5LQndsg"
SHEET_NAME = "Log"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_sheet():
    creds = Credentials.from_service_account_file(
        "credentials.json",
        scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)


# ==================================================
# URLS
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
# DAY ENGINE (SINGLE DAY ONLY)
# ==================================================

def process_day(lat, lon, radius):

    # -------------------------
    # DAY 1–3
    # -------------------------
    if DAY in ["1", "2", "3"]:

        urls = DAY_URLS[DAY]

        result = {}

        category_geo = fetch_geojson(urls["Category"])
        category = analyze_risk(lat, lon, category_geo, radius)

        result["category"] = CATEGORY_MAP.get(category["label"], "None")

        # DAY 3 special
        if DAY == "3":
            any_geo = fetch_geojson(urls["Any"])
            any_r = analyze_risk(lat, lon, any_geo, radius)
            result["Any"] = str(any_r["label"])

            result["indicator"] = any_r["indicator"]
            result["distance"] = any_r["distance"]
            result["direction"] = any_r["direction"]

            return result

        # DAY 1–2 hazards
        hazards = ["Tornado", "Hail", "Wind"]

        overall_indicator = "None"
        overall_distance = ""
        overall_direction = ""

        # FIX RULE: if category is None → indicator forced None
        if result["category"] == "None":

            for h in hazards:
                geo = fetch_geojson(urls[h])
                r = analyze_risk(lat, lon, geo, radius)
                result[h] = str(r["label"])

            result["indicator"] = "None"
            result["distance"] = ""
            result["direction"] = ""
            return result

        for h in hazards:

            geo = fetch_geojson(urls[h])
            r = analyze_risk(lat, lon, geo, radius)

            result[h] = str(r["label"])

            if r["indicator"] == "Point":
                overall_indicator = "Point"
                overall_distance = ""
                overall_direction = ""

            elif r["indicator"] == "Radius" and overall_indicator != "Point":
                overall_indicator = "Radius"
                overall_distance = r["distance"]
                overall_direction = r["direction"]

        result["indicator"] = overall_indicator
        result["distance"] = overall_distance
        result["direction"] = overall_direction

        return result


    # -------------------------
    # DAY 4–8
    # -------------------------
    url = DAY48_URL.format(DAY)

    geo = fetch_geojson(url)
    r = analyze_risk(lat, lon, geo, radius)

    return {
        "Any": str(r["label"]),
        "indicator": r["indicator"],
        "distance": r["distance"],
        "direction": r["direction"]
    }


# ==================================================
# MAIN
# ==================================================

def main():

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

        result = process_day(lat, lon, radius)

        # =========================
        # DAY COLUMN ROUTING
        # =========================

        day1 = day2 = day3 = day4 = day5 = day6 = day7 = day8 = ""

        if DAY == "1":
            day1 = result.get("category", "")
        elif DAY == "2":
            day2 = result.get("category", "")
        elif DAY == "3":
            day3 = result.get("Any", "")
        elif DAY == "4":
            day4 = result.get("Any", "")
        elif DAY == "5":
            day5 = result.get("Any", "")
        elif DAY == "6":
            day6 = result.get("Any", "")
        elif DAY == "7":
            day7 = result.get("Any", "")
        elif DAY == "8":
            day8 = result.get("Any", "")

        # =========================
        # ROW BUILD
        # =========================

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
            "NEW",

            result.get("indicator", ""),
            result.get("distance", ""),
            result.get("direction", ""),

            day1,
            result.get("Tornado", ""),
            result.get("Hail", ""),
            result.get("Wind", ""),

            day2,
            result.get("Tornado", ""),
            result.get("Hail", ""),
            result.get("Wind", ""),

            day3,
            result.get("Any", ""),

            day4,
            day5,
            day6,
            day7,
            day8
        ]

        sheet.insert_row(row, 2)

        print(f"Inserted {name}")

    print("Run complete.")


if __name__ == "__main__":
    main()
