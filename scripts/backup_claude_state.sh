#!/usr/bin/env bash
# Back up Claude Code session state (memory + plans) and a git bundle of
# this repo to the CyVerse Data Store, so a K8s pod OOM never loses work.
#
#     scripts/backup_claude_state.sh
#
# What it does:
#   1. Stages ~/.claude/projects/-home-jovyan-data-store-lto/memory/ and
#      ~/.claude/plans/*.md into a scratch dir (plain copies — the CSI/FUSE
#      mount struggles with .git metadata, so nothing git-shaped is staged).
#   2. Creates an INCREMENTAL `repo.bundle` holding only commits that are
#      not on any origin/* ref — near-empty when pushes flow, and the
#      safety net for work stranded by an expired gh token. Restore:
#      clone from GitHub, then `git fetch repo.bundle 'refs/*:refs/bundle/*'`.
#      (A full-history bundle of this repo is ~620 MB — too heavy to
#      re-upload at backup cadence.)
#   3. Writes BACKUP_INFO.txt (UTC timestamp, HEAD sha, branch).
#   4. `gocmd sync --no_root --delete` the staging dir into
#      i:/iplant/home/tswetnam/lto/claude  (overwrite-in-place mirror; the
#      publish AVU history in .mesa/ducklake provides the timeline).
#
# Exit non-zero on any failure so milestone checklists catch a dead backup.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_MEMORY="$HOME/.claude/projects/-home-jovyan-data-store-lto/memory"
CLAUDE_PLANS="$HOME/.claude/plans"
DEST="i:/iplant/home/tswetnam/lto/claude"
STAGING="${TMPDIR:-/tmp}/lto_claude_backup"

rm -rf "$STAGING"
mkdir -p "$STAGING/memory" "$STAGING/plans"

[ -d "$CLAUDE_MEMORY" ] && cp -r "$CLAUDE_MEMORY/." "$STAGING/memory/"
compgen -G "$CLAUDE_PLANS/*.md" > /dev/null && cp "$CLAUDE_PLANS"/*.md "$STAGING/plans/"

# Incremental git bundle: only commits absent from every origin/* ref.
# Fails ("Refusing to create empty bundle") when everything is pushed —
# that's the good case: remove the stale remote bundle explicitly.
# (gocmd sync --delete would otherwise hit an INTERACTIVE "Remove?"
# prompt for the extra remote object and spin forever in a headless
# shell — that exact hang killed two backup runs on 2026-08-13.)
BUNDLE_STATE="empty (all local commits are on origin)"
if git -C "$REPO" bundle create "$STAGING/repo.bundle" \
     --branches --not --remotes=origin --quiet 2>/dev/null; then
  BUNDLE_STATE="$(git -C "$REPO" bundle list-heads "$STAGING/repo.bundle" | wc -l) ref(s)"
else
  gocmd rm -f "${DEST#i:}/repo.bundle" 2>/dev/null || true
fi

{
  echo "timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "head: $(git -C "$REPO" rev-parse --short HEAD)"
  echo "branch: $(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
  echo "bundle: $BUNDLE_STATE"
  echo "unpushed:"
  git -C "$REPO" log --oneline --branches --not --remotes=origin | sed 's/^/  /'
} > "$STAGING/BACKUP_INFO.txt"

# --no: never prompt (headless). Extra remote files are handled above
# (bundle) or tolerated — mirror hygiene must not cost interactivity.
gocmd sync "$STAGING" "$DEST" --no_root --no_hash --no

echo "[ok] claude state + repo bundle backed up to ${DEST#i:}"
