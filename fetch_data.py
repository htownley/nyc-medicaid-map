#!/usr/bin/env python3
"""
Fetch all NYC Medicaid-enrolled providers from NY State open data, clean them,
group them into display categories, and write a baked snapshot for the map.

Source: Medicaid Enrolled Provider Listing (Socrata id: keti-qx5t)
        https://health.data.ny.gov/Health/Medicaid-Enrolled-Provider-Listing/keti-qx5t

Scope (see plan): 5 NYC counties, all professions, direct-service providers only
(medicaid_type FFS or MCO; OPRA / order-refer-only excluded), deduped to one point
per provider-per-address.

Outputs (overwritten each run):
  - data.json          compact snapshot the map loads (categories + points)
  - providers.geojson  portable GeoJSON for GIS / other tools

Refresh with:  python3 fetch_data.py
"""

import json
import sys
import urllib.parse
import urllib.request
from datetime import date

DATASET = "keti-qx5t"
BASE = f"https://health.data.ny.gov/resource/{DATASET}.json"

# county (uppercase, as stored) -> borough display name
BOROUGHS = {
    "BRONX": "Bronx",
    "KINGS": "Brooklyn",
    "NEW YORK": "Manhattan",
    "QUEENS": "Queens",
    "RICHMOND": "Staten Island",
}

MEDICAID_TYPES = ["FFS", "MCO"]  # direct-service; OPRA (order/refer only) excluded

# Display categories, in legend order. Index into this list is stored on each point.
CATEGORIES = [
    "Dental",                       # 0
    "Vision",                       # 1
    "Physicians & Primary Care",    # 2
    "Behavioral & Mental Health",   # 3
    "Therapy & Rehab",              # 4
    "Pharmacy",                     # 5
    "Hospitals & Clinics",          # 6
    "Labs & Diagnostics",           # 7
    "Long-Term & Home Care",        # 8
    "Transportation",               # 9
    "Equipment & Supplies",         # 10
    "Other Services",               # 11
]
CAT_INDEX = {name: i for i, name in enumerate(CATEGORIES)}
OTHER = CAT_INDEX["Other Services"]

# profession_or_service -> category name. Anything unmapped falls back to Other.
PROFESSION_TO_CATEGORY = {
    # Dental
    "DENTISTS": "Dental",
    "DENTAL GROUP PRACTICE": "Dental",
    # Vision
    "OPTOMETRIST": "Vision",
    "OPTICAL ESTABLISHMENT": "Vision",
    "OPTICIAN": "Vision",
    "EYE PROSTHESIS FITTER": "Vision",
    # Physicians & Primary Care
    "PHYSICIAN": "Physicians & Primary Care",
    "NURSE PRACTITIONER": "Physicians & Primary Care",
    "PHYSICIAN ASSISTANT": "Physicians & Primary Care",
    "PHYSICIAN GROUP PRACTICE": "Physicians & Primary Care",
    "MULTI TYPE GROUP PRACTICE": "Physicians & Primary Care",
    "NURSE MIDWIFE": "Physicians & Primary Care",
    "REGISTERED NURSE": "Physicians & Primary Care",
    "LICENSED PRACTICAL NURSE": "Physicians & Primary Care",
    "PODIATRIST": "Physicians & Primary Care",
    "MEDICARE COST SHARING PRACTITIONER": "Physicians & Primary Care",
    # Behavioral & Mental Health
    "CLINICAL SOCIAL WORKER": "Behavioral & Mental Health",
    "CLINICAL PSYCHOLOGIST": "Behavioral & Mental Health",
    "MENTAL HEALTH COUNSELORS": "Behavioral & Mental Health",
    "MENTAL HEALTH REHABILITATION": "Behavioral & Mental Health",
    "LICENSED BEHAVIOR ANALYST": "Behavioral & Mental Health",
    "MARRIAGE & FAMILY THERAPIST": "Behavioral & Mental Health",
    # Therapy & Rehab
    "PHYSICAL THERAPIST": "Therapy & Rehab",
    "OCCUPATIONAL THERAPIST": "Therapy & Rehab",
    "SPEECH LANGUAGE PATHOLOGIST": "Therapy & Rehab",
    "AUDIOLOGIST": "Therapy & Rehab",
    "AUDIOLOGIST/HEARING AID": "Therapy & Rehab",
    "HEARING AID": "Therapy & Rehab",
    "EARLY INTERVENTION OR SCHOOL SUPPORTIVE": "Therapy & Rehab",
    "CHIROPRACTIC SERVICES": "Therapy & Rehab",
    # Pharmacy
    "PHARMACY": "Pharmacy",
    "SUPERVISING PHARMACIST": "Pharmacy",
    "HOSPITAL PHARMACY": "Pharmacy",
    "CLINIC PHARMACY": "Pharmacy",
    "SPECIALTY PHARMACY": "Pharmacy",
    # Hospitals & Clinics
    "HOSPITAL - INPATIENT": "Hospitals & Clinics",
    "OUTPATIENT CLINIC": "Hospitals & Clinics",
    "OUTPATIENT": "Hospitals & Clinics",
    "OPWDD STATE-OPERATED CLINIC": "Hospitals & Clinics",
    # Labs & Diagnostics
    "LABORATORY HOSPITAL BASED": "Labs & Diagnostics",
    "LABORATORY CLINIC BASED": "Labs & Diagnostics",
    "LABORATORY": "Labs & Diagnostics",
    "LABORATORY DIRECTOR": "Labs & Diagnostics",
    # Long-Term & Home Care
    "NURSING HOME": "Long-Term & Home Care",
    "NURSING SERVICES": "Long-Term & Home Care",
    "HOME HEALTH CARE": "Long-Term & Home Care",
    "CERTIFIED HOME HEALTH AGENCY": "Long-Term & Home Care",
    "PERSONAL CARE SERVICES": "Long-Term & Home Care",
    "ADULT DAY HEALTH CARE": "Long-Term & Home Care",
    "ASSISTED LIVING PROGRAM": "Long-Term & Home Care",
    "LONG TERM HOME HEALTH CARE": "Long-Term & Home Care",
    "LONG TERM CARE - ORDERED AMB (NO LAB)": "Long-Term & Home Care",
    "HOSPICE PROVIDERS": "Long-Term & Home Care",
    "INTERMEDIATE CARE FACILITY (OPWDD)": "Long-Term & Home Care",
    "COMMUNITY SUPPORT (OPWDD)": "Long-Term & Home Care",
    "PERSONAL EMERGENCY RESPONSE SERVICE": "Long-Term & Home Care",
    "WAIVER SERVICES": "Long-Term & Home Care",
    "BRIDGES TO HEALTH WAIVER": "Long-Term & Home Care",
    "RESIDENTIAL TREATMENT FACILITY": "Long-Term & Home Care",
    # Transportation
    "NON-MEDICAL TRANSPORTATION": "Transportation",
    "AMBULANCE": "Transportation",
    # Equipment & Supplies
    "MEDICAL EQUIPMENT SUPPLIERS & DEALER": "Equipment & Supplies",
    "OXYGEN AND RELATED EQUIPMENT DEALER": "Equipment & Supplies",
    # Other Services
    "DIETITIANS / NUTRITIONISTS": "Other Services",
    "CERTIFIED DIABETES EDUCATOR": "Other Services",
    "CERTIFIED ASTHMA EDUCATOR": "Other Services",
    "DOULA (PERINATAL)": "Other Services",
    "CASE MANAGEMENT SERVICES": "Other Services",
    "CHILD (FOSTER) CARE AGENCIES": "Other Services",
    "COMMUNITY-BASED ORGANIZATION": "Other Services",
    "SOCIAL CARE NETWORK SERVICE": "Other Services",
    "SERVICE BUREAU": "Other Services",
    "TO BE DETERMINED": "Other Services",
}

# loose NYC bounding box to discard obviously-bad geocodes
LAT_MIN, LAT_MAX = 40.40, 41.05
LON_MIN, LON_MAX = -74.30, -73.65

SELECT = ",".join([
    "npi", "mmis_name", "profession_or_service",
    "service_address", "city", "zip_code", "county", "latitude", "longitude",
])


def quote_list(values):
    return ",".join("'" + v.replace("'", "''") + "'" for v in values)


def fetch_all():
    """Page through the Socrata API until exhausted."""
    where = (
        f"county in({quote_list(BOROUGHS)}) AND "
        f"medicaid_type in({quote_list(MEDICAID_TYPES)})"
    )
    rows, limit, offset = [], 50000, 0
    while True:
        params = urllib.parse.urlencode({
            "$select": SELECT,
            "$where": where,
            "$limit": limit,
            "$offset": offset,
            "$order": "npi",
        })
        print(f"  fetching offset={offset} ...", file=sys.stderr)
        with urllib.request.urlopen(f"{BASE}?{params}", timeout=180) as resp:
            batch = json.load(resp)
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return rows


def clean(rows):
    points, seen = [], set()
    stats = {"raw": len(rows), "bad_coords": 0, "duplicates": 0, "unmapped": set()}
    for r in rows:
        try:
            lat = float(r["latitude"])
            lon = float(r["longitude"])
        except (KeyError, TypeError, ValueError):
            stats["bad_coords"] += 1
            continue
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            stats["bad_coords"] += 1
            continue

        addr = (r.get("service_address") or "").strip()
        key = (r.get("npi", ""), addr.upper())
        if key in seen:
            stats["duplicates"] += 1
            continue
        seen.add(key)

        prof = r.get("profession_or_service", "")
        cat = PROFESSION_TO_CATEGORY.get(prof)
        if cat is None:
            stats["unmapped"].add(prof)
            cat = "Other Services"

        points.append({
            "p": [round(lon, 5), round(lat, 5)],
            "c": CAT_INDEX[cat],
            "n": r.get("mmis_name", ""),
            "pr": prof,
            "a": addr,
            "ci": r.get("city", ""),
            "z": (r.get("zip_code") or "").split("-")[0],
            "b": BOROUGHS.get(r.get("county", ""), r.get("county", "")),
            "np": r.get("npi", ""),
        })
    return points, stats


def write_outputs(points):
    snapshot = {
        "meta": {
            "source": "NY State Medicaid Enrolled Provider Listing (keti-qx5t)",
            "source_url": "https://health.data.ny.gov/Health/Medicaid-Enrolled-Provider-Listing/keti-qx5t",
            "generated": date.today().isoformat(),
            "scope": "NYC, all professions, direct-service (FFS+MCO)",
            "count": len(points),
        },
        "categories": CATEGORIES,
        "points": points,
    }
    with open("data.json", "w") as f:
        json.dump(snapshot, f, separators=(",", ":"))

    features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": pt["p"]},
        "properties": {
            "name": pt["n"], "category": CATEGORIES[pt["c"]], "profession": pt["pr"],
            "address": pt["a"], "city": pt["ci"], "zip": pt["z"],
            "borough": pt["b"], "npi": pt["np"],
        },
    } for pt in points]
    with open("providers.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "metadata": snapshot["meta"],
                   "features": features}, f, separators=(",", ":"))


def main():
    print("Fetching NYC Medicaid providers from NY State open data (keti-qx5t)...",
          file=sys.stderr)
    rows = fetch_all()
    points, stats = clean(rows)
    write_outputs(points)

    by_cat = {}
    for pt in points:
        by_cat[CATEGORIES[pt["c"]]] = by_cat.get(CATEGORIES[pt["c"]], 0) + 1

    print(f"\nraw rows:            {stats['raw']:>7}", file=sys.stderr)
    print(f"dropped (bad coords):{stats['bad_coords']:>7}", file=sys.stderr)
    print(f"dropped (duplicates):{stats['duplicates']:>7}", file=sys.stderr)
    print(f"mapped points:       {len(points):>7}", file=sys.stderr)
    print("\nby category:", file=sys.stderr)
    for name in CATEGORIES:
        print(f"  {name:<28}{by_cat.get(name, 0):>7}", file=sys.stderr)
    if stats["unmapped"]:
        print(f"\n[!] professions not in mapping (-> Other Services): "
              f"{sorted(stats['unmapped'])}", file=sys.stderr)
    print("\n-> wrote data.json, providers.geojson", file=sys.stderr)


if __name__ == "__main__":
    main()
