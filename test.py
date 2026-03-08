#!/usr/bin/env python3
import requests
from shapely.geometry import shape, Point
from datetime import datetime

# ----- CONFIG -----

LAT = 28.787299839629824
LON = -98.56092194574036
#LAT = 40.55025767645438    #home
#LON = -79.980155567313  #home
#LAT = 40.20650530322366
#LON = -94.15823157167513
# GLENSHAW 40.55025767645438, -79.980155567313

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

def print_day_outlook(day, urls):
    # Category
    cat_label, _ = check_risk_at_location(LAT, LON, get_spc_geojson(urls["Category"]))
    cat_display = CATEGORY_MAP.get(cat_label, cat_label) if cat_label else "None"
    print(f"⚠️ {day} SPC Outlook for your location:\n")
    print(f"Category Risk: {cat_display}")

    if day != "Day 3":
        # Day 1 & 2 hazards
        hazards = [("Tornado", "🌪️ "), ("Hail", "🪨"), ("Wind", "🌬️ ")]
        for hazard_name, emoji in hazards:
            label, _ = check_risk_at_location(LAT, LON, get_spc_geojson(urls[hazard_name]))
            sig_raw, _ = check_risk_at_location(LAT, LON, get_spc_geojson(urls[hazard_name + " Sig"]))
            display_label = format_label(label)
            sig_display = format_sig(sig_raw)
            if sig_display:
                print(f"{emoji}: {display_label} (Sig: {sig_display})")
            else:
                print(f"{emoji}: {display_label}")
    else:
        # Day 3 Any
        label, _ = check_risk_at_location(LAT, LON, get_spc_geojson(urls["Any"]))
        sig_raw, _ = check_risk_at_location(LAT, LON, get_spc_geojson(urls["Any Sig"]))
        display_label = format_label(label)
        sig_display = format_sig(sig_raw)
        if sig_display:
            print(f"⛈️ : {display_label} (Sig: {sig_display})")
        else:
            print(f"⛈️ : {display_label}")

    print("\n")

# ----- MAIN -----
def main():
    # Print current date/time in mm/dd/yyyy HH:mm 24hr format
    now = datetime.now()
    timestamp = now.strftime("%m/%d/%Y %H:%M")
    print(f"SPC Outlook Generated: {timestamp}\n")

    for day in ["Day 1", "Day 2", "Day 3"]:
        print_day_outlook(day, URLS[day])

if __name__ == "__main__":
    main()