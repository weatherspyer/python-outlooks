#!/usr/bin/env python3

import sys
import json
import math
import requests
import gspread
import os

from shapely.geometry import shape, Point
from shapely.ops import nearest_points

from datetime import datetime
from zoneinfo import ZoneInfo
from google.oauth2.service_account import Credentials


# ==================================================
# INPUT
# ==================================================

payload = json.loads(sys.argv[1])

context = payload.get("context", {})
locations = payload.get("locations", [])

DAY = str(context.get("day", ""))

OUTLOOK_TYPE = context.get("outlook_type", "")
OUTLOOK_SOURCE = context.get("outlook_source", "")
ISSUE = context.get("issue", "")


# ==================================================
# RISK MAP
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
# HELPERS
# ==================================================

def to_percent(v):
    try:
        v = float(v)
        return "None" if v == 0 else f"{round(v * 100)}%"
    except:
        return "None"


def fetch(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def direction(lat1, lon1, lat2, lon2):
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
        "N","NNE","NE","ENE",
        "E","ESE","SE","SSE",
        "S","SSW","SW","WSW",
        "W","WNW","NW","NNW"
    ]

    return dirs[round(bearing / 22.5) % 16]


# ==================================================
# ANALYZE
# ==================================================

def analyze(lat, lon, geojson, radius):
    p = Point(lon, lat)
    search = p.buffer(radius / 69.0)

    # -----------------------------------
    # PASS 1
    # INSIDE POLYGON
    # -----------------------------------

    point_best = None
    point_dn = -1

    for f in geojson.get("features", []):
        geom = f.get("geometry")
        if not geom or geom.get("type") == "GeometryCollection":
            continue

        label = f.get("properties", {}).get("LABEL")

        # IGNORE GENERAL THUNDERSTORMS
        if label == "TSTM":
            continue

        poly = shape(geom)
        dn = f.get("properties", {}).get("DN", 0)

        if poly.contains(p):
            if dn > point_dn:
                point_dn = dn
                point_best = {
                    "label": label,
                    "indicator": "Point",
                    "distance": "",
                    "direction": ""
                }

    # IF INSIDE SOMETHING
    # RETURN IT IMMEDIATELY
    if point_best:
        return point_best

    # -----------------------------------
    # PASS 2
    # RADIUS SEARCH
    # -----------------------------------

    radius_best = {
        "label": "None",
        "indicator": "None",
        "distance": "",
        "direction": ""
    }

    radius_dn = -1

    for f in geojson.get("features", []):
        geom = f.get("geometry")
        if not geom or geom.get("type") == "GeometryCollection":
            continue

        label = f.get("properties", {}).get("LABEL")

        # IGNORE GENERAL THUNDERSTORMS
        if label == "TSTM":
            continue

        poly = shape(geom)
        dn = f.get("properties", {}).get("DN", 0)

        if poly.intersects(search):
            if dn > radius_dn:
                radius_dn = dn
                near = nearest_points(p, poly)[1]
                radius_best = {
                    "label": label,
                    "indicator": "Radius",
                    "distance": round(p.distance(near) * 69),
                    "direction": direction(
                        lat,
                        lon,
                        near.y,
                        near.x
                    )
                }

    return radius_best


# ==================================================
# LOAD SPC
# ==================================================

SPC = {}


def load_standard_day():
    global SPC

    if DAY == "1":
        SPC["cat"] = fetch(
            "https://www.spc.noaa.gov/products/outlook/day1otlk_cat.nolyr.geojson"
        )
        SPC["torn"] = fetch(
            "https://www.spc.noaa.gov/products/outlook/day1otlk_torn.nolyr.geojson"
        )
        SPC["hail"] = fetch(
            "https://www.spc.noaa.gov/products/outlook/day1otlk_hail.nolyr.geojson"
        )
        SPC["wind"] = fetch(
            "https://www.spc.noaa.gov/products/outlook/day1otlk_wind.nolyr.geojson"
        )

    elif DAY == "2":
        SPC["cat"] = fetch(
            "https://www.spc.noaa.gov/products/outlook/day2otlk_cat.nolyr.geojson"
        )
        SPC["torn"] = fetch(
            "https://www.spc.noaa.gov/products/outlook/day2otlk_torn.nolyr.geojson"
        )
        SPC["hail"] = fetch(
            "https://www.spc.noaa.gov/products/outlook/day2otlk_hail.nolyr.geojson"
        )
        SPC["wind"] = fetch(
            "https://www.spc.noaa.gov/products/outlook/day2otlk_wind.nolyr.geojson"
        )

    elif DAY == "3":
        SPC["cat"] = fetch(
            "https://www.spc.noaa.gov/products/outlook/day3otlk_cat.nolyr.geojson"
        )
        SPC["prob"] = fetch(
            "https://www.spc.noaa.gov/products/outlook/day3otlk_prob.nolyr.geojson"
        )


def load_days_4_8():
    global SPC

    for d in ["4", "5", "6", "7", "8"]:
        SPC[d] = fetch(
            f"https://www.spc.noaa.gov/products/exper/day4-8/day{d}prob.nolyr.geojson"
        )


# ==================================================
# PROCESS DAY
# ==================================================

def process_day(day, lat, lon, radius):
    base = {
        "category": "None",
        "tornado": "None",
        "hail": "None",
        "wind": "None",
        "any": "None",
        "indicator": "None",
        "distance": "",
        "direction": ""
    }

    # --------------------------------------
    # DAY 1
    # --------------------------------------

    if day == "1":
        cat = analyze(lat, lon, SPC["cat"], radius)
        base["category"] = RISK_MAP.get(
            cat["label"],
            "None"
        )

        if base["category"] == "None":
            return base

        base["tornado"] = to_percent(
            analyze(lat, lon, SPC["torn"], radius)["label"]
        )
        base["hail"] = to_percent(
            analyze(lat, lon, SPC["hail"], radius)["label"]
        )
        base["wind"] = to_percent(
            analyze(lat, lon, SPC["wind"], radius)["label"]
        )

        base.update(cat)
        return base

    # --------------------------------------
    # DAY 2
    # --------------------------------------

    if day == "2":
        cat = analyze(lat, lon, SPC["cat"], radius)
        base["category"] = RISK_MAP.get(
            cat["label"],
            "None"
        )

        if base["category"] == "None":
            return base

        base["tornado"] = to_percent(
            analyze(lat, lon, SPC["torn"], radius)["label"]
        )
        base["hail"] = to_percent(
            analyze(lat, lon, SPC["hail"], radius)["label"]
        )
        base["wind"] = to_percent(
            analyze(lat, lon, SPC["wind"], radius)["label"]
        )

        base.update(cat)
        return base

    # --------------------------------------
    # DAY 3
    # --------------------------------------

    if day == "3":
        cat = analyze(lat, lon, SPC["cat"], radius)
        any_r = analyze(lat, lon, SPC["prob"], radius)

        base["category"] = RISK_MAP.get(
            cat["label"],
            "None"
        )

        if base["category"] == "None":
            return base

        base["any"] = to_percent(any_r["label"])
        base.update(cat)
        return base

    # --------------------------------------
    # DAY 4-8
    # --------------------------------------

    if day in ["4", "5", "6", "7", "8"]:
        r = analyze(lat, lon, SPC[day], radius)
        base["any"] = to_percent(r["label"])
        base.update(r)
        return base

    return base


# ==================================================
# MAIN
# ==================================================

def main():
    # --------------------------------------
    # LOAD SPC FILES
    # --------------------------------------

    if DAY in ["1", "2", "3"]:
        load_standard_day()
        days_to_run = [DAY]
    elif DAY == "4":
        load_days_4_8()
        days_to_run = ["4", "5", "6", "7", "8"]
    else:
        load_days_4_8()
        days_to_run = [DAY]

    # --------------------------------------
    # GOOGLE SHEET
    # --------------------------------------

    sheet = gspread.authorize(
        Credentials.from_service_account_file(
            "credentials.json",
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets"
            ]
        )
    ).open_by_key(
        "1HSLnDqg243qkgVJb7tpsnKLEDiaLFM0cCLwU5LQndsg"
    ).worksheet("Log")

    timestamp = datetime.now(
        ZoneInfo("America/New_York")
    ).strftime("%m/%d/%Y %H:%M")

    # --------------------------------------
    # PROCESS LOCATIONS
    # --------------------------------------

    for loc in locations:
        for d in days_to_run:
            r = process_day(
                d,
                float(loc["lat"]),
                float(loc["lon"]),
                float(loc["radius"])
            )

            row = [
                timestamp,
                loc["name"],
                loc["wfo"],
                OUTLOOK_TYPE,
                OUTLOOK_SOURCE,
                d,
                ISSUE,
                "", "", "", "",
                loc.get("region", ""),
                "",
                "",
                "NEW",
                r["indicator"],
                r["distance"],
                r["direction"],

                # DAY 1
                r["category"] if d == "1" else "",
                r["tornado"] if d == "1" else "",
                r["hail"] if d == "1" else "",
                r["wind"] if d == "1" else "",

                # DAY 2
                r["category"] if d == "2" else "",
                r["tornado"] if d == "2" else "",
                r["hail"] if d == "2" else "",
                r["wind"] if d == "2" else "",

                # DAY 3
                r["category"] if d == "3" else "",
                r["any"] if d == "3" else "",

                # DAY 4-8
                r["any"] if d == "4" else "",
                r["any"] if d == "5" else "",
                r["any"] if d == "6" else "",
                r["any"] if d == "7" else "",
                r["any"] if d == "8" else "",
            ]

            sheet.insert_row(
                row,
                2,
                value_input_option="USER_ENTERED"
            )

            print(f"Inserted {loc['name']} Day {d}")

    print("Done.")


# ==================================================
# RUN
# ==================================================

if __name__ == "__main__":

    main()

    # --------------------------------------
    # WEBHOOK
    # --------------------------------------

    script_id = os.environ.get(
        "GOOGLE_SHEETS_WEBHOOK_API_URL_ID"
    )

    api_key = os.environ.get(
        "GOOGLE_SHEETS_WEBHOOK_API_KEY"
    )

    script_url = (
        f"https://script.google.com/macros/s/{script_id}/exec"
        if script_id else None
    )

    if not script_url:
        print(
            "⚠️ Missing GOOGLE_SHEETS_WEBHOOK_API_URL_ID"
        )

    elif not api_key:
        print(
            "⚠️ Missing GOOGLE_SHEETS_WEBHOOK_API_KEY"
        )

    else:
        try:
            response = requests.get(
                script_url,
                params={"key": api_key},
                timeout=30
            )

            if response.status_code == 200:
                print(
                    "📡 Webhook triggered successfully."
                )
            else:
                print(
                    "⚠️ Webhook failed: " + str(response.status_code)
                )

        except Exception as e:
            print("🚨 Webhook error: " + str(e))
