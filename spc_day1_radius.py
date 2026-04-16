#!/usr/bin/env python3
import requests
from shapely.geometry import shape, Point
from datetime import datetime
from zoneinfo import ZoneInfo
import gspread
from google.oauth2.service_account import Credentials
import sys

# ----- CONFIG -----

if len(sys.argv) < 4:
    raise ValueError("LAT, LON, and RADIUS (miles) must be provided as arguments")

LAT = float(sys.argv[1])
LON = float(sys.argv[2])
RADIUS_MILES = float(sys.argv[3])

SHEET_ID = "1awHnPKObHtsnsWS2zLSB3vBBMIeODZeu1Ncx7hUsOg8"
SHEET_NAME = "Day1"

URLS = {
    "Category": "https://www.spc.noaa.gov/products/outlook/day1otlk_cat.nolyr.geojson",
    "Tornado": "https://www.spc.noaa.gov/products/outlook/day1otlk_torn.nolyr.geojson",
    "Tornado Sig": "https://www.spc.noaa.gov/products/outlook/day1otlk_cigtorn.nolyr.geojson",
    "Hail": "https://www.spc.noaa.gov/products/outlook/day1otlk_hail.nolyr.geojson",
    "Hail Sig": "https://www.spc.noaa.gov/products/outlook/day1otlk_cighail.nolyr.geojson",
    "Wind": "https://www.spc.noaa.gov/products/outlook/day1otlk_wind.nolyr.geojson",
    "Wind Sig": "https://www.spc.noaa.gov/products/outlook/day1otlk_cigwind.nolyr.geojson"
}

CATEGORY_MAP = {
    "MRGL": "Marginal",
    "SLGT": "Slight",
    "ENH": "Enhanced",
    "MDT": "Moderate",
    "HIGH": "High",
    "TSTM": "None"
}

CIG_MAP = {
    "CIG1": "1",
    "CIG2": "2",
    "CIG3": "3"
}

# ----- GOOGLE SHEETS -----

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_sheet():
    creds = Credentials.from_service_account_file(
        "credentials.json",
        scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SHEET_ID)
    return spreadsheet.worksheet(SHEET_NAME)

# ----- FUNCTIONS -----

def get_spc_geojson(url):
    r = requests.get(url)
    r.raise_for_status()
    return r.json()

def check_risk_in_radius(lat, lon, geojson, radius_miles):
    point = Point(lon, lat)
    radius_deg = radius_miles / 69.0
    area = point.buffer(radius_deg)

    highest_dn = 0
    highest_label = None

    for feature in geojson.get("features", []):
        geom = feature.get("geometry")
        if not geom or geom.get("type") == "GeometryCollection":
            continue

        polygon = shape(geom)
        props = feature.get("properties", {})
        dn = props.get("DN", 0)
        label = props.get("LABEL")

        if polygon.intersects(area) and dn > highest_dn:
            highest_dn = dn
            highest_label = label

    return highest_label

def format_label(label):
    if not label:
        return "None"
    try:
        return f"{float(label)*100:.0f}%"
    except:
        return str(label)

def format_sig(sig):
    return CIG_MAP.get(sig, "")

# ----- MAIN -----

def main():
    print(f"Running SPC Day 1 for LAT={LAT}, LON={LON}, RADIUS={RADIUS_MILES}")

    sheet = get_sheet()

    cat = get_spc_geojson(URLS["Category"])
    torn = get_spc_geojson(URLS["Tornado"])
    torn_sig = get_spc_geojson(URLS["Tornado Sig"])
    wind = get_spc_geojson(URLS["Wind"])
    wind_sig = get_spc_geojson(URLS["Wind Sig"])
    hail = get_spc_geojson(URLS["Hail"])
    hail_sig = get_spc_geojson(URLS["Hail Sig"])

    category = CATEGORY_MAP.get(
        check_risk_in_radius(LAT, LON, cat, RADIUS_MILES),
        "None"
    )

    tornado = format_label(
        check_risk_in_radius(LAT, LON, torn, RADIUS_MILES)
    )
    tornado_sig = format_sig(
        check_risk_in_radius(LAT, LON, torn_sig, RADIUS_MILES)
    )

    wind_val = format_label(
        check_risk_in_radius(LAT, LON, wind, RADIUS_MILES)
    )
    wind_sig_val = format_sig(
        check_risk_in_radius(LAT, LON, wind_sig, RADIUS_MILES)
    )

    hail_val = format_label(
        check_risk_in_radius(LAT, LON, hail, RADIUS_MILES)
    )
    hail_sig_val = format_sig(
        check_risk_in_radius(LAT, LON, hail_sig, RADIUS_MILES)
    )

    # ----- WRITE TO SHEET -----

    sheet.update_acell("F2", category)
    sheet.update_acell("F3", tornado)
    sheet.update_acell("F4", f"Sig {tornado_sig}" if tornado_sig else "")
    sheet.update_acell("F5", wind_val)
    sheet.update_acell("F6", f"Sig {wind_sig_val}" if wind_sig_val else "")
    sheet.update_acell("F7", hail_val)
    sheet.update_acell("F8", f"Sig {hail_sig_val}" if hail_sig_val else "")

    print("Day 1 SPC data updated successfully")

if __name__ == "__main__":
    main()
