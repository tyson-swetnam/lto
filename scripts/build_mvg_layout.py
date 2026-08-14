#!/usr/bin/env python3
"""Precompute MVG (map visualization of a graph with group restrictions)
layouts for the LTO knowledge map (U.S. Long-Term Observatories,
github.com/tyson-swetnam/lto).

Implements KMap and PCL from Hossain, Moradi, Mondal & Kobourov, "Map
Visualizations for Graphs with Group Restrictions", Graphics Interface 2025
(see scripts/mvg.py), and writes four tables to db/parquet/ and
public/parquet/:

  mvg_node_layout.parquet          per-node KMap and PCL coordinates
  mvg_area_polygons.parquet        per-area polygon WKT + area/size shares
  scholar_area_assignments.parquet scholar -> research area (+confidence)
  mvg_layout_metrics.parquet       M1-M7 quality metrics for both methods

The front end recomputes a KMap-equivalent layout in src/views/network.js at
page load; these tables let it read a precomputed PCL layout instead
(network.js Phase 3, "PCL refinement", is unbuilt).

Node population (529 nodes / 2,711 edges / 21 root areas as of the
116-identity registry, before the OpenAlex harvest lands):
  site personnel   people.parquet with an area in person_primary_groups
                   (cohort "personnel"; a person_registry row that is
                   is_scholar and not is_site_personnel flips the cohort
                   to "scholar" without moving the node)
  scholars         person_registry rows with is_scholar = true that are
                   not already placed via person_primary_groups
                   (cohort "scholar"; currently 0 rows -- the pipeline
                   degrades to a personnel-only graph until the harvest)

Edges: internal co-authorship (authorship.parquet) plus registry
collaborations (registry_collaborations.parquet, canonical ids resolved to
either node kind; currently 0 rows, which is fine -- co-authorship alone
carries the layout).

This script reads the committed parquet catalog only and never opens
db/lto.duckdb, so it is safe to run while a harvest holds the DB write
lock. It needs scipy + shapely at runtime (see scripts/mvg.py); scipy is
checked up front because it is not part of the base requirements.

Usage:
  python scripts/build_mvg_layout.py                  # both output dirs
  python scripts/build_mvg_layout.py --k-ext 12       # sparser graph

PROVENANCE WARNING. Research areas for scholars are INFERRED, not curated:
no curated scholar->area table exists in the LTO catalog. A scholar whose
person_id already sits in person_primary_groups inherits that computed
group (its score is reported as the confidence, method
"person_primary_groups"). Every other scholar's area is a majority vote
over the OpenAlex topic phrases on their publications
(authorship x publication_topics) mapped onto root research_areas via
db/derived/topic_area_map.json (method "topic_vote"; confidence is the
winning share of the phrases). If that map file does not exist, a
MECHANICAL STUB is derived here -- case-insensitive exact and unambiguous
substring matches between topic phrases and research-area labels -- and
written to the same path for curator review. The confidence column ships
with the table: treat low values as provisional pending curator review,
and do not present these in the UI as curated assignments.
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rollup(area_id, parent):
    seen = set()
    while True:
        p = parent.get(area_id)
        if p is None or (isinstance(p, float) and p != p) or not p or p in seen:
            return area_id
        seen.add(area_id)
        area_id = p


def _derive_topic_map(con, P, id2lab, parent):
    """Mechanical topic->area stub (see PROVENANCE WARNING): map each
    distinct publication_topics phrase onto a ROOT research-area label by
    case-insensitive exact match, else by substring containment kept only
    when it is unambiguous (exactly one candidate area)."""
    concepts = [r[0] for r in con.execute(
        f"select distinct concept_name from '{P('publication_topics')}' "
        f"where concept_name is not null").fetchall()]
    root_of = {}
    for aid, lab in id2lab.items():
        root_lab = id2lab.get(_rollup(aid, parent))
        if lab and root_lab:
            root_of[lab.lower()] = root_lab
    tmap = {}
    for c in concepts:
        cl = c.strip().lower()
        if not cl:
            continue
        if cl in root_of:
            tmap[c] = root_of[cl]
            continue
        hits = {root for lab, root in root_of.items()
                if lab in cl or cl in lab}
        if len(hits) == 1:
            tmap[c] = hits.pop()
    return tmap


def load_graph(parquet_dir, topic_map_path):
    """Assemble the combined node/edge/label lists from the parquet catalog.

    Returns (recs, uids, labels, edges, sch_rows) where recs is a list of
    node dicts, edges is index pairs into uids, and sch_rows is one row per
    is_scholar registry member for scholar_area_assignments."""
    import duckdb
    con = duckdb.connect()  # in-memory; reads parquet, never db/lto.duckdb
    P = lambda t: os.path.join(parquet_dir, t + ".parquet")

    areas = con.execute(
        f"select area_id, label, parent_id from '{P('research_areas')}'").fetchall()
    id2lab = {a: l for a, l, _ in areas}
    parent = {a: p for a, _, p in areas}

    names = dict(con.execute(
        f"select person_id, name from '{P('people')}'").fetchall())
    pg = con.execute(
        f"select person_id, primary_area_id, score from '{P('person_primary_groups')}' "
        f"where primary_area_id is not null").fetchall()
    area_of, ppg_score = {}, {}
    for pid, aid, score in pg:
        lab = id2lab.get(_rollup(aid, parent))
        if lab:
            area_of[pid] = lab
            ppg_score[pid] = float(score) if score is not None else None

    reg = con.execute(
        f"select canonical_id, display_name, person_id, is_site_personnel, "
        f"is_scholar, h_index from '{P('person_registry')}'").fetchall()
    scholars = [r for r in reg if r[4]]
    # A registry row that is scholar-only flips the cohort of its people-
    # directory node; is_site_personnel wins when both flags are set.
    scholar_only = {pid for _, _, pid, isp, iss, _ in reg if pid and iss and not isp}

    if os.path.exists(topic_map_path):
        with open(topic_map_path) as fh:
            topic2area = json.load(fh)
    else:
        topic2area = _derive_topic_map(con, P, id2lab, parent)
        os.makedirs(os.path.dirname(topic_map_path) or ".", exist_ok=True)
        with open(topic_map_path, "w") as fh:
            json.dump(topic2area, fh, indent=1, sort_keys=True)
        print(f"[topic-map] no curated map found; wrote mechanical stub "
              f"({len(topic2area)} phrases) -> {topic_map_path} "
              f"(NEEDS CURATOR REVIEW)")

    topics = collections.defaultdict(list)
    for pid, phrase in con.execute(
            f"""select a.person_id, pt.concept_name
                from '{P('authorship')}' a
                join '{P('publication_topics')}' pt
                  on a.publication_id = pt.publication_id
                where a.person_id is not null
                  and pt.concept_name is not null""").fetchall():
        topics[pid].append(phrase)

    def vote(phrases):
        picks = [topic2area.get(p.strip()) for p in phrases if p.strip()]
        picks = [p for p in picks if p]
        if not picks:
            return None, 0.0
        top, n = collections.Counter(picks).most_common(1)[0]
        return top, n / len([p for p in phrases if p.strip()])

    recs = []
    for pid, area in area_of.items():
        recs.append({"uid": f"p:{pid}", "name": names.get(pid) or "",
                     "area": area,
                     "cohort": "scholar" if pid in scholar_only else "personnel",
                     "src": pid})

    sch_rows = []
    for cid, dname, pid, _isp, _iss, h in scholars:
        if pid and pid in area_of:
            # Already placed as a p: node via person_primary_groups.
            sch_rows.append((cid, dname, area_of[pid], ppg_score.get(pid),
                             h, "person_primary_groups"))
            continue
        area, conf = vote(topics.get(pid, []) if pid else [])
        sch_rows.append((cid, dname, area, conf, h,
                         "topic_vote" if area else None))
        if area:
            recs.append({"uid": f"s:{cid}", "name": dname or "", "area": area,
                         "cohort": "scholar", "src": cid})

    by_uid = {}
    for r in recs:
        by_uid.setdefault(r["uid"], r)
    recs = [r for r in by_uid.values() if r["area"]]

    uid_person = {r["src"]: r["uid"] for r in recs if r["uid"].startswith("p:")}
    uid_canon = {r["src"]: r["uid"] for r in recs if r["uid"].startswith("s:")}
    canon2uid = {}
    for cid, _dn, pid, _isp, _iss, _h in reg:
        u = uid_canon.get(cid) or (uid_person.get(pid) if pid else None)
        if u:
            canon2uid[cid] = u

    E = set()
    for a, b in con.execute(
            f"""with a as (select person_id, publication_id from '{P('authorship')}'
                           where person_id is not null)
                select x.person_id pa, y.person_id pb from a x join a y
                 on x.publication_id = y.publication_id and x.person_id < y.person_id
                group by 1, 2""").fetchall():
        if a in uid_person and b in uid_person:
            E.add(tuple(sorted((uid_person[a], uid_person[b]))))
    for a, b in con.execute(
            f"select canonical_id_a, canonical_id_b "
            f"from '{P('registry_collaborations')}'").fetchall():
        ua, ub = canon2uid.get(a), canon2uid.get(b)
        if ua and ub and ua != ub:
            E.add(tuple(sorted((ua, ub))))

    uids = sorted(r["uid"] for r in recs)
    iu = {u: i for i, u in enumerate(uids)}
    area_by_uid = {r["uid"]: r["area"] for r in recs}
    labels = [area_by_uid[u] for u in uids]
    edges = sorted({(iu[a], iu[b]) for a, b in E
                    if a in iu and b in iu and iu[a] != iu[b]})
    return recs, uids, labels, edges, sch_rows


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parquet-dir", default=os.path.join(ROOT, "db", "parquet"))
    ap.add_argument("--out-dir", action="append", default=None)
    ap.add_argument("--topic-map",
                    default=os.path.join(ROOT, "db", "derived", "topic_area_map.json"))
    ap.add_argument("--k-ext", type=float, default=40.0,
                    help="PCL external gravity. TUNE PER GRAPH: the optimum "
                         "tracks the between-group edge fraction, printed at "
                         "startup (upstream tuning: 12 at 54%% between-group, "
                         "40 at 68%%; the current LTO graph sits near 71%%).")
    ap.add_argument("--iterations", type=int, default=250)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    out_dirs = args.out_dir or [os.path.join(ROOT, "db", "parquet"),
                                os.path.join(ROOT, "public", "parquet")]

    try:
        import scipy  # noqa: F401  (mvg.py lazily imports scipy.spatial/sparse)
        import shapely  # noqa: F401
    except ImportError as exc:
        print(f"[error] missing runtime dependency: {exc.name}. "
              f"scripts/mvg.py needs scipy and shapely; "
              f"pip install scipy shapely", file=sys.stderr)
        return 2

    import numpy as np
    import polars as pl
    import mvg

    recs, uids, labels, edges, sch_rows = load_graph(args.parquet_dir, args.topic_map)
    if not uids:
        print("[error] empty graph: no people with a primary research area "
              "in person_primary_groups and no assignable scholars",
              file=sys.stderr)
        return 2
    betw_frac = (sum(1 for u, v in edges if labels[u] != labels[v]) / len(edges)
                 if edges else 0.0)
    n_sch = sum(1 for r in sch_rows if r[2])
    print(f"graph: {len(uids)} nodes, {len(edges)} edges, "
          f"{len(set(labels))} areas, {betw_frac:.0%} between-group; "
          f"scholars assigned {n_sch}/{len(sch_rows)}")

    km = mvg.mvg_kmap(labels, edges, seed=args.seed)
    pcl = mvg.mvg_pcl(km["points"], labels, edges, km["polygons"],
                      iterations=args.iterations, k_ext=args.k_ext, seed=args.seed)

    deg = np.zeros(len(uids))
    for u, v in edges:
        deg[u] += 1
        deg[v] += 1
    name_of = {r["uid"]: r["name"] for r in recs}
    src_of = {r["uid"]: r["src"] for r in recs}
    coh_of = {r["uid"]: r["cohort"] for r in recs}
    layout = pl.DataFrame({
        "node_uid": uids, "name": [name_of[u] for u in uids],
        "source_id": [src_of[u] for u in uids],
        "cohort": [coh_of[u] for u in uids],
        "area_label": labels, "degree": deg.astype(np.int64),
        "connected": deg > 0,
        "kmap_x": km["points"][:, 0], "kmap_y": km["points"][:, 1],
        "pcl_x": pcl[:, 0], "pcl_y": pcl[:, 1],
    })

    sizes = collections.Counter(labels)
    total = sum(p.area for p in km["polygons"].values())
    polys = pl.DataFrame([{
        "research_area": str(g), "n_nodes": int(sizes[g]),
        "n_personnel": int(sum(1 for i, l in enumerate(labels)
                               if l == g and coh_of[uids[i]] == "personnel")),
        "n_scholar": int(sum(1 for i, l in enumerate(labels)
                             if l == g and coh_of[uids[i]] == "scholar")),
        "polygon_area": round(km["polygons"][g].area, 6),
        "area_share": round(km["polygons"][g].area / total, 4),
        "size_share": round(sizes[g] / len(labels), 4),
        "wkt": km["polygons"][g].wkt,
    } for g in sorted(km["polygons"], key=str)])

    within = [(u, v) for u, v in edges if labels[u] == labels[v]]
    betw = [(u, v) for u, v in edges if labels[u] != labels[v]]
    rows = []
    for nm, pts in [("KMap", km["points"]), (f"PCL (k_ext={args.k_ext:g})", pcl)]:
        m = mvg.mvg_metrics(pts, labels, edges, km["polygons"])
        wc = mvg.mvg_crossing_fraction(pts, within) * len(within) ** 2
        bc = mvg.mvg_crossing_fraction(pts, betw) * len(betw) ** 2
        rows.append({"method": nm, "nodes": len(labels), "edges": len(edges),
                     "groups": len(sizes),
                     **{k: round(m[k], 4) for k in mvg.MVG_METRICS},
                     "within_crossings": int(wc), "between_crossings": int(bc),
                     "total_crossings": int(wc + bc)})
        print(nm, {k: round(m[k], 3) for k in mvg.MVG_METRICS})
    metrics = pl.DataFrame(rows)

    # One row per is_scholar registry member, assigned or not; see the
    # PROVENANCE WARNING in the module docstring before surfacing this.
    sch = pl.DataFrame(
        [(cid, nm2, area, float(conf) if conf is not None else None,
          int(h) if h is not None else None, method)
         for cid, nm2, area, conf, h, method in sch_rows],
        schema={"canonical_id": pl.String, "name": pl.String,
                "assigned_area": pl.String,
                "topic_vote_confidence": pl.Float64,
                "h_index": pl.Int64, "method": pl.String},
        orient="row")

    for d in out_dirs:
        os.makedirs(d, exist_ok=True)
        layout.write_parquet(os.path.join(d, "mvg_node_layout.parquet"))
        polys.write_parquet(os.path.join(d, "mvg_area_polygons.parquet"))
        sch.write_parquet(os.path.join(d, "scholar_area_assignments.parquet"))
        metrics.write_parquet(os.path.join(d, "mvg_layout_metrics.parquet"))
        print("wrote layout tables ->", os.path.abspath(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
