#!/usr/bin/env python3
import requests
from shapely.geometry import shape, Point
from datetime import datetime
from zoneinfo import ZoneInfo
import gspread
from google.oauth2.service_account import Credentials

# ----- CONFIG -----

LAT = 35.37794647403697
LON = -77.0686649771159
#LAT = 40.55025767645438    #home
#LON = -79.980155567313  #home
#LAT = 40.20650530322366
#LON = -94.15823157167513
# GLENSHAW 40.55025767645438, -79.980155567313

SHEET_ID = "1awHnPKObHtsnsWS2zLSB3vBBMIeODZeu1Ncx7hUsOg8"
SHEET_NAME = "SPC"

URLS = {
    "Day 1": {
        "Category": "https://www.spc.noaa.gov/products/outlook/day1otlk_cat.nolyr.geojson",
        "Tornado": "https://www.spc.noaa.gov/products/outlook/day1otlk_torn.nolyr.geojson",
        "Tornado Sig": "https://www.spc.noaa.gov/products/outlook/day1otlk_cigtorn.nolyr.geojson",
        "Hail": "https://www.spc.noaa.gov/products/outlook/day1otlk_hail.nolyr.geojson",
        "Hail Sig": "https://www.spc.noaa.gov/products/outlook/day1otlk_cighail.nolyr.geojson",
        "Wind": "https://www.spc.noaa.gov/products/outlook/day1otlk_wind.nolyr.geojson",
        "Wind Sig": "https://www.spc.noaa.gov/products/outlook/day1otlk_cigwind.nolyr.geojson"
    },
    "Day 2": {
        "Category": "https://www.spc.noaa.gov/products/outlook/day2otlk_cat.nolyr.geojson",
        "Tornado": "https://www.spc.noaa.gov/products/outlook/day2otlk_torn.nolyr.geojson",
        "Tornado Sig": "https://www.spc.noaa.gov/products/outlook/day2otlk_cigtorn.nolyr.geojson",
        "Hail": "https://www.spc.noaa.gov/products/outlook/day2otlk_hail.nolyr.geojson",
        "Hail Sig": "https://www.spc.noaa.gov/products/outlook/day2otlk_cighail.nolyr.geojson",
        "Wind": "https://www.spc.noaa.gov/products/outlook/day2otlk_wind.nolyr.geojson",
        "Wind Sig": "https://www.spc.noaa.gov/products/outlook/day2otlk_cigwind.nolyr.geojson"
    },
    "Day 3": {
        "Category": "https://www.spc.noaa.gov/products/outlook/day3otlk_cat.nolyr.geojson",
        "Any": "https://www.spc.noaa.gov/products/outlook/day3otlk_prob.nolyr.geojson",
        "Any Sig": "https://www.spc.noaa.gov/products/outlook/day3otlk_cigprob.nolyr.geojson"
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
    sheet = spreadsheet.worksheet(SHEET_NAME)

    return sheet

# ----- FUNCTIONS -----

def get_spc_geojson(url):
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def check_risk_at_location(lat, lon, geojson):
    point = Point(lon, lat)

    highest_dn = 0
    highest_label = None
    highest_label2 = None

    for feature in geojson.get("features", []):
        geom = feature.get("geometry")

        if geom is None or geom.get("type") == "GeometryCollection":
            continue

        polygon = shape(geom)

        props = feature.get("properties", {})
        dn = props.get("DN", 0)
        label = props.get("LABEL")
        label2 = props.get("LABEL2")

        if polygon.contains(point) and dn > highest_dn:
            highest_dn = dn
            highest_label = label
            highest_label2 = label2

    return highest_label, highest_label2

def format_label(label):
    if label is None or label == "":
        return "None"

    try:
        return f"{float(label)*100:.0f}%"
    except:
        return str(label)

def format_sig(sig):
    if sig in CIG_MAP:
        return CIG_MAP[sig]

    return ""

def get_day_outlook(day, urls):

    cat_label, _ = check_risk_at_location(
        LAT, LON,
        get_spc_geojson(urls["Category"])
    )

    cat_display = CATEGORY_MAP.get(cat_label, cat_label) if cat_label else "None"

    results = {
        "category": cat_display
    }

    if day != "Day 3":

        hazards = ["Tornado", "Hail", "Wind"]

        for hazard in hazards:

            label, _ = check_risk_at_location(
                LAT, LON,
                get_spc_geojson(urls[hazard])
            )

            sig_raw, _ = check_risk_at_location(
                LAT, LON,
                get_spc_geojson(urls[hazard + " Sig"])
            )

            display_label = format_label(label)
            sig_display = format_sig(sig_raw)

            if sig_display:
                results[hazard] = f"{display_label} (Sig {sig_display})"
            else:
                results[hazard] = display_label

    else:

        label, _ = check_risk_at_location(
            LAT, LON,
            get_spc_geojson(urls["Any"])
        )

        sig_raw, _ = check_risk_at_location(
            LAT, LON,
            get_spc_geojson(urls["Any Sig"])
        )

        display_label = format_label(label)
        sig_display = format_sig(sig_raw)

        if sig_display:
            results["Any"] = f"{display_label} (Sig {sig_display})"
        else:
            results["Any"] = display_label

    return results

# ----- MAIN -----

def main():

    sheet = get_sheet()

    now_utc = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
    now_est = now_utc.astimezone(ZoneInfo("America/New_York"))

    timestamp = now_est.strftime("%m/%d/%Y %H:%M")

    d1 = get_day_outlook("Day 1", URLS["Day 1"])
    d2 = get_day_outlook("Day 2", URLS["Day 2"])
    d3 = get_day_outlook("Day 3", URLS["Day 3"])

    row = [
        timestamp,
        d1["category"], d1["Tornado"], d1["Hail"], d1["Wind"],
        d2["category"], d2["Tornado"], d2["Hail"], d2["Wind"],
        d3["category"], d3["Any"]
    ]

    sheet.append_row(row)

    print("Row added to Google Sheets")

if __name__ == "__main__":
    main()
