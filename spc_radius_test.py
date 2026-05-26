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


payload = json.loads(sys.argv[1])

context = payload.get("context", {})
locations = payload.get("locations", [])

DAY = str(context.get("day", ""))
OUTLOOK_TYPE = context.get("outlook_type", "")
OUTLOOK_SOURCE = context.get("outlook_source", "")
ISSUE = context.get("issue", "")


# ==================================================
# RISK MAP (FIXED OUTPUT STANDARDIZATION)
# ==================================================

RISK_MAP = {
    "MRGL": "Marginal",
    "SLGT": "Slight",
    "ENH": "Enhanced",
    "MDT": "Moderate",
    "HIGH": "High",
    "TSTM": "None",
    None: "None",
    "": "None"
}


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
    return gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)


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
    search_area = point.buffer(radius_miles / 69.0)

    best = {
        "label": "None",
        "indicator": "None",
        "distance": "",
        "direction": ""
    }

    best_dn = -1

    for feature in geojson.get("features", []):

        geom = feature.get("geometry")
        if not geom or geom.get("type") == "GeometryCollection":
            continue

        polygon = shape(geom)
        props = feature.get("properties", {})

        raw = props.get("LABEL")

        # ==================================================
        # RISK NORMALIZATION (FIXED)
        # ==================================================
        label = RISK_MAP.get(raw, "None")

        dn = props.get("DN", 0)

        if polygon.contains(point):
            if dn > best_dn:
                best_dn = dn
                best = {
                    "label": label,
                    "indicator": "Point",
                    "distance": "",
                    "direction": ""
                }

        elif polygon.intersects(search_area):
            if dn > best_dn:
                best_dn = dn
                nearest = nearest_points(point, polygon)[1]

                best = {
                    "label": label,
                    "indicator": "Radius",
                    "distance": round(point.distance(nearest) * 69),
                    "direction": calculate_direction(lat, lon, nearest.y, nearest.x)
                }

    return best


# ==================================================
# DAY PROCESSOR
# ==================================================

def process_day(lat, lon, radius):

    base = {
        "category": "",
        "tornado": "",
        "hail": "",
        "wind": "",
        "any": "",
        "indicator": "None",
        "distance": "",
        "direction": ""
    }

    # -------------------------
    # DAY 1 / 2
    # -------------------------
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

        cat = analyze_risk(lat, lon, fetch_geojson(urls["Category"]), radius)
        base["category"] = cat["label"]

        if base["category"] == "None":
            base["tornado"] = "None"
            base["hail"] = "None"
            base["wind"] = "None"
            base["indicator"] = "None"
            return base

        base["tornado"] = analyze_risk(lat, lon, fetch_geojson(urls["Tornado"]), radius)["label"]
        base["hail"] = analyze_risk(lat, lon, fetch_geojson(urls["Hail"]), radius)["label"]
        base["wind"] = analyze_risk(lat, lon, fetch_geojson(urls["Wind"]), radius)["label"]

        base["indicator"] = cat["indicator"]
        base["distance"] = cat["distance"]
        base["direction"] = cat["direction"]

        return base


    # -------------------------
    # DAY 3
    # -------------------------
    if DAY == "3":

        cat = analyze_risk(lat, lon, fetch_geojson(
            "https://www.spc.noaa.gov/products/outlook/day3otlk_cat.nolyr.geojson"
        ), radius)

        any_r = analyze_risk(lat, lon, fetch_geojson(
            "https://www.spc.noaa.gov/products/outlook/day3otlk_prob.nolyr.geojson"
        ), radius)

        base["category"] = cat["label"]
        base["any"] = any_r["label"]

        if cat["indicator"] == "Point" or any_r["indicator"] == "Point":
            base["indicator"] = "Point"
        elif cat["indicator"] == "Radius":
            base["indicator"] = "Radius"
            base["distance"] = cat["distance"]
            base["direction"] = cat["direction"]

        return base


    # -------------------------
    # DAY 4–8
    # -------------------------
    url = f"https://www.spc.noaa.gov/products/exper/day4-8/day{DAY}prob.nolyr.geojson"
    r = analyze_risk(lat, lon, fetch_geojson(url), radius)

    base["any"] = r["label"]
    base["indicator"] = r["indicator"]
    base["distance"] = r["distance"]
    base["direction"] = r["direction"]

    return base


# ==================================================
# MAIN (STRICT SINGLE DAY OUTPUT)
# ==================================================

def main():

    sheet = get_sheet()

    timestamp = datetime.now(
        ZoneInfo("America/New_York")
    ).strftime("%m/%d/%Y %H:%M")

    for loc in locations:

        name = loc["name"]
        wfo = loc["wfo"]
        region = loc.get("region", "")

        lat = float(loc["lat"])
        lon = float(loc["lon"])
        radius = float(loc["radius"])

        r = process_day(lat, lon, radius)

        # ==================================================
        # SINGLE DAY SLOT ONLY (NO CROSS CONTAMINATION)
        # ==================================================

        day = {str(i): "" for i in range(1, 9)}

        tornado = hail = wind = ""

        if DAY == "1":
            day["1"] = r["category"]
            tornado, hail, wind = r["tornado"], r["hail"], r["wind"]

        elif DAY == "2":
            day["2"] = r["category"]
            tornado, hail, wind = r["tornado"], r["hail"], r["wind"]

        elif DAY == "3":
            day["3"] = r["any"]

        elif DAY == "4":
            day["4"] = r["any"]

        elif DAY == "5":
            day["5"] = r["any"]

        elif DAY == "6":
            day["6"] = r["any"]

        elif DAY == "7":
            day["7"] = r["any"]

        elif DAY == "8":
            day["8"] = r["any"]

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

            day["1"],
            tornado if DAY == "1" else "",
            hail if DAY == "1" else "",
            wind if DAY == "1" else "",

            day["2"],
            tornado if DAY == "2" else "",
            hail if DAY == "2" else "",
            wind if DAY == "2" else "",

            day["3"],
            r.get("any", ""),

            day["4"],
            day["5"],
            day["6"],
            day["7"],
            day["8"]
        ]

        sheet.insert_row(row, 2)

        print(f"Inserted {name}")

    print("Run complete.")


if __name__ == "__main__":
    main()
