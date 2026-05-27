# NYC Medicaid Provider Map

A visual, filterable map of Medicaid-enrolled providers across the five NYC boroughs, built on NY State Open Data. Filter by category (dental, vision, primary care, pharmacy, behavioral health, therapy, home care, and more) and borough; search by name or address; click a location to see every provider at that address.

Built with MapLibre GL (CARTO Positron basemap) and deck.gl. No build step.

## Run it

```bash
python3 fetch_data.py        # pull + clean the data → data.json, providers.geojson
python3 -m http.server 8000  # serve (data.json is ~55 MB; needs a server, not file://)
```

Then open <http://localhost:8000>. The default view (dental + vision, ~12k points) loads instantly; toggling on the larger categories renders the full ~353k points.

## How it works

- **`fetch_data.py`** — pages the NYC slice from the Socrata API, drops bad coordinates and duplicate provider-at-address rows, maps each of the 74 raw professions into ~12 display categories, and writes:
  - `data.json` — compact snapshot the map loads
  - `providers.geojson` — portable GeoJSON for GIS / other tools
- **`index.html`** — a self-contained static page: MapLibre GL basemap + a deck.gl `ScatterplotLayer` overlay. Providers are aggregated to one dot per location (sized by provider count) on the fly, respecting the active filters.

## Scope & data caveats

- **Source:** NY State [Medicaid Enrolled Provider Listing](https://health.data.ny.gov/Health/Medicaid-Enrolled-Provider-Listing/keti-qx5t) (Socrata `keti-qx5t`).
- **Geography:** the 5 NYC boroughs.
- **Providers:** all professions, **direct-service only** — `medicaid_type` FFS + MCO. OPRA (order/refer-only, non-billing) providers are excluded.
- **Enrolled ≠ in-network.** Most NYC Medicaid recipients are in managed-care plans. This dataset reflects Medicaid *enrollment* (FFS billing eligibility), not plan-network membership — a near-complete **superset**. The authoritative "does this provider take my Medicaid" answer is the member's managed-care plan directory.
- **Vision** = optometrists / opticians / optical establishments only. Ophthalmologists (eye MDs) sit under the generic `PHYSICIAN` category with no specialty field, so they can't be isolated.
- **No phone numbers** — the published columns omit the telephone field the data dictionary advertises. Details show address + NPI.

## Refreshing

The state updates the dataset regularly. Re-run `python3 fetch_data.py` to pull a fresh snapshot; no other changes needed.
