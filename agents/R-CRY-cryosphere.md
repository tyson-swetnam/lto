# R-CRY — Cryosphere observatories

## Scope

U.S. long-term **cryosphere** observatories — snow, ice, glaciers, sea ice,
permafrost, and polar systems.

Includes:
- USGS Benchmark Glaciers (Wolverine, Gulkana, South Cascade, Sperry, Lemon Creek).
- NRCS SNOTEL sites with ≥30-year records.
- USACE Cold Regions Research and Engineering Laboratory (CRREL).
- Toolik Field Station (Arctic LTER instrumentation).
- McMurdo Dry Valleys (LTER + USAP cryosphere observations).
- Palmer Station (LTER + USAP sea-ice & glacial-melt observations).
- Juneau Icefield Research Program.
- Niwot Ridge LTER snow / ice instrumentation.
- North Slope of Alaska permafrost monitoring (USGS, Univ. Alaska Fairbanks).

Excludes: short-record snow telemetry stations; non-U.S. polar stations.
U.S.-funded Antarctic stations are **in scope** with `country = "AQ"`.

## Sources

1. <https://www.usgs.gov/programs/climate-research-and-development-program/science/usgs-benchmark-glacier-project> — USGS benchmark glaciers.
2. <https://www.nrcs.usda.gov/wps/portal/wcc/home/snowClimateMonitoring/> — SNOTEL.
3. <https://www.erdc.usace.army.mil/Locations/CRREL/> — CRREL.
4. <https://toolik.alaska.edu/> — Toolik Field Station.
5. <https://mcmlter.org/> — McMurdo Dry Valleys LTER.
6. <https://pal.lternet.edu/> — Palmer Station LTER.
7. <https://juneauicefield.org/> — Juneau Icefield Research Program.
8. <https://nsidc.org/data/data-sets-by-name> — NSIDC long-record cryosphere sites.

## Inputs

- `schema/vocab/{spheres,networks,facility_types,research_areas,life_zones}.csv`.

## Outputs

- `data/raw/R-CRY/facilities_cry.json`.

## Method

1. Enumerate USGS benchmark glaciers; one record per glacier with
   `facility_type = "glacier-monitoring"`, `primary_sphere = "cryosphere"`,
   ecosystem `glacier-icefield`, life zone `polar-desert` or `subalpine-rain`.
2. SNOTEL: filter to long-record (≥30y) sites in mountain West + AK; one
   record per site with `facility_type = "streamgage-network"` *not* — use
   `federal` and put SNOTEL in `networks`. Honestly this is borderline
   between cryosphere and freshwater; mark `secondary_spheres = ["freshwater"]`.
3. Toolik, McMurdo, Palmer: cross-list with R-TER-LTER but here record the
   cryosphere-specific instrumentation (snow chemistry, glacier mass balance,
   sea-ice extent). Use `secondary_spheres = ["terrestrial"]` or
   `["ocean-estuarine"]` as appropriate.
4. Coordinates from GeoJSON in NSIDC archives where available; otherwise
   geocode address.

## Known landmarks

- **Wolverine Glacier** (AK) — USGS Benchmark, 1966–.
- **Gulkana Glacier** (AK) — USGS Benchmark, 1966–.
- **South Cascade Glacier** (WA) — USGS Benchmark, 1958–.
- **Sperry Glacier** (MT) — USGS Benchmark, 2005–.
- **Lemon Creek Glacier** (AK) — Juneau Icefield, 1953–.
- **Toolik Field Station** (AK).
- **McMurdo Dry Valleys LTER** (AQ).
- **Palmer Station LTER** (AQ).
- **CRREL** (Hanover, NH).
- **Niwot Ridge cryosphere instrumentation** (CO).
- **Imnavait Creek tussock-tundra** snowpack (AK).
