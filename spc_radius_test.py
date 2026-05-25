#!/usr/bin/env python3
import sys
import json
import requests
from shapely.geometry import shape, Point
from datetime import datetime
from zoneinfo import ZoneInfo
import gspread
from google.oauth2.service_account import Credentials

# =========================
# CONFIG
# =========================

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
ISSUE = context.get("issue", "")
OUTLOOK_SOURCE = context.get("outlook_source", "")

# =========================
# SHEETS CONFIG
# =========================

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

# =========================
# SPC URLS
# =========================

BASE_D48 = "https://www.spc.noaa.gov/products/exper/day4-8/day{}prob.nolyr.geojson"

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

# =========================
# GEO HELPERS
# =========================

def fetch(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

def check(lat, lon, geojson, radius):
    point = Point(lon, lat)
    area = point.buffer(radius / 69.0)

    best_dn = 0
    best_label = None

    for f in geojson.get("features", []):
        geom = f.get("geometry")
        if not geom or geom.get("type") == "GeometryCollection":
            continue

        poly = shape(geom)
        props = f.get("properties", {})
        dn = props.get("DN", 0)
        label = props.get("LABEL")

        if poly.intersects(area) and dn > best_dn:
            best_dn = dn
            best_label = label

    return best_label

def fmt(label):
    if not label:
        return "None"
    try:
        return f"{float(label)*100:.0f}%"
    except:
        return str(label)

# =========================
# DAY PROCESSOR
# =========================

def process_day(day, lat, lon, radius):
    urls = DAY_URLS.get(day, {})
    results = {}

    if day in ["1", "2"]:

        cat = fetch(urls["Category"])
        results["category"] = CATEGORY_MAP.get(check(lat, lon, cat, radius), "None")

        for h in ["Tornado", "Hail", "Wind"]:
            geo = fetch(urls[h])
            val = fmt(check(lat, lon, geo, radius))
            results[h] = val

    elif day == "3":

        cat = fetch(urls["Category"])
        results["category"] = CATEGORY_MAP.get(check(lat, lon, cat, radius), "None")

        geo = fetch(urls["Any"])
        results["Any"] = fmt(check(lat, lon, geo, radius))

    else:
        url = BASE_D48.format(day)
        geo = fetch(url)
        results["Any"] = fmt(check(lat, lon, geo, radius))

    return results

# =========================
# MAIN LOOP
# =========================

def main():

    sheet = get_sheet()

    now = datetime.now(ZoneInfo("America/New_York")).strftime("%m/%d/%Y %H:%M")

    for loc in locations:

        name = loc.get("name")
        wfo = loc.get("wfo")
        lat = float(loc.get("lat"))
        lon = float(loc.get("lon"))
        radius = float(loc.get("radius"))
        region = loc.get("region", "")

        d = process_day(DAY, lat, lon, radius)

        # =========================
        # FINAL ROW (STRICT ORDER)
        # =========================

        row = [
            now,                          # Date
            name,                         # Location
            wfo,                          # WFO
            OUTLOOK_TYPE,                # Outlook Type
            OUTLOOK_SOURCE,              # Outlook Source
            DAY,                         # Day #
            ISSUE,                       # Issue Time

            "", "", "", "",              # RESERVED FIELDS

            region,                      # Outlook Region
            "",                          # Title
            "",                          # Toggle
            ""                           # Indicator
        ]

        # Day blocks
        row += [
            d.get("category", ""),       # Day 1 Risk (or category)
            d.get("Tornado", ""),       # Tornado
            d.get("Hail", ""),          # Hail
            d.get("Wind", ""),          # Wind

            "", "", "", "",              # Day 2 placeholder alignment (handled later if needed)

            d.get("Any", ""),            # Day 3 Any or fallback

            "", "", "", "", "", "", "",  # Day 4–8 placeholders
        ]

        sheet.insert_row(row, 2)

        print(f"Inserted row for {name} ({wfo})")

if __name__ == "__main__":
    main()
