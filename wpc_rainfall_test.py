#!/usr/bin/env python3

import sys
import json
import requests
import gspread
import os
import time

from shapely.geometry import shape, Point

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

OUTLOOK_TYPE = context.get("outlook_type", "")      # e.g., "Excessive Rainfall"
OUTLOOK_SOURCE = context.get("outlook_source", "")  # e.g., "WPC"

# --------------------------------------------------
# GENERATE UNIQUE BATCH ID FOR THIS ENTIRE RUN
# --------------------------------------------------
BATCH_ID = f"BATCH_{int(time.time() * 1000)}"
# --------------------------------------------------


# ==================================================
# RISK MAP (WPC ERO Standards)
# ==================================================

RISK_MAP = {
    "MARGINAL": "Marginal",
    "SLIGHT": "Slight",
    "MODERATE": "Moderate",
    "HIGH": "High",
    "NONE": "None",
    "": "None"
}

# Global trackers for properties pulled from the GeoJSON
VALID_TIME = ""
GEOJSON_ISSUE_TIME = ""

# --------------------------------------------------
# FIXED ARCHIVE DASHBOARD URL FOR COLUMN AM
# --------------------------------------------------
ARCHIVE_URL = "https://www.wpc.ncep.noaa.gov/qpf/excessive_rainfall_outlook_ero.php"
# --------------------------------------------------


# ==================================================
# HELPERS
# ==================================================

def fetch(url):
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"⚠️ Fetch error for {url}: {e}")
        return {"type": "FeatureCollection", "features": []}


# ==================================================
# ANALYZE (STREAMLINED POINT-ONLY LOGIC)
# ==================================================

def analyze(lat, lon, geojson):
    p = Point(lon, lat)
    best_label = "None"
    best_dn = -1

    for f in geojson.get("features", []):
        geom = f.get("geometry")
        if not geom or geom.get("type") == "GeometryCollection":
            continue

        poly = shape(geom)

        # Direct Point containment check
        if poly.contains(p):
            props = f.get("properties", {})
            dn = props.get("dn") or props.get("DN") or 0
            
            # Keep the highest threat category polygon if overlapping
            if dn > best_dn:
                best_dn = dn
                raw_outlook = props.get("OUTLOOK") or props.get("outlook") or ""
                # Safely isolate the first word (e.g., "Marginal" from "Marginal (At Least 5%)")
                best_label = raw_outlook.strip().split(" ")[0].upper()

    if best_dn != -1:
        return {
            "label": best_label,
            "indicator": "Point"
        }

    return {
        "label": "None",
        "indicator": "None"
    }


# ==================================================
# LOAD WPC DATA
# ==================================================

def load_wpc_day():
    global VALID_TIME, GEOJSON_ISSUE_TIME

    # Dynamic endpoint URL configuration
    url = f"https://www.wpc.ncep.noaa.gov/exper/eromap/geojson/Day{DAY}_Latest.geojson"
    print(f"Fetching WPC Data from: {url}")
    geojson_data = fetch(url)

    # Scrape meta properties out of the live payload features
    if "features" in geojson_data and geojson_data["features"]:
        for feature in geojson_data["features"]:
            props = feature.get("properties", {})
            
            possible_valid = props.get("VALID_TIME") or props.get("valid_time")
            if possible_valid:
                VALID_TIME = str(possible_valid)
                
            possible_issue = props.get("ISSUE_TIME") or props.get("issue_time")
            if possible_issue:
                GEOJSON_ISSUE_TIME = str(possible_issue)
                
            # Drop out early once metadata keys are populated
            if VALID_TIME and GEOJSON_ISSUE_TIME:
                break
                
    return geojson_data


# ==================================================
# MAIN EXECUTION LINE
# ==================================================

def main():
    wpc_geojson = load_wpc_day()
    days_to_run = [DAY]

    # Dynamically build the sheet name (e.g., "Rainfall Day4 Log")
    target_sheet_name = f"Rainfall Day{DAY} Log"
    print(f"Targeting Google Sheet Worksheet: {target_sheet_name}")

    sheet = gspread.authorize(
        Credentials.from_service_account_file(
            "credentials.json",
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
    ).open_by_key(
        "1HSLnDqg243qkgVJb7tpsnKLEDiaLFM0cCLwU5LQndsg"
    ).worksheet(target_sheet_name) # <-- Changed from "Log" to the dynamic variable

    timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%m/%d/%Y %H:%M")

    # This list will hold all rows to be inserted in a single batch operation
    all_rows_to_insert = []

    for loc in locations:
        for d in days_to_run:
            r = analyze(float(loc["lat"]), float(loc["lon"]), wpc_geojson)
            category_value = RISK_MAP.get(r["label"], "None")

            # Build row grid structure matching columns A - AN
            row = [
                timestamp,
                loc["name"],
                loc["wfo"],
                OUTLOOK_TYPE,
                OUTLOOK_SOURCE,
                d,
                GEOJSON_ISSUE_TIME, # Column G (Scraped Directly from GeoJSON Properties)
                "", "", "", "",     # H, I, J, K formulas populated by Apps Script
                loc.get("region", ""),
                "",                 # M formula target
                "",                 # N formula target
                "NEW",              # Status Tracker Column O
                r["indicator"],     # Column P ("Point" or "None")
                "",                 # Column Q (Intentionally left blank for point-only runs)
                "",                 # Column R (Intentionally left blank for point-only runs)

                # DAY 1 (Columns S - V)
                category_value if d == "1" else "", "", "", "",

                # DAY 2 (Columns W - Z)
                category_value if d == "2" else "", "", "", "",

                # DAY 3 (Columns AA - AB)
                category_value if d == "3" else "", "",

                # DAYS 4-8 Tracking (Columns AC - AG)
                category_value if d == "4" else "", # Column AC (Day 4 Target)
                category_value if d == "5" else "", # Column AD (Day 5 Target)
                "",                                 # Column AE Spacer
                "",                                 # Column AF Spacer
                "",                                 # Column AG Spacer
                
                # Formula buffers tail tracking allocations (AH - AN)
                "", "", "", "", 
                VALID_TIME if VALID_TIME else "",   # Column AL (Directly inserted, index 37)
                ARCHIVE_URL,                        # Column AM (Directly inserted, index 38)
                ""                                  # Column AN
            ]

            # Append the tracking Batch execution token to Column AO (Index 40)
            row.append(BATCH_ID)
            
            all_rows_to_insert.append(row)
            print(f"Prepared row: {loc['name']} WPC Day {d} | AL: {VALID_TIME} | AM: {ARCHIVE_URL}")

    # 1. Batch insert all rows starting at Row 2 in a single API call
    if all_rows_to_insert:
        sheet.insert_rows(all_rows_to_insert, 2, value_input_option="USER_ENTERED")
        print(f"Successfully batch-inserted {len(all_rows_to_insert)} rows into '{target_sheet_name}'. Batch ID: {BATCH_ID}")
    else:
        print("No data collected to insert.")

    print("Done.")


# ==================================================
# WEBHOOK DISPATCH TRIGGER (DISABLED FOR NOW)
# ==================================================

if __name__ == "__main__":
    main()

    print("ℹ️ Webhook dispatch skipped because it is currently commented out.")

    """  # <-- Starts the comment block
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
            request_params = {
                "key": api_key,
                "targetBatchId": BATCH_ID
            }
            
            response = requests.get(
                script_url,
                params=request_params,
                timeout=180
            )

            if response.status_code == 200:
                print(f"📡 Webhook triggered successfully for batch: {BATCH_ID}")
                print(f"Server response: {response.text}")
            else:
                print(f"⚠️ Webhook failed: {response.status_code}")

        except Exception as e:
            print(f"🚨 Webhook error: {e}")
    """  # <-- Ends the comment block
