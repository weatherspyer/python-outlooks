#!/usr/bin/env python3
import requests
from shapely.geometry import shape, Point
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

# ----- SHEETS -----

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_sheet():
    creds = Credentials.from_service_account_file(
        "credentials.json",
        scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SHEET_ID)
    return spreadsheet.worksheet(SHEET_NAME)

# ----- DATA -----

def get_geojson(url):
    r = requests.get(url)
    r.raise_for_status()
    return r.json()

# ----- CORE LOGIC -----

def check_point_in_category(lat, lon, geojson):
    point = Point(lon, lat)

    best_dn = 0
    best_label = None

    for feature in geojson.get("features", []):
        geom = feature.get("geometry")
        if not geom or geom.get("type") == "GeometryCollection":
            continue

        polygon = shape(geom)
        props = feature.get("properties", {})

        dn = props.get("DN", 0)
        label = props.get("LABEL")

        if polygon.contains(point) and dn > best_dn:
            best_dn = dn
            best_label = label

    return best_label

def check_radius_in_category(lat, lon, geojson, radius_miles):
    point = Point(lon, lat)
    radius_deg = radius_miles / 69.0
    area = point.buffer(radius_deg)

    best_dn = 0
    best_label = None

    for feature in geojson.get("features", []):
        geom = feature.get("geometry")
        if not geom or geom.get("type") == "GeometryCollection":
            continue

        polygon = shape(geom)
        props = feature.get("properties", {})

        dn = props.get("DN", 0)
        label = props.get("LABEL")

        if polygon.intersects(area) and dn > best_dn:
            best_dn = dn
            best_label = label

    return best_label

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

    cat = get_geojson(URLS["Category"])
    torn = get_geojson(URLS["Tornado"])
    torn_sig = get_geojson(URLS["Tornado Sig"])
    wind = get_geojson(URLS["Wind"])
    wind_sig = get_geojson(URLS["Wind Sig"])
    hail = get_geojson(URLS["Hail"])
    hail_sig = get_geojson(URLS["Hail Sig"])

    # ----- CATEGORY -----
    point_cat = check_point_in_category(LAT, LON, cat)
    if point_cat:
        cat_raw = point_cat
    else:
        cat_raw = check_radius_in_category(LAT, LON, cat, RADIUS_MILES)

    category = CATEGORY_MAP.get(cat_raw, "None")

    # ----- TORNADO -----
    point_torn = check_point_in_category(LAT, LON, torn)
    tornado_raw = point_torn if point_torn else check_radius_in_category(LAT, LON, torn, RADIUS_MILES)
    tornado = format_label(tornado_raw)

    point_torn_sig = check_point_in_category(LAT, LON, torn_sig)
    tornado_sig = point_torn_sig if point_torn_sig else check_radius_in_category(LAT, LON, torn_sig, RADIUS_MILES)
    tornado_sig = format_sig(tornado_sig)

    # ----- WIND -----
    point_wind = check_point_in_category(LAT, LON, wind)
    wind_raw = point_wind if point_wind else check_radius_in_category(LAT, LON, wind, RADIUS_MILES)
    wind_val = format_label(wind_raw)

    point_wind_sig = check_point_in_category(LAT, LON, wind_sig)
    wind_sig_val = point_wind_sig if point_wind_sig else check_radius_in_category(LAT, LON, wind_sig, RADIUS_MILES)
    wind_sig_val = format_sig(wind_sig_val)

    # ----- HAIL -----
    point_hail = check_point_in_category(LAT, LON, hail)
    hail_raw = point_hail if point_hail else check_radius_in_category(LAT, LON, hail, RADIUS_MILES)
    hail_val = format_label(hail_raw)

    point_hail_sig = check_point_in_category(LAT, LON, hail_sig)
    hail_sig_val = point_hail_sig if point_hail_sig else check_radius_in_category(LAT, LON, hail_sig, RADIUS_MILES)
    hail_sig_val = format_sig(hail_sig_val)

    # ----- WRITE TO SHEET -----
    sheet.update_acell("F2", category)
    sheet.update_acell("F3", tornado)
    sheet.update_acell("F4", f"Sig {tornado_sig}" if tornado_sig else "")
    sheet.update_acell("F5", wind_val)
    sheet.update_acell("F6", f"Sig {wind_sig_val}" if wind_sig_val else "")
    sheet.update_acell("F7", hail_val)
    sheet.update_acell("F8", f"Sig {hail_sig_val}" if hail_sig_val else "")

    print("Day 1 SPC update complete")

if __name__ == "__main__":
    main()
