# R-ATM — Atmosphere observatories

## Scope

U.S. long-term **atmospheric** observatories. The atmosphere sphere covers
greenhouse-gas baseline measurement, atmospheric chemistry, wet/dry deposition,
surface radiation, eddy-covariance flux, and column-trace-gas remote sensing.

Includes:
- NOAA Global Monitoring Laboratory (GML) baseline observatories
- NADP / NTN / AIRMoN / MDN deposition sites (long-record subset)
- AmeriFlux U.S. eddy-covariance towers (long-record)
- DOE ARM user-facility sites
- EPA CASTNET dry-deposition sites
- IMPROVE PM speciation sites
- NOAA SURFRAD surface-radiation network
- NASA AERONET U.S. AOD sites
- Pandonia Pandora trace-gas sites in the U.S.
- TCCON U.S. column-CO₂/CH₄ sites
- WMO GAW global stations on U.S. soil

Excludes: site-specific weather stations that are not part of a documented
long-term program; private corporate atmospheric instrumentation.

## Sources

1. <https://gml.noaa.gov/dv/site/> — NOAA GML site list (primary).
2. <https://nadp.slh.wisc.edu/sites/> — NADP site directory (primary).
3. <https://ameriflux.lbl.gov/sites/site-search/> — AmeriFlux registry (primary).
4. <https://www.arm.gov/capabilities/observatories> — DOE ARM observatories.
5. <https://www.epa.gov/castnet/castnet-site-locations> — CASTNET sites.
6. <http://vista.cira.colostate.edu/improve/data/IMPROVE/Studies.aspx> — IMPROVE.
7. <https://gml.noaa.gov/grad/surfrad/> — SURFRAD station list.
8. <https://aeronet.gsfc.nasa.gov/aeronet_locations.txt> — AERONET locations.
9. <https://www.pandonia-global-network.org/home/locations-contacts/> — Pandora.
10. <https://tccon-wiki.caltech.edu/Main/StatusOfSites> — TCCON status.

## Inputs

- `schema/vocab/{spheres,networks,facility_types,research_areas}.csv`.
- `agents/README.md` (shared facility JSON record schema).

## Outputs

- `data/raw/R-ATM/facilities_atm.json` — array of facility records,
  each with `primary_sphere = "atmosphere"`.

## Method

1. For each network, scrape the site listing; extract canonical name,
   acronym/site-code, lat/lng, established year, parent agency, URL.
2. Mark `record_length_years` from the site's stated start of record;
   set `long_term_threshold_met = (record_length_years >= 10)`.
3. Map to `facility_type`: `atmospheric-baseline` for GML stations,
   `flux-tower` for AmeriFlux towers, `federal` / `university-field-station`
   otherwise.
4. Set `facility_type = federal` and `parent_org` to the operating agency
   (NOAA, EPA, DOE, NASA, USDA-FS, …) when the platform is at a federal
   facility; otherwise use the host institution.
5. Populate `networks` with all relevant slugs from the vocab (e.g. a NADP
   site can also be a CASTNET co-located site → both slugs).
6. Pull `data_portal_url` from the network's data-archive landing page.
7. Deduplicate by `(canonical_name, hq_lat ± 0.001°)` before writing.

## Known landmarks

These records MUST appear in the output (QA gate):

- **Mauna Loa Observatory** (NOAA-GML, Hawaii) — established 1956.
- **Barrow / Utqiaġvik Atmospheric Baseline Observatory** (NOAA-GML, AK) — 1973.
- **South Pole Observatory** (NOAA-GML, AQ) — 1957.
- **American Samoa Observatory** (NOAA-GML, AS) — 1974.
- **Trinidad Head Observatory** (NOAA-GML, CA) — 2002.
- **Bondville, IL** (SURFRAD, NADP, AmeriFlux) — multi-network long-record.
- **Goodwin Creek, MS** (SURFRAD).
- **Park Falls / WLEF tall tower** (AmeriFlux US-PFa, WI) — established 1996.
- **Harvard Forest tall tower** (AmeriFlux US-Ha1, MA).
- **ARM Southern Great Plains Central Facility** (Lamont, OK).
- **ARM North Slope of Alaska** (Utqiaġvik / Atqasuk).
- **TCCON Lamont, OK** and **TCCON Park Falls, WI**.
