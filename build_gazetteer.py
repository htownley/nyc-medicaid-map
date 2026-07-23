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
import re
import urllib.request

HERE = os.path.dirname(__file__)
DATA_DIR = os.path.join(HERE, "data")

# Residential 2020 Neighborhood Tabulation Areas (DCP) — names + borough + geometry.
# https://data.cityofnewyork.us/City-Government/2020-Neighborhood-Tabulation-Areas-NTAs-/9nt8-h7nd
NTA_URL = ("https://data.cityofnewyork.us/resource/9nt8-h7nd.geojson"
           "?$where=ntatype='0'&$limit=400")
NTA_CACHE = os.path.join(HERE, "build_cache", "nta_2020.geojson")

# NTA names combine neighborhoods with hyphens ("SoHo-Little Italy-Hudson Square"),
# which we split into searchable aliases — except these, which are single neighborhoods
# that legitimately contain a hyphen and must not be split (compare normalized).
HYPHEN_KEEP = {"bedford stuyvesant", "prospect lefferts gardens"}

# A short hand-curated alias tail: colloquial names -> a normalized key the NTA data
# already produced. Applied only when the target exists (skipped with a warning if not).
NBHD_ALIASES = {
    "bed stuy": "bedford stuyvesant",
    "bedstuy": "bedford stuyvesant",
    "fidi": "financial district",
    "lic": "long island city",
    "spanish harlem": "east harlem",
    "el barrio": "east harlem",
    "the village": "greenwich village",
}


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


def norm(s):
    """Lowercase, drop apostrophes so "Hell's" -> "hells" (matches how people type),
    turn other punctuation into spaces, collapse spaces. The runtime matcher normalizes
    queries the same way, so keys line up."""
    s = s.lower().replace("'", "").replace("’", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def ring_centroid(ring):
    """Shoelace centroid + area of one polygon ring (list of [lon, lat])."""
    a = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i]
        x1, y1 = ring[i + 1]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if a == 0:  # degenerate ring — fall back to vertex average
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return [sum(xs) / len(ring), sum(ys) / len(ring)], 0.0
    a *= 0.5
    return [cx / (6 * a), cy / (6 * a)], abs(a)


def nta_centroid(geom):
    """Representative point for an NTA: centroid of its largest sub-polygon."""
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    best_c, best_a = None, -1.0
    for poly in polys:
        c, a = ring_centroid(poly[0])  # [0] = exterior ring
        if a > best_a:
            best_c, best_a = c, a
    return [round(best_c[0], 5), round(best_c[1], 5)]


def load_ntas():
    """Residential NTA features, from local cache or NYC Open Data."""
    if not os.path.exists(NTA_CACHE):
        os.makedirs(os.path.dirname(NTA_CACHE), exist_ok=True)
        with urllib.request.urlopen(NTA_URL, timeout=60) as r:
            data = r.read()
        with open(NTA_CACHE, "wb") as f:
            f.write(data)
    with open(NTA_CACHE) as f:
        return json.load(f)["features"]


def build_neighborhoods():
    """key -> {c, b, d}: normalized neighborhood name -> centroid, borough, display.
    On a key collision (e.g. Bushwick West/East, or a name shared across boroughs) the
    NTA with the larger shape_area wins, so bare names resolve to the more prominent one."""
    try:
        feats = load_ntas()
    except Exception as e:  # network/parse failure — ship ZIP+borough without neighborhoods
        print(f"  neighborhoods: skipped ({e})")
        return {}
    best = {}  # key -> (area, entry)
    for f in feats:
        p = f["properties"]
        name, boro = p["ntaname"], p["boroname"]
        area = float(p.get("shape_area") or 0)
        c = nta_centroid(f["geometry"])
        base = re.sub(r"\s*\([^)]*\)", "", name).strip()  # drop "(West)" etc.
        segs = [base] if (norm(base) in HYPHEN_KEEP or "-" not in base) else base.split("-")
        for seg in segs:
            k = norm(seg)
            if not k or (k in best and best[k][0] >= area):
                continue
            best[k] = (area, {"c": c, "b": boro, "d": seg.strip()})
    nbhds = {k: v[1] for k, v in best.items()}
    for alias, target in NBHD_ALIASES.items():
        if target in nbhds:
            nbhds[alias] = nbhds[target]
        else:
            print(f"  alias '{alias}' -> '{target}' skipped (no such neighborhood key)")
    return nbhds


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
    "nbhds": build_neighborhoods(),
}
with open(os.path.join(DATA_DIR, "gazetteer.json"), "w") as f:
    json.dump(out, f, separators=(",", ":"))

print(f"gazetteer: {len(out['zips'])} ZIPs, {len(out['boroughs'])} boroughs, "
      f"{len(out['nbhds'])} neighborhood keys -> data/gazetteer.json")
