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

# Global tracker for the valid time property
VALID_TIME = ""


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


def to_hazard(prob, cig):
    if prob == "None":
        return "None"
    if cig and cig != "None":
        formatted_cig = cig.replace("CIG", "CIG ").strip()
        return f"{prob} ({formatted_cig})"
    return prob


# ==================================================
# ANALYZE (FIXED GEOMETRY LOGIC)
# ==================================================

def analyze(lat, lon, geojson, radius, point_only=False):
    p = Point(lon, lat)
    
    best_point = None
    best_point_dn = -1

    best_radius = None
    best_radius_dn = -1

    for f in geojson.get("features", []):
        geom = f.get("geometry")
        if not geom or geom.get("type") == "GeometryCollection":
            continue

        props = f.get("properties", {})
        label = props.get("LABEL")

        if label == "TSTM":
            continue

        poly = shape(geom)
        dn = props.get("DN", 0)

        # Pass 1: True containment check
        if poly.contains(p):
            if dn > best_point_dn:
                best_point_dn = dn
                best_point = {
                    "label": label,
                    "indicator": "Point",
                    "distance": "",
                    "direction": ""
                }
        
        # Pass 2: Radius check (only run if point_only is False)
        elif not point_only:
            search = p.buffer(radius / 69.0)
            if poly.intersects(search):
                if dn > best_radius_dn:
                    best_radius_dn = dn
                    near = nearest_points(p, poly)[1]
                    best_radius = {
                        "label": label,
                        "indicator": "Radius",
                        "distance": round(p.distance(near) * 69),
                        "direction": direction(lat, lon, near.y, near.x)
                    }

    # Absolute Priority: A Point containment match always wins over a Radius match
    if best_point is not None:
        return best_point
        
    if best_radius is not None:
        return best_radius

    return {
        "label": "None",
        "indicator": "None",
        "distance": "",
        "direction": ""
    }


# ==================================================
# LOAD SPC
# ==================================================

SPC = {}


def load_standard_day():
    global SPC, VALID_TIME

    if DAY == "1":
        SPC["cat"] = fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_cat.nolyr.geojson")
        SPC["torn"] = fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_torn.nolyr.geojson")
        SPC["hail"] = fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_hail.nolyr.geojson")
        SPC["wind"] = fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_wind.nolyr.geojson")
        
        # Adding CIG Layers
        SPC["torn_sig"] = fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_cigtorn.nolyr.geojson")
        SPC["hail_sig"] = fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_cighail.nolyr.geojson")
        SPC["wind_sig"] = fetch("https://www.spc.noaa.gov/products/outlook/day1otlk_cigwind.nolyr.geojson")

    elif DAY == "2":
        SPC["cat"] = fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_cat.nolyr.geojson")
        SPC["torn"] = fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_torn.nolyr.geojson")
        SPC["hail"] = fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_hail.nolyr.geojson")
        SPC["wind"] = fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_wind.nolyr.geojson")
        
        # Adding CIG Layers
        SPC["torn_sig"] = fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_cigtorn.nolyr.geojson")
        SPC["hail_sig"] = fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_cighail.nolyr.geojson")
        SPC["wind_sig"] = fetch("https://www.spc.noaa.gov/products/outlook/day2otlk_cigwind.nolyr.geojson")

    elif DAY == "3":
        SPC["cat"] = fetch("https://www.spc.noaa.gov/products/outlook/day3otlk_cat.nolyr.geojson")
        SPC["prob"] = fetch("https://www.spc.noaa.gov/products/outlook/day3otlk_prob.nolyr.geojson")
        # Adding CIG Layer
        SPC["prob_sig"] = fetch("https://www.spc.noaa.gov/products/outlook/day3otlk_cigprob.nolyr.geojson")

    # Safely pull the VALID timestamp out of the categorical features metadata
    if SPC.get("cat", {}).get("features"):
        VALID_TIME = SPC["cat"]["features"][0].get("properties", {}).get("VALID", "")


def load_days_4_8():
    global SPC
    for d in ["4", "5", "6", "7", "8"]:
        SPC[d] = fetch(f"https://www.spc.noaa.gov/products/exper/day4-8/day{d}prob.nolyr.geojson")


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

    # DAY 1 & DAY 2
    if day in ["1", "2"]:
        cat = analyze(lat, lon, SPC["cat"], radius)
        base["category"] = RISK_MAP.get(cat["label"], "None")

        if base["category"] == "None":
            return base

        torn = analyze(lat, lon, SPC["torn"], radius)
        hail = analyze(lat, lon, SPC["hail"], radius)
        wind = analyze(lat, lon, SPC["wind"], radius)

        # Extracting CIG via Strict Containment (point_only=True)
        torn_sig = analyze(lat, lon, SPC["torn_sig"], radius, point_only=True).get("label")
        hail_sig = analyze(lat, lon, SPC["hail_sig"], radius, point_only=True).get("label")
        wind_sig = analyze(lat, lon, SPC["wind_sig"], radius, point_only=True).get("label")

        base["tornado"] = to_hazard(to_percent(torn["label"]), torn_sig)
        base["hail"] = to_hazard(to_percent(hail["label"]), hail_sig)
        base["wind"] = to_hazard(to_percent(wind["label"]), wind_sig)

        base.update(cat)
        return base

    # DAY 3
    if day == "3":
        cat = analyze(lat, lon, SPC["cat"], radius)
        any_r = analyze(lat, lon, SPC["prob"], radius)
        any_sig = analyze(lat, lon, SPC["prob_sig"], radius, point_only=True).get("label")

        base["category"] = RISK_MAP.get(cat["label"], "None")

        if base["category"] == "None":
            return base

        base["any"] = to_hazard(to_percent(any_r["label"]), any_sig)
        base.update(cat)
        return base

    # DAY 4–8
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
    if DAY in ["1", "2", "3"]:
        load_standard_day()
        days_to_run = [DAY]
    elif DAY == "4":
        load_days_4_8()
        days_to_run = ["4", "5", "6", "7", "8"]
    else:
        load_days_4_8()
        days_to_run = [DAY]

    sheet = gspread.authorize(
        Credentials.from_service_account_file(
            "credentials.json",
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
    ).open_by_key(
        "1HSLnDqg243qkgVJb7tpsnKLEDiaLFM0cCLwU5LQndsg"
    ).worksheet("Log")

    timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%m/%d/%Y %H:%M")

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
                
                # Column AL (38th element in the row array)
                VALID_TIME if d in ["1", "2", "3"] else ""
            ]

            sheet.insert_row(row, 2, value_input_option="USER_ENTERED")
            print(f"Inserted {loc['name']} Day {d}")

    print("Done.")


# ==================================================
# RUN & WEBHOOK TRIGGER
# ==================================================

if __name__ == "__main__":

    main()

    # --------------------------------------
    # WEBHOOK
    # --------------------------------------

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
