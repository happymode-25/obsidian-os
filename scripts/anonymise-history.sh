#!/bin/bash
# Obsidian OS — anonymise public git history.
#
# Rewrites every commit reachable from any ref so that the published history
# carries no individual's name, email, timezone, or working hours:
#
#   author/committer  Obsidian OS <obsidian@localhost>
#   author/committer date  1970-01-01T00:00:00 +0000
#
# Run this BEFORE the repository is pushed, not after. Once pushed, the objects
# exist in the GitHub API, in caches, and in any clone; rewriting later only
# changes what the default branch points at.
#
#   ./scripts/anonymise-history.sh
#   git push --force --tags origin master
#
# The pre-push hook (scripts/git-hooks/pre-push) blocks a push that would publish
# non-canonical metadata, so this is the repair tool for that failure.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")/.."

if [ -n "$(git status --porcelain)" ]; then
  echo "anonymise-history: working tree is dirty; commit or stash first" >&2
  echo "  (a rewrite does not touch the working tree, but a dirty tree makes it" >&2
  echo "   impossible to tell your changes from the ones being rewritten)" >&2
  exit 1
fi

export FILTER_BRANCH_SQUELCH_WARNING=1

env_filter='
export GIT_AUTHOR_NAME="Obsidian OS"
export GIT_AUTHOR_EMAIL="obsidian@localhost"
export GIT_COMMITTER_NAME="Obsidian OS"
export GIT_COMMITTER_EMAIL="obsidian@localhost"
export GIT_AUTHOR_DATE="1970-01-01T00:00:00+0000"
export GIT_COMMITTER_DATE="1970-01-01T00:00:00+0000"
'

echo "anonymise-history: rewriting all refs (branches and tags)…"
git filter-branch -f --env-filter "$env_filter" --tag-name-filter cat -- --all

# filter-branch keeps the pre-rewrite refs under refs/original so a mistake is
# recoverable; they also keep every old object alive locally. Drop them.
git for-each-ref --format='%(refname)' refs/original | while read -r ref; do
  [ -n "$ref" ] && git update-ref -d "$ref"
done
git reflog expire --expire=now --all
git gc --prune=now --quiet

echo
echo "anonymise-history: verify before pushing:"
echo "  git log --format='%ai %ci %an <%ae>' | sort -u"
echo "then:"
echo "  git push --force --tags origin master"
