# Knowledge map

The **Network** tab (`#/network`) draws the catalogue as a map of research areas. Each polygon is one research area. Inside it, smaller cells are the institutions (facilities) that work in that area, and dots are the researchers attached to them. This page describes how big each region is, what the first view shows, and when names appear. The code is `src/views/network.js`.

As of 2026-10-25 the map's data holds 47 regions (the active research areas that carry any weight; 29 more carry none and are left out), with 419 institutions and 1,256 researchers assigned to them. Which region each institution and researcher belongs to was last recomputed on 2026-10-25, after three ARS rows were merged into their survivors: "Fort Keogh Livestock and Range Research Laboratory (USDA-ARS historic)" into Fort Keogh, "Northern Great Plains Research Laboratory (Mandan)" into Northern Plains LTAR and "USDA-ARS Grazinglands Research Laboratory (El Reno)" into Southern Plains LTAR. The three survivors kept their regions and no researcher changed region; Jean L. Steiner and Patrick J. Starks lost the research areas they had inherited from the El Reno row. No region was added or removed. Before that, also on 2026-10-25, three rows were merged into the Reynolds Creek and Walnut Gulch LTAR sites (their two "(USDA-ARS historic)" rows and a "Great Basin LTAR" row placed at Reno) and two records of one researcher (Fred Pierson) were merged. Walnut Gulch moved from *Soil science* to *Hydrology*, two researchers whose Reno LTAR roles were dropped moved to another region, and David A. Woolhiser, whose only facility role was dropped, no longer has one. No region was added or removed. Before that, also on 2026-10-25, the Connecticut NERR and the Coastal and Heartland National Estuary Partnership were added with their 20 staff; both fall under *Coastal processes*. The recompute before that came after two "(USDA-ARS historic)" rows were merged into their LTAR sites (Jornada and Central Plains Experimental Range) and 24 duplicate funders were merged. The same recompute dropped facility-inherited research areas that no facility link still carries (47 rows for 22 people, among them two Jornada co-PIs the merge left without a facility role); with no area left, 7 of those people no longer have a region. No region was added or removed. Earlier the same day, two MarineGEO site rows were merged into the Smithsonian stations that host them. That merge removed the *Mangroves* region: the "SERC, GCREW" MarineGEO row was one of its three facilities, and with two left it fell below the three-facility minimum and folded into *Marine ecosystems*. The recompute before that, on 2026-10-24, followed the merge of eight duplicate LTER site rows into their sites (`scripts/merge_facilities.py`); the region assignments before that came from the second OpenAlex publication pass (2026-10-23), which completed OpenAlex matching for everyone with a usable ORCID or OpenAlex id. The LTER merge removed the *Tidal wetlands* region: the duplicate rows had carried it, and the merged FCE and GCE sites fall under *Estuaries and wetlands*.

## What sizes a region

A region's area is proportional to a **data-and-people weight**:

```
weight = organisations
       + 3.0 × organisations whose data sits in an authoritative archive
       + 1.5 × addressable data products
       + 0.35 × researchers anchored in the region
```

It is not the raw facility count. As of 2026-10-25, 150 of the 440 catalogued facilities (about a third) are place-type monitoring installations: protected areas (18), flux towers (27), streamgage networks (39), experimental forests and ranges (33), LTAR sites (18), atmospheric baseline observatories (10) and glacier-monitoring sites (5). A raw count measures how much of the catalogue falls in an area, not how much observatory capacity it has.

Protected areas are never counted as organisations. They stay in the catalogue, and the off-by-default **Protected areas (context)** layer draws them as one chip per region. Their data products and people still count toward the region's weight.

The sidebar lists regions by the same weight. Its three numbers are organisations · datasets · people.

## Layout

The layout follows KMap (Hossain, Moradi, Mondal & Kobourov, *Map Visualizations for Graphs with Group Restrictions*, Graphics Interface 2025):

1. **Supergraph.** Each research area becomes a square sized by √weight. A force layout places the squares, pulling areas that share facilities or co-authors closer together.
2. **Subgraph.** Inside each square, a small force layout places the area's institutions and researchers.
3. **Polygons.** A Voronoi diagram over all the nodes is computed, and each area's cells are merged into one polygon. Institutions get their own sub-polygons inside it.

The layout is shaped to the stage. On a wide screen the squares are pulled toward the centre harder vertically than sideways, so the map comes out about as wide as the stage instead of round. The layout is computed once, when the tab first opens. Resizing the window refits it but does not recompute it. **Recompute layout** runs it again for the current stage shape. Nothing in the layout is random (its jitter is seeded from the area ids, and d3-force seeds its own), so the same data on the same stage shape gives the same map.

## Viewport

- **First view: the whole map.** The map opens framed so that every polygon fits on the stage with a 24 px margin. Nothing is cropped.
- **Zoom limits are relative to that first view.** Zooming out stops at the first view. Zooming in goes to 24×, or further if the stage needs it: the limit is raised to whatever zoom frames the smallest region in the stage. On a large monitor 24× is usually enough. On a phone, 24× can leave the smallest region less than half the stage wide, so the limit is higher there. Because the limits are tied to the fit, "4×" means the same on a phone and on a large monitor.
- **The map cannot be lost off-screen.** You can pan at most half the map's size past any edge.
- **Resizing.** If you have not zoomed or panned, a resize refits the whole map. If you have, the point at the centre of the stage stays there and the zoom level is kept. Labels are recomputed either way.
- **Going to a region.** Clicking a region, or its row in the sidebar, zooms to fit that region with a 48 px margin. The region is then **pinned**: its outline is heavier, its fill darker, its sidebar row marked, and its name is always shown.
- **Back to everything.** **Reset zoom**, or a double-click on the map, returns to the first view and unpins the region.

## When names appear

Names are not tied to a zoom level. A name shows when the thing it names is large enough **on screen** to hold it. That test gives the same result on every display. Every label is drawn at a fixed screen size: zooming moves a label but does not scale its text. No label is ever drawn smaller than 9.8 px, the smallest text the site's tooltips already use. A label that does not fit at its size is hidden, not shrunk.

| Label | Shown when | Size |
|---|---|---|
| Region name | The whole name lies inside the polygon: its top, middle and bottom rows are each inside the outline. The map tries one line first, then two lines, then a smaller 11 px size. The three heaviest regions also get a 10 px try, so a long single word such as "Biogeochemistry" is still named on a phone. If none fits, the name is hidden; the sidebar and the tooltip still give it. | 12–18 px, larger for heavier regions |
| Region name, pinned | Always. | as above |
| Region name, "inside" | When the polygon covers ¾ or more of the stage, you are inside the region and its pole is usually off-screen. The name then moves to the topmost row of the stage where it fits inside the outline and clears the other labels. A region covering a fifth of the stage or more gets the same placement if no spot near its pole works. Without this, a deep zoom often showed no region name at all. | as above |
| Institution | Its sub-polygon is at least 40 px across in both directions, and at least 0.8× the width of its name. | 10.5–14 px |
| Researcher | Their institution's sub-polygon is at least 120 px across. A researcher with no institution drawn in that region needs the region itself to be 480 px across. At most 14 researchers per region are eligible, in order of importance (see below). | 10–13.5 px |
| Registry researcher | Only in the *Researchers & co-authorship* layer, for the site you shift-clicked: that site's sub-polygon is at least 120 px across. | 10–12.5 px |
| Protected-area chips, "N no site" captions | The region is at least 60 px across. | 10–12 px |

### Labels never overlap

After deciding which labels are eligible, the map places them one at a time in priority order:

1. the pinned region
2. other regions, heaviest first
3. context chips and captions
4. institutions
5. registry researchers
6. researchers

A label is skipped if its box (with a 3 px pad) would touch a label already placed, or would run off the stage. This is a single pass across all label kinds, done in screen pixels, so a region name always wins over the institution and researcher labels beneath it.

The pass runs at most once per animation frame while you zoom or pan, and once more when the gesture ends. It reads cached text widths and checks collisions against a grid, so it does not force the browser to re-measure the page.

### Label text and placement

- **Region names** start at the polygon's *pole of inaccessibility*: the interior point farthest from the edge. This is not the average of the vertices, which can fall near a boundary on an irregular shape. If the name does not fit there, the map slides it sideways within the outline, then tries positions a little above and below. Region names carry a heavier halo than other labels, because they sit over cells and dots.
- **Region names keep off institutions.** Once a region is large on screen (150 px or more across), its name avoids its institutions' dots, and it always avoids the space above the dot of any institution large enough to be named. Without this, a region holding a single institution put its own name on that institution's dot, because the two share a centre, and hid the institution's name at every zoom. If no clear position exists, the name goes in the first position that fits.
- **A large region partly off the stage is still named.** When the pole is outside the stage, or within 40 px of its edge, the map also tries the centre of the region's on-stage part, and the pole moved into that part.
- **Researcher importance** ranks researchers for naming and sets the size of their dot and name. It combines their publication count, their number of co-authors, and the recorded funding of the institutions they work at; the tooltip shows whichever of the three are non-zero. Publication and co-author counts come from OpenAlex, and as of 2026-10-25 only 560 of the 1,329 people in the catalogue have an OpenAlex record (people without an ORCID or OpenAlex id cannot be matched), so most researchers have none. Of the 1,256 researchers on the map, 556 have publications and 525 have co-authors. Many funding figures are recalled by research agents, not taken from award records; the exceptions are the four LTREB award series, fetched from the NSF Award API, and the National Estuarine Research Reserves' and National Estuary Programs' NOAA and EPA awards, fetched from USAspending.gov. A facility's funding counts once per researcher, however many roles they hold there. Treat importance as a rough ordering.
- **Institution names.** An acronym is used as the name only when no other institution has the same one. An acronym shared by several sites (today only CPER) is replaced by the place name, and so is a missing acronym: "Wells National Estuarine Research Reserve", which has none, is labelled **Wells**. Reserves and estuary programs that state their own acronym on their homepage use it (GTMNERR, TBEP). Names sit just above their dot, so they do not cover it. The tooltip always gives the full name.

## Controls

| Control | Effect |
|---|---|
| **Facilities** / **People** | Show or hide institution and researcher marks. These switches also decide which cross-area edges a click can reveal. |
| **Researchers & co-authorship** | Turns on the researcher registry. Amber ribbons are co-publication between catalogued sites. Shift-clicking a site opens its roster. Clicking a dashed "no site" badge lists that region's researchers placed by research area alone. Clicking a registry researcher opens their People card, or their ORCID or OpenAlex profile. |
| **Protected areas (context)** | One aggregate chip per region for the protected areas catalogued there. |
| **Recompute layout** | Runs the layout again for the current stage. |
| Click a region or a sidebar row | Zooms to the region and pins it. On a phone, tapping a sidebar row also folds the list and scrolls the map into view. |
| Click an institution or researcher | Reveals that node's cross-area edges. Click it again, click the background, or press **Esc** to hide them. |
| Shift-click | On an institution, opens its homepage, or its researcher roster when *Researchers & co-authorship* is on. On a researcher, opens their card on the **People** tab. |
| **Reset zoom** / double-click | Shows the whole map again. |

On a phone (760 px wide or less), the subtitle is hidden and the toggles wrap. The status line shows two lines; tap it to see the rest. The map gets 65% of the screen height. The sidebar moves below the map and collapses to a **Research areas** heading you can tap to open. Together these keep the whole map above the fold on a 390×844 screen.

## Loading

The map needs the in-browser database (DuckDB-Wasm). On a slow first load the database can take longer to start than the site's 30-second start-up timeout. The map does not give up when that timeout fires. It shows **Waiting for the database to start…** and checks again every half second for up to three minutes, then draws itself. If the database still has not started after three minutes, the status line says so; **Recompute layout** tries again without reloading the page.

## Not implemented

The browser does not implement the KMap paper's PCL boundary refinement, custom force terms, or canvas rendering in a Web Worker. The pipeline script `scripts/build_mvg_layout.py` computes both a KMap and a PCL layout offline and writes them to `mvg_node_layout`, `mvg_area_polygons`, `scholar_area_assignments` and `mvg_layout_metrics`. You can query those tables in the SQL tab, but the Network tab does not read them; it computes its own layout.
