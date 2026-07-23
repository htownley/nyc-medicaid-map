#!/usr/bin/env python3
"""Build data/gazetteer.json — a tiny coarse-place lookup for the search box.

GeoSearch (Pelias) has no ZIP or borough layer, so a bare "11201" or "Brooklyn"
gets mangled into a house number in the wrong place. This precomputes a per-ZIP and
per-borough centroid straight from the provider dataset itself (each point carries
z, b, p), so those coarse queries can zoom the map without any external geocoder.
One-time build step — re-run after fetch_data.py refreshes the data.

Centroid is the median of provider coordinates, not the mean: the dataset has some
mislocated points, and the median ignores them where a mean (or a raw min/max
bounding box) would be dragged to the wrong place.
"""

import glob
import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    m = n // 2
    return xs[m] if n % 2 else (xs[m - 1] + xs[m]) / 2


def new_acc():
    return {"lon": [], "lat": [], "boro": {}}


def add(acc, lon, lat, boro):
    acc["lon"].append(lon)
    acc["lat"].append(lat)
    if boro:
        acc["boro"][boro] = acc["boro"].get(boro, 0) + 1


def finalize(acc, with_boro):
    e = {"c": [round(median(acc["lon"]), 5), round(median(acc["lat"]), 5)]}
    if with_boro and acc["boro"]:
        e["b"] = max(acc["boro"], key=acc["boro"].get)
    return e


zips, boros = {}, {}
for path in sorted(glob.glob(os.path.join(DATA_DIR, "cat-*.json"))):
    with open(path) as f:
        pts = json.load(f)
    for d in pts:
        lon, lat = d["p"]
        z, b = d.get("z"), d.get("b")
        if z and len(z) == 5 and z.isdigit():
            zips.setdefault(z, new_acc())
            add(zips[z], lon, lat, b)
        if b:
            boros.setdefault(b, new_acc())
            add(boros[b], lon, lat, b)

out = {
    "zips": {z: finalize(a, True) for z, a in sorted(zips.items())},
    "boroughs": {b: finalize(a, False) for b, a in sorted(boros.items())},
}
with open(os.path.join(DATA_DIR, "gazetteer.json"), "w") as f:
    json.dump(out, f, separators=(",", ":"))

print(f"gazetteer: {len(out['zips'])} ZIPs, {len(out['boroughs'])} boroughs "
      f"-> data/gazetteer.json")
