#!/usr/bin/env python3

import sys
import json
import requests
import math

from shapely.geometry import shape, Point
from shapely.ops import nearest_points

from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
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

DAY = str(context.get("day"))
OUTLOOK_TYPE = context.get("outlook_type", "")
OUTLOOK_SOURCE = context.get("outlook_source", "")
ISSUE = context.get("issue", "")


# ==================================================
# SHEET CONFIG
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
# SPC DATA
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
    y = (math.cos(lat1) * math.sin(lat2) -
         math.sin(lat1) * math.cos(lat2) * math.cos(dlon))

    bearing = (math.degrees(math.atan2(x, y)) + 360) % 360

    dirs = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW"
    ]

    return dirs[round(bearing / 22.5) % 16]


# ==================================================
# INDICATOR ENGINE (CATEGORY ONLY)
# ==================================================

def calculate_indicator_from_category(category_result, lat, lon, radius):

    label = category_result.get("label")

    if not label or label == "TSTM":
        return {"indicator": "None", "distance": "", "direction": ""}

    geom = category_result.get("geometry")
    point = Point(lon, lat)

    radius_deg = radius / 69.0
    search_area = point.buffer(radius_deg)

    polygon = shape(geom)

    # POINT
    if polygon.contains(point):
        return {"indicator": "Point", "distance": "", "direction": ""}

    # RADIUS
    if polygon.intersects(search_area):

        nearest = nearest_points(point, polygon)[1]

        dist_miles = round(point.distance(nearest) * 69)

        direction = calculate_direction(
            lat, lon,
            nearest.y,
            nearest.x
        )

        return {
            "indicator": "Radius",
            "distance": dist_miles,
            "direction": direction
        }

    return {"indicator": "None", "distance": "", "direction": ""}


# ==================================================
# DAY PROCESSOR (1 & 2)
# ==================================================

def process_day_1_or_2(day, lat, lon, radius):

    urls = DAY_URLS[day]

    category_geo = fetch_geojson(urls["Category"])

    category_feature = next(iter(category_geo["features"]))

    category_result = {
        "label": category_feature["properties"].get("LABEL"),
        "geometry": category_feature["geometry"]
    }

    indicator_data = calculate_indicator_from_category(
        category_result,
        lat,
        lon,
        radius
    )

    results = {
        "category": CATEGORY_MAP.get(category_result["label"], "None"),
        "indicator": indicator_data["indicator"],
        "distance": indicator_data["distance"],
        "direction": indicator_data["direction"]
    }

    for hazard in ["Tornado", "Hail", "Wind"]:

        geo = fetch_geojson(urls[hazard])

        for f in geo.get("features", []):
            results[hazard] = f["properties"].get("LABEL", "None")
            break

    return results


# ==================================================
# DAY 3
# ==================================================

def process_day_3(lat, lon, radius):

    urls = DAY_URLS["3"]

    cat_geo = fetch_geojson(urls["Category"])
    cat_feature = next(iter(cat_geo["features"]))

    cat_result = {
        "label": cat_feature["properties"].get("LABEL"),
        "geometry": cat_feature["geometry"]
    }

    any_geo = fetch_geojson(urls["Any"])
    any_feature = next(iter(any_geo["features"]))

    any_result = {
        "label": any_feature["properties"].get("LABEL"),
        "geometry": any_feature["geometry"]
    }

    cat_ind = calculate_indicator_from_category(cat_result, lat, lon, radius)
    any_ind = calculate_indicator_from_category(any_result, lat, lon, radius)

    if cat_ind["indicator"] == "Point" or any_ind["indicator"] == "Point":
        indicator = {"indicator": "Point", "distance": "", "direction": ""}

    elif cat_ind["indicator"] == "Radius":
        indicator = cat_ind

    elif any_ind["indicator"] == "Radius":
        indicator = any_ind

    else:
        indicator = {"indicator": "None", "distance": "", "direction": ""}

    return {
        "category": CATEGORY_MAP.get(cat_result["label"], "None"),
        "Any": any_result["label"],
        "indicator": indicator["indicator"],
        "distance": indicator["distance"],
        "direction": indicator["direction"]
    }


# ==================================================
# MAIN
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

        if DAY == "1":
            d = process_day_1_or_2("1", lat, lon, radius)
        elif DAY == "2":
            d = process_day_1_or_2("2", lat, lon, radius)
        elif DAY == "3":
            d = process_day_3(lat, lon, radius)
        else:
            d = {"category": "None", "indicator": "None", "distance": "", "direction": ""}

        row = [
            timestamp,
            name,
            wfo,
            OUTLOOK_TYPE,
            OUTLOOK_SOURCE,
            DAY,
            ISSUE,

            "",
            "",
            "",
            "",

            region,
            "",
            "",

            "NEW",  # STATUS COLUMN (NEW ADDITION)

            d.get("indicator"),
            d.get("distance"),
            d.get("direction"),

            d.get("category", ""),
            d.get("Tornado", ""),
            d.get("Hail", ""),
            d.get("Wind", "")
        ]

        sheet.insert_row(row, index=2)

        print(f"Inserted {name}")

    print("Run complete.")


if __name__ == "__main__":
    main()
