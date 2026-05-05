# R2 — US universities, marine labs, and field stations

## Scope
University-operated marine laboratories, coastal field stations, oceanographic
institutions, and university-based coastal research centers in the United States.
Covers both public and private institutions; HQ can be inland so long as they
operate a coastal field facility or a coastal research program.

Exclusions: federal labs (→ R1), purely state-government agencies (→ R4),
multi-institution networks (→ R3).

## Sources
- https://www.naml.org/members/ — National Association of Marine Laboratories
- https://obfs.org/ — Organization of Biological Field Stations (coastal subset)
- https://www.cossa.org/ consortium of ocean leadership membership list
- https://oceanleadership.org/members/
- Individual institution sites (.edu)
- https://www.nsf.gov/awardsearch/ — to confirm active funding
- https://carnegieclassifications.acenet.edu/ — for institution classification

## Inputs
- Wave 1 vocab CSVs
- R1 output (to avoid duplicating federally owned labs sometimes hosted on
  campuses, e.g., NOAA NCCOS Beaufort at Duke's Pivers Island)

## Outputs
- `data/raw/R2/facilities_universities_us.json`
- `data/raw/R2/notes.md`

## Method
1. Seed from the NAML member directory (~28 labs) and OBFS coastal members.
2. Add oceanographic institutions (Scripps, WHOI, MBARI, Bigelow) and university
   marine/coastal centers (VIMS, URI-GSO, UH-HIMB, Rutgers-IMCS, UDel CEOE,
   UNC-CSI, UGA-Skidaway, USC-SeaGrant, FSU-CML, TAMU-Galveston).
3. For each, capture parent institution, HQ campus location (inland OK), and all
   field-station locations.
4. Record research areas and any named NSF / NOAA / state funding programs.
5. Mark public vs private via `facility_type` (use `university-marine-lab`).

## Known landmarks (must appear)
- Scripps Institution of Oceanography (UC San Diego) — La Jolla, CA
- Woods Hole Oceanographic Institution — Woods Hole, MA (private non-profit)
- Monterey Bay Aquarium Research Institute (MBARI) — Moss Landing, CA
- Marine Biological Laboratory (MBL / U Chicago) — Woods Hole, MA
- Hawai'i Institute of Marine Biology (UH Mānoa) — Kāne'ohe, HI
- Friday Harbor Laboratories (U Washington) — Friday Harbor, WA
- Bodega Marine Laboratory (UC Davis) — Bodega Bay, CA
- Hopkins Marine Station (Stanford) — Pacific Grove, CA
- Oregon Institute of Marine Biology (U Oregon) — Charleston, OR
- Hatfield Marine Science Center (Oregon State) — Newport, OR
- Shannon Point Marine Center (Western WA U) — Anacortes, WA
- Skidaway Institute of Oceanography (U Georgia) — Savannah, GA
- Dauphin Island Sea Lab — Dauphin Island, AL
- Virginia Institute of Marine Science (W&M) — Gloucester Point, VA
- Duke Marine Laboratory — Beaufort, NC
- Institute of Marine Sciences (UNC-Chapel Hill) — Morehead City, NC
- Bigelow Laboratory for Ocean Sciences — East Boothbay, ME
- Darling Marine Center (U Maine) — Walpole, ME
- URI Graduate School of Oceanography — Narragansett, RI
- Rutgers Institute of Marine and Coastal Sciences — New Brunswick / Tuckerton, NJ
- UDel College of Earth, Ocean & Environment — Lewes, DE
- Horn Point Laboratory (UMCES) — Cambridge, MD
- Chesapeake Biological Laboratory (UMCES) — Solomons, MD
- Florida Institute of Oceanography + Keys Marine Lab — Tampa / Layton, FL
- Harbor Branch Oceanographic Institute (FAU) — Fort Pierce, FL
- Rosenstiel School (U Miami) — Miami, FL
- Louisiana Universities Marine Consortium (LUMCON) — Chauvin, LA
- Texas A&M Galveston + Geochemical and Environmental Research Group
- Moss Landing Marine Laboratories (CSU) — Moss Landing, CA
