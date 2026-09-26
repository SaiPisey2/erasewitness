#!/usr/bin/env bash
# Fails if any commit or tracked file carries AI-tool attribution.
set -euo pipefail
pattern='claude|anthropic|co-authored-by|generated with'
if git log --format='%an%n%ae%n%cn%n%ce%n%B' | grep -qiE "$pattern"; then
  echo "verify-attribution: AI attribution found in commit history" >&2
  exit 1
fi
if git grep -qiE "$pattern" -- ':!scripts/verify-attribution.sh'; then
  echo "verify-attribution: AI attribution found in tracked files:" >&2
  git grep -niE "$pattern" -- ':!scripts/verify-attribution.sh' >&2
  exit 1
fi
echo "verify-attribution: clean"
