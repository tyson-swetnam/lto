# L-URL-FIX-* — Per-person homepage URL audit

## Goal

Most `people.homepage_url` values were emitted by earlier R-PEOPLE / Q-ENRICH
agents that fabricated likely-looking slugs (e.g. `/people/jane-doe`) without
verifying the URL exists. Many 404 in production. The user's request is:

> the directors and PI hyperlinks are almost all broken and do not lead
> to individual investigators staff profiles -- use sub agents and loops
> to investigate every person's staff profile url and update it in the
> database […] If they do not have a individual profile page, default to
> the staff profile page or the observatory website, or their personal
> website

## Sandbox constraint

Agents have NO network access. Use training-data knowledge of each
institution's URL pattern and well-known researchers; mark anything
constructed-from-pattern as `confidence: "medium"` so the next CI URL
HEAD pass (`scripts/check_url_health.py`, weekly) can verify and the
`scripts/url_hygiene.py` pass can null any that 404.

## Input

Each agent receives one slice of `data/raw/L-URL-FIX/<slice>.input.json`
containing rows of:

```json
{
  "person_id": "abc123…",
  "name": "Jane Doe",
  "orcid": null,
  "current_homepage_url": "…possibly broken…",
  "facility": "Scripps Institution of Oceanography",
  "facility_acronym": "SIO",
  "facility_url": "https://scripps.ucsd.edu",
  "facility_data_portal": "https://scrippsco2.ucsd.edu/",
  "role": "research-faculty",
  "title": "Distinguished Professor",
  "is_key": true
}
```

## Output

Write to `data/raw/L-URL-FIX-<slice>/homepage_updates.json`:

```json
[
  {
    "person_id": "abc123…",
    "name": "Jane Doe",
    "facility_acronym": "SIO",
    "homepage_url": "https://scripps.ucsd.edu/profiles/jdoe",
    "homepage_url_kind": "individual-profile" | "staff-listing" |
                        "facility-home" | "personal-site" | "orcid-fallback",
    "confidence": "high" | "medium" | "low",
    "source": "training-data" | "scripps directory recall" | "…",
    "notes": "Pattern: scripps.ucsd.edu/profiles/{lname}{first-initial}"
  }
]
```

### Resolution cascade

For each person, try in order:

1. **Verified individual profile** (high confidence, well-known
   researcher you can recall a specific URL for, e.g.
   `https://www.usgs.gov/staff-profiles/jayne-belnap`).
2. **Constructed individual profile** (medium confidence) using a
   well-attested per-institution URL pattern with the person's name as
   the slug. Examples below.
3. **Staff-listing page** (medium confidence) — institutional staff
   directory where the person's bio likely lives, e.g.
   `https://www.fs.usda.gov/research/people` or
   `https://www.usgs.gov/centers/forrsc/staff`.
4. **Facility homepage / data portal** (low confidence) — if you
   cannot find any path to the person's profile, just point at
   `facility_url` or `facility_data_portal`.

### Per-institution URL patterns (training-data)

| Institution | Pattern | Example |
|-------------|---------|---------|
| USGS | `https://www.usgs.gov/staff-profiles/<slug>` | jayne-belnap |
| USFS Research (PNW/PSW/RMRS/SRS/NRS) | `https://research.fs.usda.gov/people/<slug>` | thomas-spies |
| USDA-ARS | `https://www.ars.usda.gov/people-locations/person/?person-id=<id>` | numeric ID — only emit if you recall the person-id |
| NOAA OAR (PMEL/AOML/GLERL/GFDL) | `https://www.<lab>.noaa.gov/People/<surname>` | varies by lab |
| NOAA Fisheries | `https://www.fisheries.noaa.gov/contact/<slug>` | slug = first-last |
| EPA ORD | `https://www.epa.gov/aboutepa/about-<lab>` (lab listings) | rarely individual |
| NPS | rarely has individual profiles; default to park page |
| Smithsonian (NMNH/SI/SCBI/STRI/SERC) | `https://<unit>.si.edu/staff/<slug>` or `https://www.si.edu/researchers/<slug>` | `serc.si.edu/staff/anson-h-hines` |
| WHOI | `https://www.whoi.edu/profile/<slug>/` | `https://www.whoi.edu/profile/csiuda/` |
| Scripps | `https://scripps.ucsd.edu/profiles/<initials>` (legacy) or `https://scripps.ucsd.edu/programs/staff/<slug>` | varies |
| Generic university | `https://<dept>.<school>.edu/people/<slug>` or `/faculty/<slug>` | depends on dept |
| The Nature Conservancy | rarely individual; default to chapter page |
| MBL | `https://www.mbl.edu/about/scientific-staff/<slug>` | |
| Bigelow | `https://www.bigelow.org/about/people/<slug>.html` | |
| Mote | `https://mote.org/research/scientists/<slug>` | |
| LBNL ESS | `https://eesa.lbl.gov/profiles/<slug>` | |
| ORNL | `https://www.ornl.gov/staff-profile/<slug>` | |
| Argonne | `https://www.anl.gov/profile/<slug>` | |
| LANL | `https://www.lanl.gov/our-people/<slug>` | |

### Hard rules

- NEVER invent a URL just because the pattern looks plausible — flag
  with `confidence: "low"` if you're constructing without verification.
- Where the prior URL was clearly fabricated (looks like
  `…/people/<lowercased-name-with-hyphens>` and you don't recall the
  person specifically), prefer falling back to the facility staff
  listing or facility URL with `confidence: "low"`.
- Skip people you cannot improve at all (their `current_homepage_url`
  may already be correct or you have nothing to add). Don't emit a
  no-op row.
- If an ORCID is present and no profile URL exists, emit
  `homepage_url: "https://orcid.org/<orcid>"` with kind=`orcid-fallback`.

## Loader

`scripts/apply_homepage_url_fixes.py` reads every
`data/raw/L-URL-FIX-*/homepage_updates.json` and runs:

```sql
UPDATE people SET homepage_url = ? WHERE person_id = ?
```

so re-running an agent overwrites earlier emissions. The next
`scripts/url_hygiene.py` pass nulls broken patterns, and
`scripts/check_url_health.py` (weekly CI) HTTP-HEAD-verifies the
remaining URLs.
