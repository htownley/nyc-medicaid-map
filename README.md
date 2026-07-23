# NYC Medicaid Provider Map

A visual, filterable map of Medicaid-enrolled providers across the five NYC boroughs, built on NY State Open Data. Filter by category (dental, vision, primary care, pharmacy, behavioral health, therapy, home care, and more) and borough; search by name; find providers near an address (via [NYC GeoSearch](https://geosearch.planninglabs.nyc)), a ZIP, a neighborhood, a borough, or your location; click a location to see every provider at that address.

Built with MapLibre GL (CARTO Positron basemap) and deck.gl. No build step. Works on phones: on small screens the map fills the viewport and the panel becomes a draggable bottom sheet.

## Run it

```bash
python3 fetch_data.py        # pull + clean the data → data/, providers.geojson
python3 build_gazetteer.py   # build the ZIP/neighborhood/borough search index → data/gazetteer.json
python3 -m http.server 8000  # serve (data is fetched at runtime; needs a server, not file://)
```

Then open <http://localhost:8000>.

## How it works

- **`fetch_data.py`** — pages the NYC slice from the Socrata API, drops bad coordinates and duplicate provider-at-address rows, maps each of the ~74 raw professions into 12 display categories, and writes:
  - `data/meta.json` — categories, per-category counts, snapshot date (loaded at boot)
  - `data/cat-0.json` … `data/cat-11.json` — points per category, fetched only when that filter is enabled
  - `providers.geojson` — portable GeoJSON for GIS / other tools
- **`build_gazetteer.py`** — builds `data/gazetteer.json`, a small lookup that lets the search box resolve a bare ZIP, neighborhood, or borough (things GeoSearch has no layer for and mis-parses). ZIP and borough centroids come from the provider data itself; neighborhood names + centroids come from DCP's [2020 NTAs](https://data.cityofnewyork.us/City-Government/2020-Neighborhood-Tabulation-Areas-NTAs-/9nt8-h7nd) (cached under `build_cache/`). A query that isn't a place still falls through to GeoSearch for street addresses.
- **`index.html`** — a self-contained static page: MapLibre GL basemap + a deck.gl `ScatterplotLayer` overlay. Providers are aggregated to one dot per location (sized by provider count) on the fly, respecting the active filters.

The default view (dental + vision, ~12.5k points) costs about **330 KB compressed** over the network; other categories load on demand when toggled. The largest — Physicians & Primary Care, ~304k of the ~356k points — is about 7 MB compressed, fetched only if you turn it on.

### Scaling: the next rung

Per-category files loaded on demand are the right size for this dataset because the app's search, nearest-location list, and live counts all want the working set in memory. If a dataset outgrows that (or you only need display), the next rung is pre-tiling: `tippecanoe` → a single [PMTiles](https://protomaps.com/docs/pmtiles) file, which browsers read by HTTP range request straight off static hosting — the browser then fetches only the tiles in view, at any dataset size.

## Accessibility

Filter changes are announced via live regions; the nearest-location results are real buttons (keyboard operable); the detail card closes on Esc and returns focus; text colors meet WCAG AA contrast. The map canvas itself is not keyboard-navigable — the "find providers near you" list is the accessible pathway to the same information.

## Scope & data caveats

- **Source:** NY State [Medicaid Enrolled Provider Listing](https://health.data.ny.gov/Health/Medicaid-Enrolled-Provider-Listing/keti-qx5t) (Socrata `keti-qx5t`).
- **Geography:** the 5 NYC boroughs.
- **Providers:** all professions, **direct-service only** — `medicaid_type` FFS + MCO. OPRA (order/refer-only, non-billing) providers are excluded.
- **Enrolled ≠ in-network.** Most NYC Medicaid recipients are in managed-care plans. This dataset reflects Medicaid *enrollment* (FFS billing eligibility), not plan-network membership — a near-complete **superset**. The authoritative "does this provider take my Medicaid" answer is the member's managed-care plan directory.
- **Vision** = optometrists / opticians / optical establishments only. Ophthalmologists (eye MDs) sit under the generic `PHYSICIAN` category with no specialty field, so they can't be isolated.
- **No phone numbers** — the published columns omit the telephone field the data dictionary advertises. As a stopgap, each provider's NPI in the detail card links to their federal [NPPES registry](https://npiregistry.cms.hhs.gov/) entry (`provider-view/{NPI}`), which lists a self-reported phone. Registry data can be stale, and organizations show one org-level number for all their sites.

## Refreshing

The state updates the dataset regularly. Re-run `python3 fetch_data.py` to pull a fresh snapshot, then `python3 build_gazetteer.py` to rebuild the ZIP/borough centroids from it. The neighborhood layer changes rarely; delete `build_cache/` if you want to re-pull the NTA boundaries too.
