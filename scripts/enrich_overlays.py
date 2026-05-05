#!/usr/bin/env python3
"""
Enrich public/overlays/*.geojson with full names, websites, descriptions,
and other authoritative metadata the app can show in popups. Also collapses
same-name Polygon fragments into single MultiPolygon features so each site
is one record.

Run from the repo root:   python3 scripts/enrich_overlays.py
"""
from __future__ import annotations
import json
import os
import sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OV   = os.path.join(ROOT, 'public', 'overlays')


# ── helpers ─────────────────────────────────────────────────────────

def load(p):
    with open(p) as f:
        return json.load(f)

def save(p, j):
    with open(p, 'w') as f:
        json.dump(j, f, ensure_ascii=False, separators=(', ', ': '))

def merge_by_name(geojson):
    """
    Collapse features with the same `properties.name` into one feature.
    Polygon -> lifted into MultiPolygon; MultiPolygons are concatenated.
    """
    grouped = OrderedDict()
    for f in geojson['features']:
        name = (f.get('properties') or {}).get('name') or f'__row_{id(f)}'
        geom = f.get('geometry') or {}
        gtype = geom.get('type')
        coords = geom.get('coordinates') or []
        if gtype == 'Polygon':
            polys = [coords]
        elif gtype == 'MultiPolygon':
            polys = list(coords)
        else:
            grouped[f'__passthrough_{id(f)}'] = f
            continue
        if name not in grouped:
            grouped[name] = {
                'type': 'Feature',
                'properties': dict(f.get('properties') or {}),
                'geometry': {'type': 'MultiPolygon', 'coordinates': polys[:]},
            }
        else:
            grouped[name]['geometry']['coordinates'].extend(polys)
    out = []
    for _, feat in grouped.items():
        if feat.get('type') == 'Feature' and feat.get('geometry', {}).get('type') == 'MultiPolygon':
            cs = feat['geometry']['coordinates']
            if len(cs) == 1:
                feat['geometry'] = {'type': 'Polygon', 'coordinates': cs[0]}
        out.append(feat)
    geojson['features'] = out
    return geojson

FORCE_OVERWRITE = {'name', 'state'}

def enrich(p, table, key='name'):
    """
    Merge the `table` of per-name metadata into matching features.

    Rules:
      * `name`, `state` -> always overwritten by metadata (the legacy
        values in several files carry junk like state='National Park
        Service', or names that are just acronyms).
      * every other field -> fill-only (don't stomp existing values).
      * When we overwrite `name`, the old value is stashed under
        `short` so the acronym / original label isn't lost.
    """
    j = load(p)
    updated = 0
    for feat in j['features']:
        props = feat.setdefault('properties', {})
        k = props.get(key)
        meta = table.get(k)
        if not meta:
            continue
        for mk, mv in meta.items():
            if mv is None:
                continue
            if mk == 'name':
                old = props.get('name')
                if old and old != mv and not props.get('short'):
                    props['short'] = old
                props['name'] = mv
            elif mk in FORCE_OVERWRITE:
                props[mk] = mv
            elif props.get(mk) in (None, '', 0):
                props[mk] = mv
        updated += 1
    save(p, j)
    return updated, len(j['features'])


# ── NATIONAL MARINE SANCTUARIES (13) ────────────────────────────────
# Name -> replacement label, acronym, website, year designated, manager,
# short description. Data drawn from sanctuaries.noaa.gov site pages.

NMS = {
    'cbnms National Marine Sanctuary': {
        'name': 'Cordell Bank National Marine Sanctuary',
        'acronym': 'CBNMS',
        'url': 'https://cordellbank.noaa.gov/',
        'year_designated': 1989,
        'manager': 'NOAA Office of National Marine Sanctuaries',
        'state': 'California',
        'description': 'Offshore California sanctuary protecting a submerged '
                       'granite bank and its associated deep-sea and pelagic '
                       'ecosystem.',
    },
    'CINMS': {
        'name': 'Channel Islands National Marine Sanctuary',
        'acronym': 'CINMS',
        'url': 'https://channelislands.noaa.gov/',
        'year_designated': 1980,
        'manager': 'NOAA Office of National Marine Sanctuaries',
        'state': 'California',
        'description': 'Waters surrounding five of the Channel Islands off '
                       'Southern California; a biologically diverse '
                       'transition zone between cold and warm Pacific currents.',
    },
    'fgbnms National Marine Sanctuary': {
        'name': 'Flower Garden Banks National Marine Sanctuary',
        'acronym': 'FGBNMS',
        'url': 'https://flowergarden.noaa.gov/',
        'year_designated': 1992,
        'manager': 'NOAA Office of National Marine Sanctuaries',
        'state': 'Texas / Louisiana (offshore)',
        'description': 'Coral reefs and banks on the Texas–Louisiana outer '
                       'continental shelf in the Gulf of Mexico.',
    },
    'FKNMS': {
        'name': 'Florida Keys National Marine Sanctuary',
        'acronym': 'FKNMS',
        'url': 'https://floridakeys.noaa.gov/',
        'year_designated': 1990,
        'manager': 'NOAA Office of National Marine Sanctuaries',
        'state': 'Florida',
        'description': 'Third-largest barrier reef ecosystem in the world, '
                       'encompassing the Florida Keys coral reef tract.',
    },
    'grnms National Marine Sanctuary': {
        'name': "Gray's Reef National Marine Sanctuary",
        'acronym': 'GRNMS',
        'url': 'https://graysreef.noaa.gov/',
        'year_designated': 1981,
        'manager': 'NOAA Office of National Marine Sanctuaries',
        'state': 'Georgia',
        'description': 'Live-bottom reef 17 nmi off Sapelo Island, GA — one '
                       'of the largest nearshore live-bottom reefs in the '
                       'southeastern United States.',
    },
    'HIHWNMS': {
        'name': 'Hawaiian Islands Humpback Whale National Marine Sanctuary',
        'acronym': 'HIHWNMS',
        'url': 'https://hawaiihumpbackwhale.noaa.gov/',
        'year_designated': 1992,
        'manager': 'NOAA Office of National Marine Sanctuaries (co-managed '
                   'with the State of Hawaiʻi)',
        'state': 'Hawaii',
        'description': 'Protects the primary wintering, mating, calving, and '
                       'nursing grounds for the North Pacific humpback whale '
                       'population.',
    },
    'MBNMS': {
        'name': 'Monterey Bay National Marine Sanctuary',
        'acronym': 'MBNMS',
        'url': 'https://montereybay.noaa.gov/',
        'year_designated': 1992,
        'manager': 'NOAA Office of National Marine Sanctuaries',
        'state': 'California',
        'description': 'The nation’s largest contiguous NMS; kelp forests, '
                       'open ocean, and the Monterey Submarine Canyon.',
    },
    'MNMS': {
        'name': 'Mallows Bay–Potomac River National Marine Sanctuary',
        'acronym': 'MPRNMS',
        'url': 'https://mallowsbay.noaa.gov/',
        'year_designated': 2019,
        'manager': 'NOAA Office of National Marine Sanctuaries',
        'state': 'Maryland',
        'description': 'Freshwater tidal sanctuary centered on the "Ghost '
                       'Fleet of Mallows Bay" — nearly 100 WWI-era wooden '
                       'steamship wrecks.',
    },
    'NMSAS': {
        'name': 'National Marine Sanctuary of American Samoa',
        'acronym': 'NMSAS',
        'url': 'https://americansamoa.noaa.gov/',
        'year_designated': 1986,
        'manager': 'NOAA Office of National Marine Sanctuaries (co-managed '
                   'with American Samoa)',
        'state': 'American Samoa',
        'description': 'Six protected management areas across the Samoan '
                       'archipelago, including Fagatele Bay and Rose Atoll.',
    },
    'OCNMS': {
        'name': 'Olympic Coast National Marine Sanctuary',
        'acronym': 'OCNMS',
        'url': 'https://olympiccoast.noaa.gov/',
        'year_designated': 1994,
        'manager': 'NOAA Office of National Marine Sanctuaries (co-managed '
                   'with the Makah, Quileute, Hoh, and Quinault tribes)',
        'state': 'Washington',
        'description': '3,188 sq mi along 135 mi of Washington’s outer coast '
                       '— temperate rain-forest shoreline and productive '
                       'continental shelf habitats.',
    },
    'Papahānaumokuākea Marine National Monument National Marine Sanctuary': {
        'name': 'Papahānaumokuākea Marine National Monument',
        'acronym': 'PMNM',
        'url': 'https://www.papahanaumokuakea.gov/',
        'year_designated': 2006,
        'manager': 'NOAA, USFWS, State of Hawaiʻi, and the Office of '
                   'Hawaiian Affairs (co-trustees)',
        'state': 'Hawaii (Northwestern Hawaiian Islands)',
        'description': 'One of the largest marine protected areas on Earth. '
                       'UNESCO World Heritage Site. Expanded in 2016 to '
                       '582,578 sq mi.',
    },
    'SBNMS': {
        'name': 'Stellwagen Bank National Marine Sanctuary',
        'acronym': 'SBNMS',
        'url': 'https://stellwagen.noaa.gov/',
        'year_designated': 1992,
        'manager': 'NOAA Office of National Marine Sanctuaries',
        'state': 'Massachusetts',
        'description': 'Glacially-deposited underwater plateau at the mouth '
                       'of Massachusetts Bay; critical feeding ground for '
                       'endangered North Atlantic humpback, fin, and right whales.',
    },
    'Thunder Bay National Marine Sanctuary': {
        'name': 'Thunder Bay National Marine Sanctuary',
        'acronym': 'TBNMS',
        'url': 'https://thunderbay.noaa.gov/',
        'year_designated': 2000,
        'manager': 'NOAA Office of National Marine Sanctuaries (co-managed '
                   'with the State of Michigan)',
        'state': 'Michigan (Lake Huron)',
        'description': 'Protects ≈200 known shipwrecks in northwestern '
                       'Lake Huron; the only freshwater NMS.',
    },
}


# ── MARINE NATIONAL MONUMENTS (4) ───────────────────────────────────

MONUMENTS = {
    'Rose Atoll Marine National Monument': {
        'acronym': 'RAMNM',
        'url': 'https://www.fws.gov/refuge/rose-atoll-marine',
        'year_designated': 2009,
        'manager': 'U.S. Fish and Wildlife Service / NOAA',
        'state': 'American Samoa',
        'description': 'Easternmost point of the United States; a small '
                       'atoll and surrounding waters with vibrant pink '
                       'crustose coralline algae reefs.',
    },
    'Pacific Remote Islands Marine National Monument': {
        'acronym': 'PRIMNM',
        'url': 'https://www.fws.gov/refuge/pacific-remote-islands-marine-national-monument',
        'year_designated': 2009,
        'manager': 'U.S. Fish and Wildlife Service / NOAA',
        'state': 'U.S. Minor Outlying Islands (Pacific)',
        'description': 'Seven remote central-Pacific islands and atolls '
                       '(Baker, Howland, Jarvis, Johnston, Kingman, Palmyra, '
                       'Wake) and the surrounding EEZ — 490,000+ sq mi.',
    },
    'Marianas Trench Marine National Monument': {
        'acronym': 'MTMNM',
        'url': 'https://www.fws.gov/refuge/marianas-trench-marine-national-monument',
        'year_designated': 2009,
        'manager': 'U.S. Fish and Wildlife Service / NOAA',
        'state': 'Commonwealth of the Northern Mariana Islands',
        'description': 'Includes the deepest part of the world ocean '
                       '(Challenger Deep) and active submarine volcanoes '
                       'along the Mariana Arc.',
    },
    'Northeast Canyons and Seamounts Marine National Monument': {
        'acronym': 'NECSMNM',
        'url': 'https://www.fisheries.noaa.gov/new-england-mid-atlantic/habitat-conservation/northeast-canyons-and-seamounts-marine-national-monument',
        'year_designated': 2016,
        'manager': 'NOAA / U.S. Fish and Wildlife Service',
        'state': 'Offshore New England (U.S. Atlantic EEZ)',
        'description': 'Three underwater canyons (Oceanographer, Gilbert, '
                       'Lydonia) and four seamounts (Bear, Physalia, '
                       'Retriever, Mytilus) ~150 mi SE of Cape Cod.',
    },
}


# ── NEON ECOLOGICAL DOMAINS (20) ────────────────────────────────────

NEON_URL = 'https://www.neonscience.org/field-sites/about-field-sites'
def neon_url(domain_id):
    return f'https://www.neonscience.org/field-sites/about-field-sites#d{int(domain_id):02d}'

NEON = {
    'Northeast':                           {'domain_id': 1,  'acronym': 'D01', 'description': 'Glaciated New England and adjacent Canadian Maritimes.'},
    'Mid Atlantic':                        {'domain_id': 2,  'acronym': 'D02', 'description': 'Mid-Atlantic coastal plain and Piedmont.'},
    'Southeast':                           {'domain_id': 3,  'acronym': 'D03', 'description': 'Southeastern US coastal plain.'},
    'Atlantic Neotropical':                {'domain_id': 4,  'acronym': 'D04', 'description': 'Puerto Rico and the US Virgin Islands tropical forests.'},
    'Great Lakes':                         {'domain_id': 5,  'acronym': 'D05', 'description': 'Great Lakes basin mixed deciduous/boreal forests.'},
    'Prairie Peninsula':                   {'domain_id': 6,  'acronym': 'D06', 'description': 'Tallgrass prairie peninsula of the US Midwest.'},
    'Appalachians / Cumberland Plateau':   {'domain_id': 7,  'acronym': 'D07', 'description': 'Appalachian Mountains and Cumberland Plateau.'},
    'Ozarks Complex':                      {'domain_id': 8,  'acronym': 'D08', 'description': 'Ozark Plateau and Ouachita Mountains.'},
    'Northern Plains':                     {'domain_id': 9,  'acronym': 'D09', 'description': 'Glaciated mixed-grass and shortgrass plains.'},
    'Central Plains':                      {'domain_id': 10, 'acronym': 'D10', 'description': 'Central Great Plains shortgrass/mixed prairie.'},
    'Southern Plains':                     {'domain_id': 11, 'acronym': 'D11', 'description': 'Southern Great Plains.'},
    'Northern Rockies':                    {'domain_id': 12, 'acronym': 'D12', 'description': 'Northern Rocky Mountains and intermontane valleys.'},
    'Southern Rockies / Colorado Plateau': {'domain_id': 13, 'acronym': 'D13', 'description': 'Southern Rockies and Colorado Plateau high desert.'},
    'Desert Southwest':                    {'domain_id': 14, 'acronym': 'D14', 'description': 'Sonoran and Chihuahuan desert systems.'},
    'Great Basin':                         {'domain_id': 15, 'acronym': 'D15', 'description': 'Great Basin sagebrush steppe.'},
    'Pacific Northwest':                   {'domain_id': 16, 'acronym': 'D16', 'description': 'Temperate rainforests and Cascades from northern California to British Columbia.'},
    'Pacific Southwest':                   {'domain_id': 17, 'acronym': 'D17', 'description': 'California Mediterranean and montane ecosystems.'},
    'Tundra':                              {'domain_id': 18, 'acronym': 'D18', 'description': 'Arctic tundra of northern Alaska.'},
    'Taiga':                               {'domain_id': 19, 'acronym': 'D19', 'description': 'Boreal forests of interior Alaska.'},
    'Pacific Tropical':                    {'domain_id': 20, 'acronym': 'D20', 'description': 'Hawaiian Islands tropical montane and coastal systems.'},
}


# ── EPA REGIONS (10) ────────────────────────────────────────────────

EPA = {
    'EPA Region Region 1':  {'name': 'EPA Region 1 — New England',         'states': 'CT, ME, MA, NH, RI, VT',            'hq': 'Boston, MA',        'url': 'https://www.epa.gov/aboutepa/epa-region-1-new-england'},
    'EPA Region Region 2':  {'name': 'EPA Region 2',                        'states': 'NJ, NY, PR, USVI',                 'hq': 'New York, NY',      'url': 'https://www.epa.gov/aboutepa/about-epa-region-2'},
    'EPA Region Region 3':  {'name': 'EPA Region 3 — Mid-Atlantic',         'states': 'DE, DC, MD, PA, VA, WV',           'hq': 'Philadelphia, PA',  'url': 'https://www.epa.gov/aboutepa/about-epa-region-3-mid-atlantic'},
    'EPA Region Region 4':  {'name': 'EPA Region 4 — Southeast',            'states': 'AL, FL, GA, KY, MS, NC, SC, TN',   'hq': 'Atlanta, GA',       'url': 'https://www.epa.gov/aboutepa/about-epa-region-4-southeast'},
    'EPA Region Region 5':  {'name': 'EPA Region 5 — Great Lakes',          'states': 'IL, IN, MI, MN, OH, WI',           'hq': 'Chicago, IL',       'url': 'https://www.epa.gov/aboutepa/epa-region-5'},
    'EPA Region Region 6':  {'name': 'EPA Region 6 — South Central',        'states': 'AR, LA, NM, OK, TX',               'hq': 'Dallas, TX',        'url': 'https://www.epa.gov/aboutepa/about-epa-region-6-south-central'},
    'EPA Region Region 7':  {'name': 'EPA Region 7',                        'states': 'IA, KS, MO, NE',                   'hq': 'Lenexa, KS',        'url': 'https://www.epa.gov/aboutepa/about-epa-region-7'},
    'EPA Region Region 8':  {'name': 'EPA Region 8 — Mountains and Plains', 'states': 'CO, MT, ND, SD, UT, WY',           'hq': 'Denver, CO',        'url': 'https://www.epa.gov/aboutepa/about-epa-region-8'},
    'EPA Region Region 9':  {'name': 'EPA Region 9 — Pacific Southwest',    'states': 'AZ, CA, HI, NV, Pacific Islands',  'hq': 'San Francisco, CA', 'url': 'https://www.epa.gov/aboutepa/about-epa-region-9-pacific-southwest'},
    'EPA Region Region 10': {'name': 'EPA Region 10 — Pacific Northwest',   'states': 'AK, ID, OR, WA',                   'hq': 'Seattle, WA',       'url': 'https://www.epa.gov/aboutepa/about-epa-region-10-pacific-northwest'},
}


# ── NERR RESERVES (28) ──────────────────────────────────────────────
#
# NOAA keeps canonical reserve pages at coast.noaa.gov/nerrs/reserves/<slug>
# The individual reserve websites (below) are the operational portals.

NERR = {
    'ACE Basin NERR':              {'name': 'ACE Basin National Estuarine Research Reserve',            'state': 'South Carolina', 'url': 'https://acebasinnerr.org/'},
    'Apalachicola NERR':           {'name': 'Apalachicola National Estuarine Research Reserve',         'state': 'Florida',        'url': 'https://apalachicolareserve.com/'},
    'Chesapeake Bay Maryland NERR':{'name': 'Chesapeake Bay Maryland National Estuarine Research Reserve','state': 'Maryland',     'url': 'https://dnr.maryland.gov/waters/cbnerr/'},
    'Chesapeake Bay Virginia NERR':{'name': 'Chesapeake Bay Virginia National Estuarine Research Reserve','state': 'Virginia',     'url': 'https://www.vims.edu/cbnerr/'},
    'Delaware NERR':               {'name': 'Delaware National Estuarine Research Reserve',             'state': 'Delaware',       'url': 'https://www.dnrec.delaware.gov/fish-wildlife/dnerr/'},
    'Elkhorn Slough NERR':         {'name': 'Elkhorn Slough National Estuarine Research Reserve',       'state': 'California',     'url': 'https://www.elkhornslough.org/'},
    'Grand Bay NERR':              {'name': 'Grand Bay National Estuarine Research Reserve',            'state': 'Mississippi',    'url': 'https://www.grandbaynerr.org/'},
    'Great Bay NERR':              {'name': 'Great Bay National Estuarine Research Reserve',            'state': 'New Hampshire',  'url': 'https://www.greatbay.org/'},
    'Guana Tolomato Matanzas NERR':{'name': 'Guana Tolomato Matanzas National Estuarine Research Reserve','state': 'Florida',      'url': 'https://gtmnerr.org/'},
    'Hudson River NERR':           {'name': 'Hudson River National Estuarine Research Reserve',         'state': 'New York',       'url': 'https://dec.ny.gov/nature/natural-areas/hudson-river-reserve'},
    'Jacques Cousteau NERR':       {'name': 'Jacques Cousteau National Estuarine Research Reserve',     'state': 'New Jersey',     'url': 'https://jcnerr.org/'},
    'Jobos Bay NERR':              {'name': 'Jobos Bay National Estuarine Research Reserve',            'state': 'Puerto Rico',    'url': 'https://www.drna.pr.gov/nerr-jobos/'},
    'Kachemak Bay NERR':           {'name': 'Kachemak Bay National Estuarine Research Reserve',         'state': 'Alaska',         'url': 'https://accs.uaa.alaska.edu/kbnerr/'},
    'Lake Superior NERR':          {'name': 'Lake Superior National Estuarine Research Reserve',        'state': 'Wisconsin',      'url': 'https://lakesuperiorreserve.org/'},
    'Mission-Aransas NERR':        {'name': 'Mission-Aransas National Estuarine Research Reserve',      'state': 'Texas',          'url': 'https://missionaransas.org/'},
    'Narragansett Bay NERR':       {'name': 'Narragansett Bay National Estuarine Research Reserve',     'state': 'Rhode Island',   'url': 'https://nbnerr.org/'},
    'North Carolina NERR':         {'name': 'North Carolina National Estuarine Research Reserve',       'state': 'North Carolina', 'url': 'https://www.nccoastalreserve.net/'},
    'North Inlet\u2013Winyah Bay NERR': {'name': 'North Inlet–Winyah Bay National Estuarine Research Reserve','state': 'South Carolina','url': 'https://belle.baruch.sc.edu/nerr/'},
    'Old Woman Creek NERR':        {'name': 'Old Woman Creek National Estuarine Research Reserve',      'state': 'Ohio',           'url': 'https://owc.osu.edu/'},
    'Padilla Bay NERR':            {'name': 'Padilla Bay National Estuarine Research Reserve',          'state': 'Washington',     'url': 'https://padillabay.gov/'},
    'Rookery Bay NERR':            {'name': 'Rookery Bay National Estuarine Research Reserve',          'state': 'Florida',        'url': 'https://rookerybay.org/'},
    'San Francisco Bay NERR':      {'name': 'San Francisco Bay National Estuarine Research Reserve',    'state': 'California',     'url': 'https://sfbaynerr.sfsu.edu/'},
    'Sapelo Island NERR':          {'name': 'Sapelo Island National Estuarine Research Reserve',        'state': 'Georgia',        'url': 'https://sapelonerr.org/'},
    'South Slough NERR':           {'name': 'South Slough National Estuarine Research Reserve',         'state': 'Oregon',         'url': 'https://www.oregon.gov/dsl/ss/Pages/default.aspx'},
    'Tijuana River NERR':          {'name': 'Tijuana River National Estuarine Research Reserve',        'state': 'California',     'url': 'https://trnerr.org/'},
    'Waquoit Bay NERR':            {'name': 'Waquoit Bay National Estuarine Research Reserve',          'state': 'Massachusetts',  'url': 'https://www.waquoitbayreserve.org/'},
    'Weeks Bay NERR':              {'name': 'Weeks Bay National Estuarine Research Reserve',            'state': 'Alabama',        'url': 'https://weeksbay.org/'},
    'Wells NERR':                  {'name': 'Wells National Estuarine Research Reserve',                'state': 'Maine',          'url': 'https://www.wellsreserve.org/'},
}


# ── NATIONAL ESTUARY PROGRAM (28) ───────────────────────────────────

NEP = {
    'Coastal Bend Bays and Estuaries Program':               {'state': 'Texas',                  'url': 'https://www.cbbep.org/'},
    'Galveston Bay Estuary Program':                         {'state': 'Texas',                  'url': 'https://www.gbep.texas.gov/'},
    'Santa Monica Bay National Estuary Program':             {'state': 'California',             'url': 'https://www.smbrc.ca.gov/'},
    'San Franciso Estuary Partnership':                      {'name': 'San Francisco Estuary Partnership', 'state': 'California', 'url': 'https://www.sfestuary.org/'},
    'Lower Columbia Estuary Partnership':                    {'state': 'Oregon / Washington',    'url': 'https://www.estuarypartnership.org/'},
    'Puget Sound Partnership':                               {'state': 'Washington',             'url': 'https://www.psp.wa.gov/'},
    'Mobile Bay National Estuary Program':                   {'state': 'Alabama',                'url': 'https://www.mobilebaynep.com/'},
    'Sarasota Bay Estuary Program':                          {'state': 'Florida',                'url': 'https://sarasotabay.org/'},
    'Indian River Lagoon National Estuary Program':          {'state': 'Florida',                'url': 'https://onelagoon.org/'},
    'Tampa Bay Estuary Program':                             {'state': 'Florida',                'url': 'https://tbep.org/'},
    'San Juan Bay Estuary Program':                          {'state': 'Puerto Rico',            'url': 'https://estuario.org/'},
    'Albemarle-Pamlico National Estuary Partnership':        {'state': 'North Carolina / Virginia','url': 'https://apnep.nc.gov/'},
    'Barnegat Bay Partnership':                              {'state': 'New Jersey',             'url': 'https://www.barnegatbaypartnership.org/'},
    'Partnership for the Delaware Estuary':                  {'state': 'DE / NJ / PA',           'url': 'https://delawareestuary.org/'},
    'Delaware Center for the Inland Bays':                   {'state': 'Delaware',               'url': 'https://www.inlandbays.org/'},
    'Maryland Coastal Bays Program':                         {'state': 'Maryland',               'url': 'https://mdcoastalbays.org/'},
    'New York - New Jersey Harbor Estuary Program':          {'state': 'New York / New Jersey',  'url': 'https://www.hudsonriver.org/estuary-program'},
    'Peconic Estuary Program':                               {'state': 'New York',               'url': 'https://www.peconicestuary.org/'},
    'Long Island Sound Study':                               {'state': 'Connecticut / New York', 'url': 'https://longislandsoundstudy.net/'},
    'Massachusetts Bays National Estuary Program':           {'state': 'Massachusetts',          'url': 'https://www.mass.gov/orgs/massachusetts-bays-national-estuary-partnership'},
    'Piscataqua Region Estuaries Partnership':               {'state': 'New Hampshire / Maine',  'url': 'https://prep.unh.edu/'},
    'Casco Bay Estuary Partnership':                         {'state': 'Maine',                  'url': 'https://www.cascobayestuary.org/'},
    'Barataria-Terrebonne National Estuary Program':         {'state': 'Louisiana',              'url': 'https://btnep.org/'},
    'Morro Bay National Estuary Program':                    {'state': 'California',             'url': 'https://www.mbnep.org/'},
    'Tillamook Estuaries Partnership':                       {'state': 'Oregon',                 'url': 'https://www.tbnep.org/'},
    'Buzzards Bay National Estuary Program':                 {'state': 'Massachusetts',          'url': 'https://buzzardsbay.org/'},
    'Narragansett Bay Estuary Program':                      {'state': 'Rhode Island / Massachusetts', 'url': 'https://nbep.org/'},
    'Coastal and Heartland National Estuary Partnership':    {'state': 'Florida',                'url': 'https://www.chnep.org/'},
}


# ── NPS COASTAL UNITS (44) ──────────────────────────────────────────
#
# NPS unit pages live at nps.gov/<four-letter code>. Units are mapped
# by their canonical NPS unit code.

NPS = {
    'Buck Island Reef National Monument':                       {'park_code': 'buis', 'state': 'US Virgin Islands'},
    'Dry Tortugas National Park':                               {'park_code': 'drto', 'state': 'Florida'},
    'Cabrillo National Monument':                               {'park_code': 'cabr', 'state': 'California'},
    'Fort Sumter National Monument':                            {'park_code': 'fosu', 'state': 'South Carolina'},
    'Virgin Islands Coral Reef National Monument':              {'park_code': 'vicr', 'state': 'US Virgin Islands'},
    'Acadia National Park':                                     {'park_code': 'acad', 'state': 'Maine'},
    'Cape Hatteras National Seashore':                          {'park_code': 'caha', 'state': 'North Carolina'},
    'Cape Lookout National Seashore':                           {'park_code': 'calo', 'state': 'North Carolina'},
    'Channel Islands National Park':                            {'park_code': 'chis', 'state': 'California'},
    'Cumberland Island National Seashore':                      {'park_code': 'cuis', 'state': 'Georgia'},
    'Everglades National Park':                                 {'park_code': 'ever', 'state': 'Florida'},
    'Fire Island National Seashore':                            {'park_code': 'fiis', 'state': 'New York'},
    'Gateway National Recreation Area':                         {'park_code': 'gate', 'state': 'New York / New Jersey'},
    'Golden Gate National Recreation Area':                     {'park_code': 'goga', 'state': 'California'},
    'Apostle Islands National Lakeshore':                       {'park_code': 'apis', 'state': 'Wisconsin'},
    'Gulf Islands National Seashore':                           {'park_code': 'guis', 'state': 'Florida / Mississippi'},
    'Isle Royale National Park':                                {'park_code': 'isro', 'state': 'Michigan'},
    'Kalaupapa National Historical Park':                       {'park_code': 'kala', 'state': 'Hawaii'},
    'Kaloko-Honokohau National Historical Park':                {'park_code': 'kaho', 'state': 'Hawaii'},
    'National Park of American Samoa':                          {'park_code': 'npsa', 'state': 'American Samoa'},
    'Olympic National Park':                                    {'park_code': 'olym', 'state': 'Washington'},
    'Padre Island National Seashore':                           {'park_code': 'pais', 'state': 'Texas'},
    'Pictured Rocks National Lakeshore':                        {'park_code': 'piro', 'state': 'Michigan'},
    'Assateague Island National Seashore':                      {'park_code': 'asis', 'state': 'Maryland / Virginia'},
    'Point Reyes National Seashore':                            {'park_code': 'pore', 'state': 'California'},
    'Redwood National Park':                                    {'park_code': 'redw', 'state': 'California'},
    'Salt River Bay National Historic Park and Ecological Preserve': {'park_code': 'sari','state':'US Virgin Islands'},
    'Sleeping Bear Dunes National Lakeshore':                   {'park_code': 'slbe', 'state': 'Michigan'},
    'Timucuan Ecological & Historic Preserve':                  {'park_code': 'timu', 'state': 'Florida'},
    'Virgin Islands National Park':                             {'park_code': 'viis', 'state': 'US Virgin Islands'},
    'War in the Pacific National Historical Park':              {'park_code': 'wapa', 'state': 'Guam'},
    'Puukohola Heiau National Historic Site':                   {'park_code': 'puhe', 'state': 'Hawaii'},
    'Biscayne National Park':                                   {'park_code': 'bisc', 'state': 'Florida'},
    'San Juan Island National Historical Park':                 {'park_code': 'sajh', 'state': 'Washington'},
    'Canaveral National Seashore':                              {'park_code': 'cana', 'state': 'Florida'},
    'Cape Cod National Seashore':                               {'park_code': 'caco', 'state': 'Massachusetts'},
    'Fort Pulaski National Monument':                           {'park_code': 'fopu', 'state': 'Georgia'},
    "Ebey's Landing National Historical Reserve":               {'park_code': 'ebla', 'state': 'Washington'},
    'Glacier Bay National Park & Preserve':                     {'park_code': 'glba', 'state': 'Alaska'},
    'Indiana Dunes National Lakeshore':                         {'park_code': 'indu', 'state': 'Indiana'},
    'Sitka National Historical Park':                           {'park_code': 'sitk', 'state': 'Alaska'},
    'Bering Land Bridge National Park and Preserve':            {'park_code': 'bela', 'state': 'Alaska'},
    'Cape Krusenstern National Monument':                       {'park_code': 'cakr', 'state': 'Alaska'},
    'Jean Lafitte National Historical Park and Preserve, Barataria Preserve': {'park_code': 'jela','state':'Louisiana'},
}


# ── RUN ────────────────────────────────────────────────────────────

def normalize_properties(j, overlay_slug):
    """
    Final normalization pass — runs after the per-table enrichment so the
    output is uniform across every overlay file.

      * `name` is the canonical long form (never an acronym).
      * `acronym` is always populated when one exists.
      * `short` is dropped — it was the legacy pre-rename label and is now
        redundant with `acronym`/`name`.
      * `network_slug` is added so regions can join to networks.
    """
    # Mapping from the per-file `network` tag to the vocabulary slug.
    NETWORK_SLUG = {
        'NMS':             'nms',
        'Marine-Monument': 'marine-monument',
        'NERRS':           'nerrs',
        'NEP':             'nep',
        'NEON':            'neon',
        'NPS-Coastal':     'nps-coastal',
        'EPA-Region':      'epa-region',
    }
    # Per-overlay "kind" — keeps the polygon type first-class, independent
    # of the network vocabulary slug.
    KIND = {
        'marine-sanctuaries.geojson': 'sanctuary',
        'marine-monuments.geojson':   'monument',
        'nerr-reserves.geojson':      'nerr-reserve',
        'nep-programs.geojson':       'nep-program',
        'nps-coastal.geojson':        'nps-unit',
        'neon-domains.geojson':       'neon-domain',
        'epa-regions.geojson':        'epa-region',
    }
    kind = KIND.get(overlay_slug, 'region')

    for feat in j['features']:
        p = feat.setdefault('properties', {})

        # Infer acronym if missing.
        if not p.get('acronym'):
            if p.get('park_code'):
                # NPS four-letter code — uppercase it.
                p['acronym'] = str(p['park_code']).upper()
            elif p.get('domain_id'):
                p['acronym'] = f"D{int(p['domain_id']):02d}"
            elif p.get('region'):
                # "Region 1" -> "R1"
                m = str(p['region']).strip().split()
                if len(m) == 2 and m[0].lower() == 'region' and m[1].isdigit():
                    p['acronym'] = f'R{m[1]}'
            elif p.get('short') and 2 <= len(str(p['short'])) <= 10 \
                    and str(p['short']).isupper():
                # Legacy uppercase abbreviation hiding in `short`.
                p['acronym'] = p['short']

        # Drop the legacy `short` field — it's redundant now.
        if 'short' in p:
            del p['short']

        # Always record the network slug so the DB can FK it.
        if p.get('network') and 'network_slug' not in p:
            slug = NETWORK_SLUG.get(p['network'])
            if slug:
                p['network_slug'] = slug

        # Record the region kind.
        p.setdefault('kind', kind)

    return j


def run():
    # 1. Merge same-name fragments in NERR + NEON (sanctuaries/monuments
    # were merged in an earlier commit).
    for fn in ('nerr-reserves.geojson', 'neon-domains.geojson'):
        p = os.path.join(OV, fn)
        j = merge_by_name(load(p))
        save(p, j)
        print(f'merged fragments in {fn}: {len(j["features"])} features')

    # 2. Enrich each overlay.
    specs = [
        ('marine-sanctuaries.geojson', NMS,       'name'),
        ('marine-monuments.geojson',   MONUMENTS, 'name'),
        ('neon-domains.geojson',       NEON,      'name'),
        ('epa-regions.geojson',        EPA,       'name'),
        ('nerr-reserves.geojson',      NERR,      'name'),
        ('nep-programs.geojson',       NEP,       'name'),
        ('nps-coastal.geojson',        NPS,       'name'),
    ]
    for fn, table, key in specs:
        p = os.path.join(OV, fn)
        updated, total = enrich(p, table, key)
        print(f'enriched {fn}: {updated}/{total} features touched')

    # 3. Post-process NEON — fill the domain url derived from domain_id.
    p = os.path.join(OV, 'neon-domains.geojson')
    j = load(p)
    for f in j['features']:
        pr = f.get('properties') or {}
        did = pr.get('domain_id')
        if did and not pr.get('url'):
            pr['url'] = neon_url(did)
    save(p, j)

    # 4. Post-process NPS — derive url from park_code.
    p = os.path.join(OV, 'nps-coastal.geojson')
    j = load(p)
    for f in j['features']:
        pr = f.get('properties') or {}
        pc = pr.get('park_code')
        if pc and not pr.get('url'):
            pr['url'] = f'https://www.nps.gov/{pc}/'
    save(p, j)

    # 5. Name normalization / acronym inference / drop legacy `short`.
    for fn in ('marine-sanctuaries.geojson', 'marine-monuments.geojson',
               'nerr-reserves.geojson', 'nep-programs.geojson',
               'nps-coastal.geojson', 'neon-domains.geojson',
               'epa-regions.geojson'):
        p = os.path.join(OV, fn)
        j = load(p)
        normalize_properties(j, fn)
        save(p, j)
        print(f'normalized {fn}')

    print('done.')

if __name__ == '__main__':
    run()
