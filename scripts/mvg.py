"""KMap / PCL map-visualization layouts for graphs with group restrictions.

Vendored from the mvg-knowledge-map implementation of Hossain, Moradi,
Mondal & Kobourov, "Map Visualizations for Graphs with Group Restrictions",
Graphics Interface 2025. Used by scripts/build_mvg_layout.py.

Departures from the printed paper (all deliberate, see module docstring
of the original): external gravity pulls TOWARD the neighbouring polygon
center (Eq. 3 as printed points away, contradicting Fig. 7); alpha is
sqrt(area/n) so its units are length; scale-and-fit is per-axis on the
88th percentile so force-layout outliers do not squash a subgraph.
"""
import math
import numpy as np

MVG_SEED = 7
MVG_METRICS = ("M1", "M2", "M3", "M4", "M5", "M6", "M7")


def mvg_force_layout(n, edges, iterations=300, seed=None, scale=1.0):
    """Fruchterman-Reingold layout in numpy. Returns (n, 2) positions
    centered on the origin and scaled to fit a `scale`-wide box.
    O(n^2) per iteration -- fine to a few thousand nodes."""
    if seed is None:
        seed = MVG_SEED
    rng = np.random.default_rng(seed)
    if n <= 1:
        return np.zeros((max(n, 0), 2))
    pos = rng.normal(0.0, 0.3, (n, 2))
    E = np.asarray(list(edges), dtype=int).reshape(-1, 2)
    k = math.sqrt(1.0 / n)
    temp = 0.1
    for _ in range(iterations):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.linalg.norm(delta, axis=-1)
        np.fill_diagonal(dist, np.inf)
        dist = np.maximum(dist, 1e-9)
        disp = ((k * k) / (dist ** 2))[:, :, None] * delta
        disp = disp.sum(axis=1)
        if E.size:
            d = pos[E[:, 0]] - pos[E[:, 1]]
            dl = np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
            att = d * (dl / k)
            np.add.at(disp, E[:, 0], -att)
            np.add.at(disp, E[:, 1], att)
        dl = np.maximum(np.linalg.norm(disp, axis=1, keepdims=True), 1e-9)
        pos = pos + disp / dl * np.minimum(dl, temp)
        temp *= 0.985
    pos = pos - pos.mean(axis=0)
    span = np.abs(pos).max()
    if span > 0:
        pos = pos / span * (scale / 2.0)
    return pos


def mvg_group_network(labels, edges):
    """Weighted group-group supergraph (KMap step 1).
    Returns (groups, weights, super_edges) where super_edges is a list of
    (i, j, weight) index triples into `groups`."""
    labels = list(labels)
    groups = sorted(set(labels), key=lambda g: (str(type(g)), str(g)))
    index = {g: i for i, g in enumerate(groups)}
    weights = np.zeros(len(groups), dtype=float)
    for g in labels:
        weights[index[g]] += 1.0
    acc = {}
    for u, v in edges:
        a, b = index[labels[u]], index[labels[v]]
        if a == b:
            continue
        key = (min(a, b), max(a, b))
        acc[key] = acc.get(key, 0.0) + 1.0
    super_edges = [(a, b, w) for (a, b), w in acc.items()]
    return groups, weights, super_edges


def mvg_pack_squares(weights, super_edges, iterations=400, seed=None,
                     pad=1.06, spread=0.8):
    """Embed the supergraph as non-overlapping axis-aligned squares whose
    side lengths go as sqrt(group weight) (KMap step 1).
    Returns (centers (k,2), sides (k,))."""
    if seed is None:
        seed = MVG_SEED
    weights = np.asarray(weights, dtype=float)
    k = len(weights)
    sides = np.sqrt(np.maximum(weights, 1.0))
    sides = sides / sides.max()
    centers = mvg_force_layout(k, [(a, b) for a, b, _ in super_edges],
                               iterations=iterations, seed=seed, scale=1.0)
    centers = centers * math.sqrt((sides ** 2).sum()) * spread
    rng = np.random.default_rng(seed)
    centers = centers + rng.normal(0.0, 1e-4, centers.shape)
    for _ in range(3000):
        dx = centers[:, None, 0] - centers[None, :, 0]
        dy = centers[:, None, 1] - centers[None, :, 1]
        half = (sides[:, None] + sides[None, :]) / 2.0 * pad
        ox = half - np.abs(dx)
        oy = half - np.abs(dy)
        hit = (ox > 0) & (oy > 0)
        np.fill_diagonal(hit, False)
        if not hit.any():
            break
        sx = np.where(dx >= 0, 1.0, -1.0)
        sy = np.where(dy >= 0, 1.0, -1.0)
        px = np.where(ox <= oy, sx * ox * 0.5, 0.0)
        py = np.where(oy < ox, sy * oy * 0.5, 0.0)
        centers = centers + np.c_[np.where(hit, px, 0.0).sum(axis=1),
                                  np.where(hit, py, 0.0).sum(axis=1)]
    return centers - centers.mean(axis=0), sides


def mvg_gmap_polygons(points, labels, ring=128, margin=0.05, ring_mult=1.05):
    """GMap-style plane partition: Voronoi over the node points plus a ring
    of points in the unbounded space, cells merged per group (KMap step 3).
    Returns {group: shapely geometry} -- a group can come back as a
    MultiPolygon (GMap's fragmentation); see mvg_largest_part."""
    from scipy.spatial import Voronoi
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    pts = np.asarray(points, dtype=float)
    labels = list(labels)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    center = (lo + hi) / 2.0
    # Size the ring on the max RADIAL distance, not the axis span: a node in
    # a corner of the bounding box sits up to sqrt(2)/2 * span from the
    # center, further than a circle of radius span/2, and any node outside
    # the ring gets an unbounded Voronoi cell and is dropped from its group
    # polygon (silently placing it outside its own region).
    radius = float(np.linalg.norm(pts - center, axis=1).max()) * (1.0 + margin) + 1e-6
    ang = np.linspace(0.0, 2.0 * math.pi, ring, endpoint=False)
    ringpts = center + np.c_[np.cos(ang), np.sin(ang)] * radius * ring_mult
    vor = Voronoi(np.vstack([pts, ringpts]))
    box = Polygon([(center[0] - radius, center[1] - radius),
                   (center[0] + radius, center[1] - radius),
                   (center[0] + radius, center[1] + radius),
                   (center[0] - radius, center[1] + radius)])
    cells = {}
    for i in range(len(pts)):
        region = vor.regions[vor.point_region[i]]
        if not region or -1 in region:
            continue
        poly = Polygon(vor.vertices[region]).buffer(0).intersection(box)
        if not poly.is_empty:
            cells.setdefault(labels[i], []).append(poly)
    return {g: unary_union(v).buffer(0) for g, v in cells.items()}


def mvg_fit_to_square(local, side, fill=0.86, uniform=False, pct=88.0):
    """Scale a centered subgraph layout to fit a square of `side` (KMap
    step 2). Default is per-axis: each axis is stretched independently so
    the nodes actually occupy the square -- this is what produces KMap's
    characteristic 'artificial square shape' and what M6 rewards. Pass
    uniform=True to preserve the subgraph's aspect ratio instead."""
    local = np.asarray(local, dtype=float)
    if len(local) == 0:
        return local
    local = local - local.mean(axis=0)
    if len(local) == 1:
        return np.zeros((1, 2))
    target = side / 2.0 * fill
    # Scale on a high percentile rather than the max: force layouts often
    # throw a few outliers that would otherwise squash the bulk of the
    # subgraph into the middle of the square. Points past the percentile
    # are clipped back to the square edge.
    if uniform:
        span = np.percentile(np.abs(local), pct)
        span = span if span > 0 else (np.abs(local).max() or 1.0)
        return np.clip(local / span * target, -target, target)
    span = np.percentile(np.abs(local), pct, axis=0)
    hard = np.abs(local).max(axis=0)
    degenerate = hard < (hard.max() if hard.max() > 0 else 1.0) * 1e-3
    span = np.where(span <= 0, np.where(hard > 0, hard, 1.0), span)
    out = np.clip(local / span * target, -target, target)
    out[:, degenerate] = 0.0
    return out


def mvg_largest_part(geom):
    """Largest single polygon of a Polygon/MultiPolygon."""
    if geom.geom_type == "Polygon":
        return geom
    return max(geom.geoms, key=lambda p: p.area)


def mvg_kmap(labels, edges, seed=None, sub_iterations=250, fill=0.86,
             spread=0.8, margin=0.05, ring_mult=1.05, uniform_fit=False):
    """KMap (Method 1): pack group squares, lay out each subgraph
    independently and scale-and-fit it into its square, then GMap-partition
    the plane. Returns {'points', 'labels', 'polygons', 'squares'}.

    `spread`/`margin`/`ring_mult` control how tightly the squares pack and
    how far the GMap ring sits outside them; the defaults keep total polygon
    area close to total square area (see SKILL.md 'Tuning')."""
    if seed is None:
        seed = MVG_SEED
    labels = list(labels)
    edges = [tuple(e) for e in edges]
    groups, weights, super_edges = mvg_group_network(labels, edges)
    centers, sides = mvg_pack_squares(weights, super_edges, seed=seed,
                                      spread=spread)
    points = np.zeros((len(labels), 2))
    for gi, g in enumerate(groups):
        members = [i for i, lb in enumerate(labels) if lb == g]
        remap = {v: i for i, v in enumerate(members)}
        sub = [(remap[u], remap[v]) for u, v in edges
               if labels[u] == g and labels[v] == g]
        local = mvg_force_layout(len(members), sub, iterations=sub_iterations,
                                 seed=seed + gi, scale=1.0)
        local = mvg_fit_to_square(local, sides[gi], fill=fill,
                                  uniform=uniform_fit)
        points[members] = local + centers[gi]
    squares = {g: (centers[i], sides[i]) for i, g in enumerate(groups)}
    polygons = mvg_gmap_polygons(points, labels, margin=margin,
                                 ring_mult=ring_mult)
    return {"points": points, "labels": labels, "polygons": polygons,
            "squares": squares}


def mvg_pcl(points, labels, edges, polygons, iterations=300, kg=0.06,
            k_corner=0.30, k_ext=0.55, k_rep=1.0, alpha_sqrt=True,
            coverage_target=0.70, clamp=True, seed=None):
    """PCL (Method 2): redistribute nodes inside the KMap polygons under
    boundary-aware central gravity (Eq. 2), corner gravity, external
    gravity (Eq. 3) and the area-normalized attraction force.

    Two deliberate departures from the printed paper, both documented in
    SKILL.md: external gravity pulls TOWARD the neighbouring polygon's
    center (Eq. 3 as printed has the vector pointing away, contradicting
    the surrounding text and Fig. 7), and alpha is the square root of
    area/|nodes| so that it is a distance (`alpha_sqrt=False` for the
    literal reading). Returns new (n, 2) positions."""
    from shapely.geometry import Point, LineString
    if seed is None:
        seed = MVG_SEED
    rng = np.random.default_rng(seed)
    labels = list(labels)
    edges = [tuple(e) for e in edges]
    pos = np.asarray(points, dtype=float).copy()
    groups = sorted(polygons.keys(), key=lambda g: str(g))
    parts = {g: mvg_largest_part(polygons[g]) for g in groups}
    members = {g: [i for i, lb in enumerate(labels) if lb == g] for g in groups}
    gcenter = {g: np.array(parts[g].centroid.coords[0]) for g in groups}
    corners = {g: np.asarray(parts[g].exterior.coords)[:-1] for g in groups}
    alpha = {}
    for g in groups:
        n = max(len(members[g]), 1)
        a = parts[g].area / n
        alpha[g] = math.sqrt(a) if alpha_sqrt else a
    deg = np.zeros(len(labels))
    for u, v in edges:
        deg[u] += 1.0
        deg[v] += 1.0
    mass = np.maximum(deg, 1.0)
    ext = {}
    for u, v in edges:
        if labels[u] != labels[v]:
            ext.setdefault(u, {}).setdefault(labels[v], 0.0)
            ext[u][labels[v]] += 1.0
            ext.setdefault(v, {}).setdefault(labels[u], 0.0)
            ext[v][labels[u]] += 1.0
    for g in groups:
        idx = members[g]
        if idx:
            pos[idx] = gcenter[g] + rng.normal(0.0, alpha[g] * 0.05, (len(idx), 2))
    rep_scale = k_rep
    for step in range(iterations):
        disp = np.zeros_like(pos)
        for g in groups:
            idx = members[g]
            if len(idx) == 0:
                continue
            p = pos[idx]
            poly, cen = parts[g], gcenter[g]
            r = cen - p
            norm = np.maximum(np.linalg.norm(r, axis=1, keepdims=True), 1e-9)
            dvo = np.empty((len(idx), 1))
            bound = poly.exterior
            for j, xy in enumerate(p):
                ray = LineString([xy, xy + (cen - xy) / max(
                    np.linalg.norm(cen - xy), 1e-9) * (poly.length + 1.0) * -1.0])
                inter = ray.intersection(bound)
                dvo[j, 0] = (Point(xy).distance(inter)
                             if not inter.is_empty else alpha[g])
            dvo = np.maximum(dvo, alpha[g] * 0.2)
            disp[idx] += kg * mass[idx, None] * (r / norm) / dvo
            cs = corners[g]
            rc = cs[None, :, :] - p[:, None, :]
            nc = np.maximum(np.linalg.norm(rc, axis=-1, keepdims=True), 1e-9)
            disp[idx] += k_corner * kg * mass[idx, None] * (rc / nc).mean(axis=1)
            if len(idx) > 1:
                d = p[:, None, :] - p[None, :, :]
                dd = np.maximum(np.linalg.norm(d, axis=-1), 1e-9)
                np.fill_diagonal(dd, np.inf)
                rep = ((alpha[g] ** 2 / dd ** 2)[:, :, None]
                       * (d / dd[:, :, None]))
                disp[idx] += rep_scale * np.nan_to_num(rep).sum(axis=1)
            for i in idx:
                for q, m_ext in ext.get(i, {}).items():
                    if q not in gcenter:
                        continue
                    re = gcenter[q] - pos[i]
                    disp[i] += k_ext * kg * m_ext * re / max(
                        np.linalg.norm(re), 1e-9)
        for u, v in edges:
            g = labels[u] if labels[u] == labels[v] else None
            a = alpha[labels[u]] if g is None else alpha[g]
            d = pos[u] - pos[v]
            dl = max(float(np.linalg.norm(d)), 1e-9)
            f = d * (a / dl)
            disp[u] -= f * 0.5
            disp[v] += f * 0.5
        dl = np.maximum(np.linalg.norm(disp, axis=1, keepdims=True), 1e-9)
        cap = np.array([alpha[labels[i]] * 0.25 for i in range(len(pos))])[:, None]
        pos = pos + disp / dl * np.minimum(dl, cap) * (1.0 - step / (2.0 * iterations))
        if clamp:
            for g in groups:
                poly = parts[g]
                for i in members[g]:
                    pt = Point(pos[i])
                    if not poly.contains(pt):
                        nearest = poly.exterior.interpolate(
                            poly.exterior.project(pt))
                        inward = np.array(nearest.coords[0])
                        pos[i] = inward + (gcenter[g] - inward) * 0.08
        if step % 25 == 24 and coverage_target:
            cov = np.mean([mvg_hull_coverage(pos[members[g]], parts[g])
                           for g in groups if len(members[g]) > 2] or [1.0])
            if cov < coverage_target:
                rep_scale *= 1.15
    return pos


def mvg_hull_coverage(pts, poly):
    """Fraction of a polygon's convex hull covered by the convex hull of the
    node positions inside it (the quantity M6 penalizes)."""
    from shapely.geometry import MultiPoint
    if len(pts) < 3:
        return 0.0
    hull = MultiPoint([tuple(p) for p in pts]).convex_hull
    ch = poly.convex_hull
    return float(hull.area / ch.area) if ch.area > 0 else 0.0


def mvg_metrics(points, labels, edges, polygons, sample=1200, seed=None):
    """Quality metrics M1-M7 (paper Section 5.3). Larger is better for every
    metric AS DEFINED IN THE PAPER; note M2 is a hull/area ratio >= 1 whose
    stated direction is questionable (see SKILL.md). Returns a dict."""
    from shapely.geometry import LineString, MultiPoint
    from shapely.ops import unary_union
    if seed is None:
        seed = MVG_SEED
    pts = np.asarray(points, dtype=float)
    labels = list(labels)
    edges = [tuple(e) for e in edges]
    groups = sorted(polygons.keys(), key=lambda g: str(g))
    parts = {g: mvg_largest_part(polygons[g]) for g in groups}
    m1 = []
    for g in groups:
        poly = parts[g]
        cs = np.asarray(poly.exterior.coords)[:-1]
        k = len(cs)
        good = 0
        for a in range(k):
            for b in range(a + 1, k):
                if poly.covers(LineString([cs[a], cs[b]])):
                    good += 1
        m1.append(good / (k ** 2) if k else 0.0)
    union = unary_union([polygons[g] for g in groups])
    total = sum(polygons[g].area for g in groups)
    m2 = union.convex_hull.area / total if total > 0 else 0.0
    counts = {g: sum(1 for lb in labels if lb == g) for g in groups}
    sup = {}
    for u, v in edges:
        if labels[u] != labels[v]:
            sup[(min(str(labels[u]), str(labels[v])),
                 max(str(labels[u]), str(labels[v])))] = (labels[u], labels[v])
    hits = 0
    for a, b in sup.values():
        if parts[a].buffer(1e-9).intersects(parts[b].buffer(1e-9)):
            hits += 1
    m3 = hits / len(sup) if sup else 1.0
    tw = sum(counts.values())
    ta = sum(polygons[g].area for g in groups)
    m4 = 1.0 - float(np.mean([abs(counts[g] / tw - polygons[g].area / ta)
                              for g in groups])) if tw and ta else 0.0
    m5 = 1.0 - mvg_stress(pts, edges, sample=sample, seed=seed)
    m6 = 1.0 - float(np.mean([
        1.0 - mvg_hull_coverage(pts[[i for i, lb in enumerate(labels) if lb == g]],
                                parts[g]) for g in groups]))
    m7 = 1.0 - mvg_crossing_fraction(pts, edges)
    return {"M1": float(np.mean(m1)) if m1 else 0.0, "M2": float(m2),
            "M3": float(m3), "M4": float(m4), "M5": float(m5),
            "M6": float(m6), "M7": float(m7)}


def mvg_stress(points, edges, sample=1200, seed=None):
    """Normalized stress (paper Eq. in 5.3.5), w(u,v) = graph distance.
    Node pairs are subsampled above `sample` nodes to bound the O(n^2) BFS."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import shortest_path
    if seed is None:
        seed = MVG_SEED
    pts = np.asarray(points, dtype=float)
    n = len(pts)
    if n < 2 or not edges:
        return 0.0
    E = np.asarray(edges, dtype=int).reshape(-1, 2)
    A = coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(n, n))
    A = A + A.T
    idx = np.arange(n)
    if n > sample:
        idx = np.random.default_rng(seed).choice(n, sample, replace=False)
    D = shortest_path(A.tocsr(), method="D", unweighted=True, indices=idx)[:, idx]
    P = pts[idx]
    L = np.linalg.norm(P[:, None, :] - P[None, :, :], axis=-1)
    ok = np.isfinite(D) & (D > 0)
    if not ok.any():
        return 0.0
    d, l = D[ok], L[ok]
    num = (d * ((l - d) / np.maximum(np.maximum(l, d), 1e-9)) ** 2).sum()
    return float(num / d.sum())


def mvg_crossing_fraction(points, edges, cap=4000):
    """Properly-crossing edge pairs / |E|^2 (paper 5.3.7)."""
    pts = np.asarray(points, dtype=float)
    E = np.asarray(edges, dtype=int).reshape(-1, 2)
    m = len(E)
    if m < 2:
        return 0.0
    use = E if m <= cap else E[np.random.default_rng(MVG_SEED).choice(
        m, cap, replace=False)]
    a, b = pts[use[:, 0]], pts[use[:, 1]]

    def side(p, q, r):
        return np.sign((q[:, None, 0] - p[:, None, 0]) * (r[None, :, 1] - p[:, None, 1])
                       - (q[:, None, 1] - p[:, None, 1]) * (r[None, :, 0] - p[:, None, 0]))

    s1, s2 = side(a, b, a), side(a, b, b)
    cross = (s1 * s2 < 0) & (s1.T * s2.T < 0)
    shared = ((use[:, None, 0] == use[None, :, 0]) | (use[:, None, 0] == use[None, :, 1])
              | (use[:, None, 1] == use[None, :, 0]) | (use[:, None, 1] == use[None, :, 1]))
    cross = cross & ~shared
    np.fill_diagonal(cross, False)
    n_cross = int(cross.sum() / 2)
    return float(n_cross / (m ** 2))


def mvg_plot(points, labels, edges, polygons, path="mvg.png", figsize=(9, 9),
             node_size=6, edge_alpha=0.18, cmap="tab20", title=None):
    """Render an MVG: filled group polygons, edges, nodes. Returns the fig."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MplPolygon
    pts = np.asarray(points, dtype=float)
    labels = list(labels)
    groups = sorted(polygons.keys(), key=lambda g: str(g))
    colors = plt.get_cmap(cmap)(np.linspace(0, 1, max(len(groups), 2)))
    fig, ax = plt.subplots(figsize=figsize)
    for gi, g in enumerate(groups):
        geom = polygons[g]
        for part in ([geom] if geom.geom_type == "Polygon" else list(geom.geoms)):
            ax.add_patch(MplPolygon(np.asarray(part.exterior.coords),
                                    closed=True, facecolor=colors[gi],
                                    edgecolor="white", linewidth=1.4, alpha=0.55,
                                    zorder=1))
    for u, v in edges:
        ax.plot([pts[u, 0], pts[v, 0]], [pts[u, 1], pts[v, 1]], color="0.25",
                linewidth=0.4, alpha=edge_alpha, zorder=2)
    cidx = {g: i for i, g in enumerate(groups)}
    ax.scatter(pts[:, 0], pts[:, 1], s=node_size,
               c=[colors[cidx[lb]] for lb in labels], edgecolors="0.2",
               linewidths=0.3, zorder=3)
    ax.set_aspect("equal")
    ax.axis("off")
    if title:
        ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    return fig
