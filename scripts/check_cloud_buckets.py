#!/usr/bin/env python3
"""Check every cloud_buckets row against the bucket itself, and correct the lake.

check_url_health.py checks a bucket's documentation_url, not the bucket.
This asks the storage service, anonymously, about each row, and reads
the AWS Open Data Registry (github.com/awslabs/open-data-registry, cloned
shallow into a temp dir) for what each bucket's provider documents:

  s3     HEAD https://<bucket>.s3.amazonaws.com/ -> exists? region
         (x-amz-bucket-region, sent even when access is denied); then a
         ListObjectsV2 in that region, a 1-byte GET of the first object,
         and a listing under sample_prefix
  gcs    JSON API object listing + a 1-byte GET of the first object
  azure  container listing + a 1-byte GET; when anonymous listing is
         refused, the Planetary Computer token API: it either issues a
         read token without an account (checked by listing with it) or
         says the container does not exist
  https  GET https://<host>/<sample_prefix> (a 404 there is not taken as
         the host being gone)

  verdict  readable   anonymous listing and object read allowed
           token      readable with a token issued without an account
           list-only  listing allowed, object read refused
           denied     the bucket exists; anonymous listing refused
           gone       no such bucket / container / host
           error      anything else (the row is left alone)

Decisions, applied with --apply in one lake transaction (one snapshot):

  successor  a row named in data/seed/cloud_bucket_successors.csv (each
             citing the registry page that names the replacement) is
             re-pointed at the successor bucket, which is then checked
             like any other
  delete     gone; or the registry marks the bucket's dataset Deprecated
             and it is not anonymously readable
  access     observed anonymous read (readable / token) -> public-read,
             unless already public-read / public-anon-egress;
             else registry ControlledAccess (an Earthdata s3credentials
             endpoint) -> registered-users;
             else registry RequesterPays -> requester-pays;
             else the recorded mode is kept (a refused listing alone does
             not say whether an account, payment or nothing is needed)
  region     the region S3 reports
  prefix     sample_prefix cleared when a listing under it is empty
  duplicate  rows that end up as the same (provider, bucket, region):
             the one linked to an archive is kept

Each changed row gets a dated note of what was observed and the source.
bucket_id is re-derived as load_lto_archives.py does
(sha1(provider|bucket_name|region)[:16]). data/seed/cloud_bucket_checks.csv
logs every row, changed or not. There are no raw cloud_buckets.json
files: public/parquet is these rows' only source, so after --apply run
qa.py, export_parquet.py and export_view_caches.py.

Usage::

    python scripts/check_cloud_buckets.py            # check and log only
    python scripts/check_cloud_buckets.py --apply
    python scripts/check_cloud_buckets.py --registry /path/to/open-data-registry
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "seed" / "cloud_bucket_checks.csv"
SUCCESSORS = ROOT / "data" / "seed" / "cloud_bucket_successors.csv"
REGISTRY_GIT = "https://github.com/awslabs/open-data-registry"
REGISTRY_PAGE = "https://registry.opendata.aws/{slug}/"
PC_TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/{account}/{container}"
UA = "lto check_cloud_buckets (https://github.com/tyson-swetnam/lto)"
PUBLIC = {"public-read", "public-anon-egress"}
# An S3 listing names objects in <Key> (its <Name> is the bucket); Azure
# names blobs in <Name>.
S3_KEY_RE = re.compile(r"<Key>([^<]+)</Key>")
AZ_KEY_RE = re.compile(r"<Blob><Name>([^<]+)</Name>")
PREFIX_RE = re.compile(r"<Prefix>([^<]+)</Prefix>")


def sha16(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


@dataclass
class Probe:
    verdict: str
    region: str | None = None
    detail: str = ""
    prefix_empty: bool = False


# ── AWS Open Data Registry ──────────────────────────────────────────

def load_registry(path: Path) -> tuple[dict[str, dict], str]:
    """bucket name -> what the registry's datasets say about it."""
    idx: dict[str, dict] = {}
    for f in sorted((path / "datasets").glob("*.yaml")):
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(d, dict):
            continue
        dep = bool(d.get("Deprecated"))
        for res in d.get("Resources") or []:
            arn = str((res or {}).get("ARN") or "").strip()
            if not arn.startswith("arn:aws:s3:::"):
                continue
            name = arn[len("arn:aws:s3:::"):].split("/", 1)[0]
            e = idx.setdefault(name, {"slug": f.stem, "region": res.get("Region"),
                                      "requester_pays": False, "controlled_access": None,
                                      "deprecated": dep})
            # Deprecated only if every dataset that names the bucket is.
            e["deprecated"] = e["deprecated"] and dep
            e["requester_pays"] |= str(res.get("RequesterPays")).lower() == "true"
            e["controlled_access"] = e["controlled_access"] or res.get("ControlledAccess")
    commit = subprocess.run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    return idx, commit


# ── storage probes ──────────────────────────────────────────────────

def first_object(text: str, pattern: re.Pattern) -> str | None:
    for k in pattern.findall(text):
        k = html.unescape(k)
        if not k.endswith("/"):
            return k
    return None


def deep_s3_object(s, base: str) -> str | None:
    """A data object, not a root-level readme: follow the first
    sub-prefix down (up to 8 levels), then take the first object there.
    Root files can be public in a bucket whose data are not."""
    prefix = ""
    for _ in range(8):
        r = s.get(f"{base}/?list-type=2&delimiter=/&max-keys=50&prefix={quote(prefix)}", timeout=30)
        subs = [html.unescape(x) for x in PREFIX_RE.findall(r.text)]
        subs = [x for x in subs if x != prefix]
        if not subs:
            break
        prefix = subs[0]
    r = s.get(f"{base}/?list-type=2&max-keys=20&prefix={quote(prefix)}", timeout=30)
    return first_object(r.text, S3_KEY_RE)


def deep_gcs_object(s, name: str) -> str | None:
    api = f"https://storage.googleapis.com/storage/v1/b/{name}/o"
    prefix = ""
    for _ in range(8):
        subs = s.get(api, params={"delimiter": "/", "prefix": prefix, "maxResults": 50},
                     timeout=30).json().get("prefixes") or []
        if not subs:
            break
        prefix = subs[0]
    items = s.get(api, params={"prefix": prefix, "maxResults": 20}, timeout=30).json().get("items") or []
    return next((i["name"] for i in items if not i["name"].endswith("/")), None)


def read_one(s, url: str) -> int:
    r = s.get(url, headers={"Range": "bytes=0-0"}, timeout=30, stream=True)
    r.close()
    return r.status_code


def probe_s3(s, name: str, prefix: str | None) -> Probe:
    h = s.head(f"https://{name}.s3.amazonaws.com/", timeout=30, allow_redirects=False)
    region = h.headers.get("x-amz-bucket-region")
    if not region:
        r = s.get(f"https://{name}.s3.amazonaws.com/?list-type=2&max-keys=1", timeout=30)
        if "NoSuchBucket" in r.text:
            return Probe("gone", detail="NoSuchBucket")
        return Probe("error", detail=f"HTTP {h.status_code}, no region header")
    base = f"https://{name}.s3.{region}.amazonaws.com"
    r = s.get(f"{base}/?list-type=2&max-keys=20", timeout=30)
    if r.status_code != 200 or "ListBucketResult" not in r.text:
        return Probe("denied", region, "anonymous listing refused (AccessDenied)")
    empty = False
    if prefix:
        rp = s.get(f"{base}/?list-type=2&max-keys=1&prefix={quote(prefix)}", timeout=30)
        empty = rp.status_code == 200 and "<KeyCount>0</KeyCount>" in rp.text
    key = deep_s3_object(s, base) or first_object(r.text, S3_KEY_RE)
    if not key:
        return Probe("list-only", region, "listing allowed; no object found to read", empty)
    code = read_one(s, f"{base}/{quote(key)}")
    if code in (200, 206):
        return Probe("readable", region, f"anonymous listing and read of {key} allowed", empty)
    return Probe("list-only", region, f"listing allowed; reading {key} refused (HTTP {code})", empty)


def probe_gcs(s, name: str, prefix: str | None) -> Probe:
    r = s.get(f"https://storage.googleapis.com/storage/v1/b/{name}/o?maxResults=20", timeout=30)
    if r.status_code == 404:
        return Probe("gone", detail="bucket not found")
    if r.status_code in (401, 403):
        return Probe("denied", detail=f"anonymous listing refused (HTTP {r.status_code})")
    if r.status_code != 200:
        return Probe("error", detail=f"HTTP {r.status_code}")
    items = [i["name"] for i in r.json().get("items", []) if not i["name"].endswith("/")]
    empty = False
    if prefix:
        rp = s.get(f"https://storage.googleapis.com/storage/v1/b/{name}/o",
                   params={"maxResults": 1, "prefix": prefix}, timeout=30)
        empty = rp.status_code == 200 and not rp.json().get("items")
    key = deep_gcs_object(s, name) or (items[0] if items else None)
    if not key:
        return Probe("list-only", detail="listing allowed; no object found to read", prefix_empty=empty)
    code = read_one(s, f"https://storage.googleapis.com/{name}/{quote(key)}")
    if code in (200, 206):
        return Probe("readable", detail=f"anonymous listing and read of {key} allowed", prefix_empty=empty)
    return Probe("list-only", detail=f"listing allowed; reading {key} refused (HTTP {code})", prefix_empty=empty)


def probe_azure(s, name: str) -> Probe:
    host, _, container = name.partition("/")
    base = f"https://{host}/{container}"
    try:
        r = s.get(f"{base}?restype=container&comp=list&maxresults=20", timeout=30)
    except requests.exceptions.ConnectionError:
        return Probe("gone", detail="storage account host does not resolve")
    if "ContainerNotFound" in r.text or "ResourceNotFound" in r.text:
        return Probe("gone", detail="container not found")
    if r.status_code == 200 and "EnumerationResults" in r.text:
        key = first_object(r.text, AZ_KEY_RE)
        code = read_one(s, f"{base}/{quote(key)}") if key else None
        if code in (200, 206):
            return Probe("readable", detail="anonymous listing and object read allowed")
        return Probe("list-only", detail="listing allowed; object read "
                                         + (f"refused (HTTP {code})" if code else "not tried"))
    # Planetary Computer storage: anonymous access goes through a SAS
    # token its token API hands out without an account.
    account = host.split(".", 1)[0]
    tok_url = PC_TOKEN.format(account=account, container=container)
    t = s.get(tok_url, timeout=30)
    body = t.json() if t.headers.get("content-type", "").startswith("application/json") else {}
    if t.status_code == 200 and body.get("token"):
        r2 = s.get(f"{base}?restype=container&comp=list&maxresults=1&{body['token']}", timeout=30)
        if r2.status_code == 200 and "EnumerationResults" in r2.text:
            return Probe("token", detail=f"anonymous listing refused; readable with a token from "
                                         f"{tok_url}, issued without an account")
        return Probe("denied", detail=f"token issued by {tok_url} but listing with it failed "
                                      f"(HTTP {r2.status_code})")
    if "does not exist" in str(body.get("detail", "")):
        return Probe("gone", detail=f"{tok_url}: {body['detail']}")
    return Probe("denied", detail=f"anonymous listing refused (HTTP {r.status_code})")


def probe_https(s, name: str, prefix: str | None) -> Probe:
    url = f"https://{name}/{prefix or ''}"
    try:
        r = s.get(url, timeout=30, allow_redirects=True, stream=True)
        r.close()
    except requests.exceptions.ConnectionError:
        return Probe("gone", detail=f"{name} does not resolve")
    if r.ok:
        return Probe("readable", detail=f"GET {url} -> {r.status_code}")
    return Probe("error", detail=f"GET {url} -> {r.status_code}; host answers")


def probe(s, provider: str, name: str, prefix: str | None) -> Probe:
    try:
        if provider == "s3":
            return probe_s3(s, name, prefix)
        if provider == "gcs":
            return probe_gcs(s, name, prefix)
        if provider == "azure":
            return probe_azure(s, name)
        if provider == "https":
            return probe_https(s, name, prefix)
        return Probe("error", detail=f"unknown provider {provider}")
    except requests.RequestException as e:
        return Probe("error", detail=str(e)[:100])


# ── decisions ───────────────────────────────────────────────────────

def decide(row: dict, p: Probe, reg: dict | None) -> tuple[str | None, list[str], str | None]:
    """(new access_mode or None to delete, reasons, source url)."""
    rec = row["access_mode"]
    page = REGISTRY_PAGE.format(slug=reg["slug"]) if reg else None
    if p.verdict == "gone":
        return None, [p.detail], None
    if reg and reg["deprecated"] and p.verdict not in ("readable", "token"):
        return None, [f"the registry marks dataset {reg['slug']} deprecated; {p.detail}"], page
    if p.verdict in ("readable", "token"):
        why = [p.detail]
        if reg and reg["requester_pays"]:
            why.append("the registry still marks it RequesterPays")
        return (rec if rec in PUBLIC else "public-read"), why, (page if reg and reg["requester_pays"] else None)
    if reg and reg["controlled_access"]:
        return "registered-users", [f"{p.detail}; the registry gives an Earthdata credentials "
                                    f"endpoint ({reg['controlled_access']})"], page
    if reg and reg["requester_pays"]:
        return "requester-pays", [f"{p.detail}; the registry marks it RequesterPays"], page
    return rec, [p.detail], None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--apply", action="store_true", help="correct the lake (default: check and log)")
    ap.add_argument("--registry", type=Path,
                    help="a clone of awslabs/open-data-registry (default: clone one to a temp dir)")
    args = ap.parse_args()
    today = date.today().isoformat()

    tmp = None
    if not args.registry:
        tmp = tempfile.TemporaryDirectory()
        args.registry = Path(tmp.name) / "odr"
        subprocess.run(["git", "clone", "-q", "--depth", "1", REGISTRY_GIT, str(args.registry)], check=True)
    registry, reg_commit = load_registry(args.registry)
    print(f"[registry] {len(registry)} buckets from {REGISTRY_GIT} @ {reg_commit}")
    successors = {(r["provider"], r["bucket_name"]): r
                  for r in csv.DictReader(SUCCESSORS.open(encoding="utf-8"))}

    con = lto_db.connect(read_only=not args.apply, catalog=args.catalog, data=args.lake_data)
    cols = ["bucket_id", "archive_id", "provider", "bucket_name", "region", "access_mode",
            "documentation_url", "sample_prefix", "notes"]
    rows = [dict(zip(cols, r)) for r in lto_db.rows(
        con, f"SELECT {', '.join(cols)} FROM cloud_buckets ORDER BY provider, bucket_name, region")]
    s = requests.Session()
    s.headers["User-Agent"] = UA

    plan = []
    for row in rows:
        prov, name, prefix = row["provider"], row["bucket_name"], row["sample_prefix"]
        new = dict(row)
        notes = []
        succ = successors.get((prov, name))
        if succ:
            old = probe(s, prov, name, None)
            new.update(bucket_name=succ["successor_bucket"], documentation_url=succ["source_url"],
                       sample_prefix=succ["successor_prefix"] or prefix)
            notes.append(f"was {name} ({old.verdict}: {old.detail}); {succ['reason']} "
                         f"({succ['source_url']})")
        p = probe(s, prov, new["bucket_name"], new["sample_prefix"])
        reg = registry.get(new["bucket_name"]) if prov == "s3" else None
        if p.verdict == "error":
            mode, why, src = row["access_mode"], [p.detail], None
        else:
            mode, why, src = decide(new, p, reg)
        changes = []
        if succ:
            changes.append(f"bucket {name} -> {new['bucket_name']}")
        if mode is None:
            action = "delete"
        else:
            if mode != row["access_mode"]:
                changes.append(f"access_mode {row['access_mode']} -> {mode}")
                new["access_mode"] = mode
            if p.region and p.region != row["region"]:
                changes.append(f"region {row['region']} -> {p.region}")
                new["region"] = p.region
            if p.prefix_empty:
                changes.append(f"sample_prefix {new['sample_prefix']} cleared (nothing under it)")
                new["sample_prefix"] = None
            elif succ and not succ["successor_prefix"] and p.verdict not in ("readable", "list-only"):
                new["sample_prefix"] = None   # the old prefix cannot be checked in the new bucket
            action = "; ".join(changes) or "keep"
        notes += why + ([src] if src else [])
        plan.append({"row": row, "new": new, "verdict": p.verdict, "action": action,
                     "detail": "; ".join(notes), "registry": reg["slug"] if reg else ""})
        print(f"[{p.verdict:>9}] {prov:<5} {name:<45} {action}")

    # Rows that end up as the same bucket: keep the one linked to an
    # archive (then the one that already had that region).
    keep: dict[tuple, dict] = {}
    for e in plan:
        if e["action"] == "delete":
            continue
        k = (e["new"]["provider"], e["new"]["bucket_name"], e["new"]["region"])
        if k not in keep:
            keep[k] = e
            continue
        a, b = keep[k], e
        rank = lambda x: (x["row"]["archive_id"] is not None, x["row"]["region"] == k[2])  # noqa: E731
        win, lose = (a, b) if rank(a) >= rank(b) else (b, a)
        lose["action"] = f"delete (same bucket as the row for {win['row']['archive_id'] or 'no archive'})"
        keep[k] = win

    with LOG.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["bucket_id", "archive_id", "provider", "bucket_name", "recorded_region",
                    "recorded_access_mode", "verdict", "registry_dataset", "decision", "detail",
                    "checked_at"])
        for e in plan:
            r = e["row"]
            w.writerow([r["bucket_id"], r["archive_id"] or "", r["provider"], r["bucket_name"],
                        r["region"] or "", r["access_mode"] or "", e["verdict"], e["registry"],
                        e["action"], e["detail"], today])
    tally: dict[str, int] = {}
    for e in plan:
        tally[e["verdict"]] = tally.get(e["verdict"], 0) + 1
    changed = [e for e in plan if e["action"] != "keep"]
    deletes = [e for e in changed if e["action"].startswith("delete")]
    print(f"[log] {len(plan)} buckets -> {LOG.relative_to(ROOT)}: {tally}; "
          f"{len(changed) - len(deletes)} to correct, {len(deletes)} to delete")
    if not args.apply:
        print("[dry-run] lake unchanged; pass --apply to correct it")
        return 0

    with lto_db.transaction(con, f"check_cloud_buckets: {len(changed) - len(deletes)} bucket rows "
                                 f"corrected, {len(deletes)} deleted, checked against the storage "
                                 f"services and the AWS Open Data Registry @ {reg_commit} ({today})"):
        for e in deletes:
            con.execute("DELETE FROM cloud_buckets WHERE bucket_id = ?", [e["row"]["bucket_id"]])
        for e in changed:
            if e in deletes:
                continue
            n = e["new"]
            note = f"Checked {today}: {e['action']}. {e['detail']} (scripts/check_cloud_buckets.py)"
            con.execute("""UPDATE cloud_buckets
                           SET bucket_id = ?, bucket_name = ?, region = ?, access_mode = ?,
                               documentation_url = ?, sample_prefix = ?,
                               notes = trim(coalesce(notes, '') || ' ' || ?)
                           WHERE bucket_id = ?""",
                        [sha16(f"{n['provider']}|{n['bucket_name']}|{n['region'] or ''}"),
                         n["bucket_name"], n["region"], n["access_mode"], n["documentation_url"],
                         n["sample_prefix"], note, e["row"]["bucket_id"]])
        lto_db.assert_integrity(con, ["cloud_buckets"])
    print(f"[apply] done; snapshot {lto_db.latest_snapshot(con).get('snapshot_id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
