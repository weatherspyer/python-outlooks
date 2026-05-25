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
# URLS (not used directly here but kept for future)
# ==================================================

DAY48_URL = "https://www.spc.noaa.gov/products/exper/day4-8/day{}prob.nolyr.geojson"


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
# DAY PROCESSOR (SINGLE DAY ONLY)
# ==================================================

def process_day(lat, lon, radius):

    result = {
        "category": "",
        "Tornado": "",
        "Hail": "",
        "Wind": "",
        "Any": "",
        "indicator": "None",
        "distance": "",
        "direction": ""
    }

    # --------------------------------------------------
    # DAY 1 / 2
    # --------------------------------------------------

    if DAY in ["1", "2"]:

        url_map = {
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
            }
        }

        urls = url_map[DAY]

        cat_geo = fetch_geojson(urls["Category"])
        cat = analyze_risk(lat, lon, cat_geo, radius)

        result["category"] = cat["label"] or "None"

        hazards = ["Tornado", "Hail", "Wind"]

        if result["category"] == "None":
            for h in hazards:
                geo = fetch_geojson(urls[h])
                r = analyze_risk(lat, lon, geo, radius)
                result[h] = str(r["label"])

            result["indicator"] = "None"
            return result

        overall_indicator = "None"
        overall_distance = ""
        overall_direction = ""

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


    # --------------------------------------------------
    # DAY 3
    # --------------------------------------------------

    if DAY == "3":

        cat_url = "https://www.spc.noaa.gov/products/outlook/day3otlk_cat.nolyr.geojson"
        any_url = "https://www.spc.noaa.gov/products/outlook/day3otlk_prob.nolyr.geojson"

        cat = analyze_risk(lat, lon, fetch_geojson(cat_url), radius)
        any_r = analyze_risk(lat, lon, fetch_geojson(any_url), radius)

        result["category"] = cat["label"] or "None"
        result["Any"] = str(any_r["label"])

        # indicator logic
        if cat["indicator"] == "Point" or any_r["indicator"] == "Point":
            result["indicator"] = "Point"
        elif cat["indicator"] == "Radius":
            result["indicator"] = "Radius"
            result["distance"] = cat["distance"]
            result["direction"] = cat["direction"]
        elif any_r["indicator"] == "Radius":
            result["indicator"] = "Radius"
            result["distance"] = any_r["distance"]
            result["direction"] = any_r["direction"]

        return result


    # --------------------------------------------------
    # DAY 4–8
    # --------------------------------------------------

    url = DAY48_URL.format(DAY)
    r = analyze_risk(lat, lon, fetch_geojson(url), radius)

    result["Any"] = str(r["label"])
    result["indicator"] = r["indicator"]
    result["distance"] = r["distance"]
    result["direction"] = r["direction"]

    return result


# ==================================================
# MAIN
# ==================================================

def main():

    sheet = get_sheet()

    timestamp = datetime.now(
        ZoneInfo("America/New_York")
    ).strftime("%m/%d/%Y %H:%M")

    for loc in locations:

        name = loc.get("name")
        wfo = loc.get("wfo")
        region = loc.get("region", "")

        lat = float(loc.get("lat"))
        lon = float(loc.get("lon"))
        radius = float(loc.get("radius"))

        print(f"Processing {name} ({wfo})")

        r = process_day(lat, lon, radius)

        # --------------------------------------------------
        # STRICT DAY COLUMN ROUTING (ONLY ONE FILLED)
        # --------------------------------------------------

        day1 = day2 = day3 = day4 = day5 = day6 = day7 = day8 = ""

        if DAY == "1":
            day1 = r.get("category", "")
        elif DAY == "2":
            day2 = r.get("category", "")
        elif DAY == "3":
            day3 = r.get("Any", "")
        elif DAY == "4":
            day4 = r.get("Any", "")
        elif DAY == "5":
            day5 = r.get("Any", "")
        elif DAY == "6":
            day6 = r.get("Any", "")
        elif DAY == "7":
            day7 = r.get("Any", "")
        elif DAY == "8":
            day8 = r.get("Any", "")

        # --------------------------------------------------
        # ROW (MATCHES YOUR COLUMN ORDER EXACTLY)
        # --------------------------------------------------

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

            r["indicator"],
            r["distance"],
            r["direction"],

            day1,
            r["Tornado"],
            r["Hail"],
            r["Wind"],

            day2,
            r["Tornado"],
            r["Hail"],
            r["Wind"],

            day3,
            r["Any"],

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
