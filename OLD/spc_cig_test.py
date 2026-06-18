#!/usr/bin/env python3

import sys
import json
import math
import requests
import gspread
import os
import time  # <-- NEW: Needed for generating our Batch Timestamp ID

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
ISSUE = str(context.get("issue", ""))

# --------------------------------------------------
# GENERATE UNIQUE BATCH ID FOR THIS ENTIRE RUN
# --------------------------------------------------
BATCH_ID = f"BATCH_{int(time.time() * 1000)}"
# --------------------------------------------------


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
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"⚠️ Fetch error for {url}: {e}")
        return {"type": "FeatureCollection", "features": []}


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

    # Scrape the VALID attribute specifically from the live dataset features
    if "cat" in SPC and "features" in SPC["cat"] and SPC["cat"]["features"]:
        for feature in SPC["cat"]["features"]:
            possible_val = feature.get("properties", {}).get("VALID")
            if possible_val:
                VALID_TIME = str(possible_val)
                break


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
            base.update(cat)
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
            base.update(cat)
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

    # Safe parsing of ISSUE details for rule processing
    ref_date = ISSUE[:8] if len(ISSUE) >= 8 else datetime.now(ZoneInfo("UTC")).strftime("%Y%m%d")
    year = ref_date[:4]

    # Parse Issue Hour (HHMM) out of payload string
    issue_hour = int(ISSUE[8:12]) if len(ISSUE) >= 12 else 0

    for loc in locations:
        for d in days_to_run:
            r = process_day(
                d,
                float(loc["lat"]),
                float(loc["lon"]),
                float(loc["radius"])
            )

            # Build standard base row structure
            # Columns A - AN (Indices 0 - 39)
            row = [
                timestamp,
                loc["name"],
                loc["wfo"],
                OUTLOOK_TYPE,
                OUTLOOK_SOURCE,
                d,
                ISSUE,
                "", "", "", "",  # H, I, J, K will hold formulas
                loc.get("region", ""),
                "",              # M will hold formula
                "",              # N will hold formula
                "NEW",           # Column O (Index 14)
                r["indicator"],  # Column P
                r["distance"],   # Column Q
                r["direction"],  # Column R

                # DAY 1 (Columns S - V)
                r["category"] if d == "1" else "",
                r["tornado"] if d == "1" else "",
                r["hail"] if d == "1" else "",
                r["wind"] if d == "1" else "",

                # DAY 2 (Columns W - Z)
                r["category"] if d == "2" else "",
                r["tornado"] if d == "2" else "",
                r["hail"] if d == "2" else "",
                r["wind"] if d == "2" else "",

                # DAY 3 (Columns AA - AB)
                r["category"] if d == "3" else "",
                r["any"] if d == "3" else "",

                # DAY 4-8 (Columns AC - AG)
                r["any"] if d == "4" else "",
                r["any"] if d == "5" else "",
                r["any"] if d == "6" else "",
                r["any"] if d == "7" else "",
                r["any"] if d == "8" else "",
                
                # Columns AH - AN (Indices 33 - 39)
                "", "", "", "", "", "", "" 
            ]

            # --------------------------------------------------
            # ADJUSTMENT: Append the Batch ID to Column AO (Index 40)
            # --------------------------------------------------
            row.append(BATCH_ID)
            # --------------------------------------------------

            # 1. Insert base fields into Row 2
            sheet.insert_row(row, 2, value_input_option="USER_ENTERED")
            
            # 2. Construct Custom Archive Links
            archive_url = ""
            
            if d == "1":
                if VALID_TIME and len(VALID_TIME) >= 12:
                    formatted_time = f"{VALID_TIME[:8]}_{VALID_TIME[8:]}"
                    archive_url = f"https://www.spc.noaa.gov/products/outlook/archive/{VALID_TIME[:4]}/day1otlk_{formatted_time}.html"
                elif VALID_TIME and len(VALID_TIME) >= 4:
                    archive_url = f"https://www.spc.noaa.gov/products/outlook/archive/{VALID_TIME[:4]}/day1otlk_{VALID_TIME}.html"
            
            elif d == "2":
                run_hour = "0600" if issue_hour < 1200 else "1730"
                archive_url = f"https://www.spc.noaa.gov/products/outlook/archive/{year}/day2otlk_{ref_date}_{run_hour}.html"
            
            elif d == "3":
                run_hour = "0730" if issue_hour < 1200 else "1930"
                archive_url = f"https://www.spc.noaa.gov/products/outlook/archive/{year}/day3otlk_{ref_date}_{run_hour}.html"
            
            elif d in ["4", "5", "6", "7", "8"]:
                archive_url = f"https://www.spc.noaa.gov/products/exper/day4-8/archive/{year}/day4-8_{ref_date}.html"

            # 3. Target Injections into AL2 and AM2
            if VALID_TIME:
                sheet.update_acell("AL2", VALID_TIME)
            if archive_url:
                sheet.update_acell("AM2", archive_url)

            print(f"Inserted {loc['name']} Day {d} | AL2: {VALID_TIME} | AM2: {archive_url} | Batch ID: {BATCH_ID}")

    print("Done.")


# ==================================================
# RUN & WEBHOOK TRIGGER
# ==================================================

if __name__ == "__main__":

    main()

    # --------------------------------------
    # WEBHOOK (UPDATED TO PASS BATCH PARAMETER)
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
            # --------------------------------------------------
            # ADJUSTMENT: Adding targetBatchId parameter to GET request
            # --------------------------------------------------
            request_params = {
                "key": api_key,
                "targetBatchId": BATCH_ID
            }
            
            response = requests.get(
                script_url,
                params=request_params,
                timeout=180
            )
            # --------------------------------------------------

            if response.status_code == 200:
                print(f"📡 Webhook triggered successfully for batch: {BATCH_ID}")
            else:
                print(f"⚠️ Webhook failed: {response.status_code}")

        except Exception as e:
            print(f"🚨 Webhook error: {e}")
