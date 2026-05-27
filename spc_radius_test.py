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

DAY_INPUT = str(context.get("day", ""))
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

    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
            "S","SSW","SW","WSW","W","WNW","NW","NNW"]

    return dirs[round(bearing / 22.5) % 16]


# ==================================================
# ANALYSIS
# ==================================================

def analyze(lat, lon, geojson, radius):

    p = Point(lon, lat)
    search = p.buffer(radius / 69.0)

    best = {"label":"None","indicator":"None","distance":"","direction":""}
    best_dn = -1

    for f in geojson.get("features", []):

        geom = f.get("geometry")
        if not geom or geom.get("type") == "GeometryCollection":
            continue

        label = f.get("properties", {}).get("LABEL")
        if label == "TSTM":
            continue

        poly = shape(geom)
        dn = f.get("properties", {}).get("DN", 0)

        if poly.contains(p):
            if dn > best_dn:
                best_dn = dn
                best = {"label":label,"indicator":"Point","distance":"","direction":""}

        elif poly.intersects(search):
            if dn > best_dn:
                best_dn = dn
                near = nearest_points(p, poly)[1]

                best = {
                    "label": label,
                    "indicator": "Radius",
                    "distance": round(p.distance(near) * 69),
                    "direction": direction(lat, lon, near.y, near.x)
                }

    return best


# ==================================================
# SPC CACHE
# ==================================================

SPC_BY_DAY = {}

def load_spc_1_3(day):
    if day == "1":
        SPC_BY_DAY["cat"] = fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_cat.nolyr.geojson")
        SPC_BY_DAY["torn"] = fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_torn.nolyr.geojson")
        SPC_BY_DAY["hail"] = fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_hail.nolyr.geojson")
        SPC_BY_DAY["wind"] = fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_wind.nolyr.geojson")

    elif day == "2":
        SPC_BY_DAY["cat"] = fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_cat.nolyr.geojson")
        SPC_BY_DAY["torn"] = fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_torn.nolyr.geojson")
        SPC_BY_DAY["hail"] = fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_hail.nolyr.geojson")
        SPC_BY_DAY["wind"] = fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_wind.nolyr.geojson")

    elif day == "3":
        SPC_BY_DAY["cat"] = fetch("https://www.spc.noaa.gov/products/outlook/day3otlk_cat.nolyr.geojson")
        SPC_BY_DAY["prob"] = fetch("https://www.spc.noaa.gov/products/outlook/day3otlk_prob.nolyr.geojson")


def load_spc_4_8():
    for d in range(4, 9):
        SPC_BY_DAY[str(d)] = fetch(
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

    if day == "1":

        cat = analyze(lat, lon, SPC_BY_DAY["cat"], radius)

        base["category"] = RISK_MAP.get(cat["label"], "None")
        if base["category"] == "None":
            return base

        base["tornado"] = to_percent(analyze(lat, lon, SPC_BY_DAY["torn"], radius)["label"])
        base["hail"] = to_percent(analyze(lat, lon, SPC_BY_DAY["hail"], radius)["label"])
        base["wind"] = to_percent(analyze(lat, lon, SPC_BY_DAY["wind"], radius)["label"])

        base.update(cat)
        return base

    if day == "2":

        cat = analyze(lat, lon, SPC_BY_DAY["cat"], radius)

        base["category"] = RISK_MAP.get(cat["label"], "None")
        if base["category"] == "None":
            return base

        base["tornado"] = to_percent(analyze(lat, lon, SPC_BY_DAY["torn"], radius)["label"])
        base["hail"] = to_percent(analyze(lat, lon, SPC_BY_DAY["hail"], radius)["label"])
        base["wind"] = to_percent(analyze(lat, lon, SPC_BY_DAY["wind"], radius)["label"])

        base.update(cat)
        return base

    if day == "3":

        cat = analyze(lat, lon, SPC_BY_DAY["cat"], radius)
        any_r = analyze(lat, lon, SPC_BY_DAY["prob"], radius)

        base["category"] = RISK_MAP.get(cat["label"], "None")
        if base["category"] == "None":
            return base

        base["any"] = to_percent(any_r["label"])
        base.update(cat)
        return base

    # 4–8
    r = analyze(lat, lon, SPC_BY_DAY[day], radius)
    base["any"] = to_percent(r["label"])
    base.update(r)
    return base


# ==================================================
# MAIN
# ==================================================

def main():

    sheet = gspread.authorize(
        Credentials.from_service_account_file(
            "credentials.json",
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
    ).open_by_key(
        "1HSLnDqg243qkgVJb7tpsnKLEDiaLFM0cCLwU5LQndsg"
    ).worksheet("Log")

    timestamp = datetime.now(
        ZoneInfo("America/New_York")
    ).strftime("%m/%d/%Y %H:%M")

    # ---------------------------
    # MODE SWITCH
    # ---------------------------

    if DAY_INPUT in ["4", "5", "6", "7", "8"]:

        load_spc_4_8()

        for d in range(4, 9):
            for loc in locations:

                r = process_day(str(d),
                    float(loc["lat"]),
                    float(loc["lon"]),
                    float(loc["radius"])
                )

                row = build_row(timestamp, loc, r, d)

                sheet.insert_row(row, 2, value_input_option="USER_ENTERED")
                print(f"Inserted {loc['name']} Day {d}")

    else:

        load_spc_1_3(DAY_INPUT)

        for loc in locations:

            r = process_day(
                DAY_INPUT,
                float(loc["lat"]),
                float(loc["lon"]),
                float(loc["radius"])
            )

            row = build_row(timestamp, loc, r, DAY_INPUT)

            sheet.insert_row(row, 2, value_input_option="USER_ENTERED")
            print(f"Inserted {loc['name']}")

    print("Done.")


# ==================================================
# ROW BUILDER
# ==================================================

def build_row(timestamp, loc, r, day):

    return [
        timestamp,
        loc["name"],
        loc["wfo"],
        OUTLOOK_TYPE,
        OUTLOOK_SOURCE,
        day,
        ISSUE,
        "", "", "", "",
        loc.get("region",""),
        "", "",
        "NEW",
        r["indicator"],
        r["distance"],
        r["direction"],
        r["category"] if day == "1" else "",
        r["tornado"] if day == "1" else "",
        r["hail"] if day == "1" else "",
        r["wind"] if day == "1" else "",
        r["category"] if day == "2" else "",
        r["tornado"] if day == "2" else "",
        r["hail"] if day == "2" else "",
        r["wind"] if day == "2" else "",
        r["category"] if day == "3" else "",
        r["any"] if day == "3" else "",
        r["any"] if day == "4" else "",
        r["any"] if day == "5" else "",
        r["any"] if day == "6" else "",
        r["any"] if day == "7" else "",
        r["any"] if day == "8" else "",
    ]


# ==================================================
# WEBHOOK
# ==================================================

if __name__ == "__main__":

    main()

    script_id = os.environ.get("GOOGLE_SHEETS_WEBHOOK_API_URL_ID")
    api_key = os.environ.get("GOOGLE_SHEETS_WEBHOOK_API_KEY")

    script_url = (
        f"https://script.google.com/macros/s/{script_id}/exec"
        if script_id else None
    )

    if script_url and api_key:

        try:
            r = requests.get(script_url, params={"key": api_key}, timeout=30)

            if r.status_code == 200:
                print("📡 Webhook triggered successfully.")
            else:
                print(f"⚠️ Webhook failed: {r.status_code}")

        except Exception as e:
            print(f"🚨 Webhook error: {e}")