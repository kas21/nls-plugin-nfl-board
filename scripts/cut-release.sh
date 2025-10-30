#!/usr/bin/env bash
set -euo pipefail

# Usage: scripts/cut-release.sh vX.Y.Z
VERSION="${1:?Usage: scripts/cut-release.sh vX.Y.Z}"
DATE="$(date +%F)"

# Resolve upstreams (expects: beta -> origin/2025.x.x-beta, main -> origin/main)
BETA_UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name beta@{upstream} 2>/dev/null || true)"
MAIN_UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name main@{upstream} 2>/dev/null || true)"
if [ -z "$BETA_UPSTREAM" ]; then
  echo "ERROR: 'beta' has no upstream. Set to origin/2025.x.x-beta:" >&2
  echo "       git branch --set-upstream-to=origin/2025.x.x-beta beta" >&2
  exit 1
fi
if [ -z "$MAIN_UPSTREAM" ]; then
  echo "ERROR: 'main' has no upstream. Set to origin/main:" >&2
  echo "       git branch --set-upstream-to=origin/main main" >&2
  exit 1
fi
REMOTE="${MAIN_UPSTREAM%%/*}"

# Update branches
git fetch "$REMOTE" --prune
git switch beta && git pull --ff-only
git switch main && git pull --ff-only

# Ensure main can fast-forward to beta
if ! git merge-base --is-ancestor main beta; then
  echo "ERROR: 'main' has commits not in 'beta'. Merge/rebase ${MAIN_UPSTREAM} into beta and retry." >&2
  exit 1
fi

# Prepare release notes
TEMPLATE="docs/RELEASE_TEMPLATE.md"
[ -f "$TEMPLATE" ] || { echo "ERROR: $TEMPLATE not found."; exit 1; }
mkdir -p docs/releases
NOTES="docs/releases/${VERSION}.md"
sed -e "s/\$VERSION/${VERSION#v}/g" -e "s/\$DATE/${DATE}/g" "$TEMPLATE" > "$NOTES"

PREV_TAG="$(git describe --tags --abbrev=0 --match 'v*' 2>/dev/null || true)"
{
  printf "\n```\n"
  if [ -n "$PREV_TAG" ]; then
    git --no-pager log --pretty='format:%h %s' "${PREV_TAG}..beta"
  else
    git --no-pager log --pretty='format:%h %s' beta
  fi
  printf "\n```\n"
} >> "$NOTES"

# Fast-forward main <- beta, tag, push
git switch main
git merge --ff-only beta
git tag -a "$VERSION" -m "Release ${VERSION#v}"
git push "$REMOTE" main
git push "$REMOTE" "$VERSION"

echo "Drafted notes: $NOTES"
echo "Publish the release (UI) or:"
echo "  gh release create $VERSION --title '${VERSION#v}' --notes-file $NOTES"
echo "Then bump beta to next dev, commit, and push."
