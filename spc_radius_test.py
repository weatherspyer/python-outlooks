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
# PROCESS SINGLE DAY
# ==================================================

def process_day(lat, lon, radius, day):

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

    # ---------------- DAY 1 ----------------
    if day == "1":

        cat = analyze(lat, lon, fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_cat.nolyr.geojson"), radius)

        base["category"] = RISK_MAP.get(cat["label"], "None")
        if base["category"] == "None":
            return base

        base["tornado"] = to_percent(analyze(lat, lon, fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_torn.nolyr.geojson"), radius)["label"])
        base["hail"] = to_percent(analyze(lat, lon, fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_hail.nolyr.geojson"), radius)["label"])
        base["wind"] = to_percent(analyze(lat, lon, fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_wind.nolyr.geojson"), radius)["label"])

        base.update(cat)
        return base


    # ---------------- DAY 2 ----------------
    if day == "2":

        cat = analyze(lat, lon, fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_cat.nolyr.geojson"), radius)

        base["category"] = RISK_MAP.get(cat["label"], "None")
        if base["category"] == "None":
            return base

        base["tornado"] = to_percent(analyze(lat, lon, fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_torn.nolyr.geojson"), radius)["label"])
        base["hail"] = to_percent(analyze(lat, lon, fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_hail.nolyr.geojson"), radius)["label"])
        base["wind"] = to_percent(analyze(lat, lon, fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_wind.nolyr.geojson"), radius)["label"])

        base.update(cat)
        return base


    # ---------------- DAY 3 ----------------
    if day == "3":

        cat = analyze(lat, lon, fetch("https://www.spc.noaa.gov/products/outlook/day3otlk_cat.nolyr.geojson"), radius)
        any_r = analyze(lat, lon, fetch("https://www.spc.noaa.gov/products/outlook/day3otlk_prob.nolyr.geojson"), radius)

        base["category"] = RISK_MAP.get(cat["label"], "None")
        if base["category"] == "None":
            return base

        base["any"] = to_percent(any_r["label"])
        base.update(cat)
        return base


    # ---------------- DAY 4–8 (single day mode fallback) ----------------
    url = f"https://www.spc.noaa.gov/products/exper/day4-8/day{day}prob.nolyr.geojson"
    geo = fetch(url)

    r = analyze(lat, lon, geo, radius)

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

    # ==================================================
    # DAY 4 SPECIAL MODE (EXPANDS INTO 4–8)
    # ==================================================

    if DAY == "4":

        for d in ["4", "5", "6", "7", "8"]:

            for loc in locations:

                r = process_day(
                    float(loc["lat"]),
                    float(loc["lon"]),
                    float(loc["radius"]),
                    d
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
                    loc.get("region",""),
                    "", "",

                    "NEW",

                    r["indicator"],
                    r["distance"],
                    r["direction"],

                    r["category"] if d == "1" else "",
                    r["tornado"] if d == "1" else "",
                    r["hail"] if d == "1" else "",
                    r["wind"] if d == "1" else "",

                    r["category"] if d == "2" else "",
                    r["tornado"] if d == "2" else "",
                    r["hail"] if d == "2" else "",
                    r["wind"] if d == "2" else "",

                    r["category"] if d == "3" else "",
                    r["any"] if d == "3" else "",

                    r["any"] if d == "4" else "",
                    r["any"] if d == "5" else "",
                    r["any"] if d == "6" else "",
                    r["any"] if d == "7" else "",
                    r["any"] if d == "8" else "",
                ]

                sheet.insert_row(row, 2, value_input_option="USER_ENTERED")

                print(f"Inserted {loc['name']} Day {d}")

        print("Done.")
        return


    # ==================================================
    # NORMAL MODE (1–3)
    # ==================================================

    for loc in locations:

        r = process_day(
            float(loc["lat"]),
            float(loc["lon"]),
            float(loc["radius"]),
            DAY
        )

        row = [
            timestamp,
            loc["name"],
            loc["wfo"],
            OUTLOOK_TYPE,
            OUTLOOK_SOURCE,
            DAY,
            ISSUE,

            "", "", "", "",
            loc.get("region",""),
            "", "",

            "NEW",

            r["indicator"],
            r["distance"],
            r["direction"],

            r["category"] if DAY == "1" else "",
            r["tornado"] if DAY == "1" else "",
            r["hail"] if DAY == "1" else "",
            r["wind"] if DAY == "1" else "",

            r["category"] if DAY == "2" else "",
            r["tornado"] if DAY == "2" else "",
            r["hail"] if DAY == "2" else "",
            r["wind"] if DAY == "2" else "",

            r["category"] if DAY == "3" else "",
            r["any"] if DAY == "3" else "",

            r["any"] if DAY == "4" else "",
            r["any"] if DAY == "5" else "",
            r["any"] if DAY == "6" else "",
            r["any"] if DAY == "7" else "",
            r["any"] if DAY == "8" else "",
        ]

        sheet.insert_row(row, 2, value_input_option="USER_ENTERED")

        print(f"Inserted {loc['name']}")

    print("Done.")


# ==================================================
# RUN + WEBHOOK
# ==================================================

if __name__ == "__main__":
    main()

    script_id = os.environ.get("GOOGLE_SHEETS_WEBHOOK_API_URL_ID")
    api_key = os.environ.get("GOOGLE_SHEETS_WEBHOOK_API_KEY")

    script_url = (
        f"https://script.google.com/macros/s/{script_id}/exec"
        if script_id else None
    )

    if not script_url:
        print("⚠️ Missing GOOGLE_SHEETS_WEBHOOK_API_URL_ID")

    elif not api_key:
        print("⚠️ Missing GOOGLE_SHEETS_WEBHOOK_API_KEY")

    else:
        try:
            response = requests.get(
                script_url,
                params={"key": api_key},
                timeout=30
            )

            if response.status_code == 200:
                print("📡 Webhook triggered successfully.")
            else:
                print(f"⚠️ Webhook failed: {response.status_code}")

        except Exception as e:
            print(f"🚨 Webhook error: {e}")