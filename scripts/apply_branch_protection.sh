#!/usr/bin/env bash
# Idempotent: reads scripts/branch_protection_config.json and applies it to main.
# Usage: REPO=melon-lab-com/melon-monarch-cfo bash scripts/apply_branch_protection.sh
#        (defaults to the repo detected by gh in the current directory)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$SCRIPT_DIR/branch_protection_config.json"

REPO="${REPO:-$(gh repo view --json nameWithOwner --jq '.nameWithOwner')}"

[[ -f "$CONFIG" ]] || { echo "error: config not found at $CONFIG"; exit 1; }

echo "Applying branch protection to $REPO / main ..."
gh api -X PUT "repos/$REPO/branches/main/protection" --input "$CONFIG"
echo "Done. Current protection:"
gh api "repos/$REPO/branches/main/protection" \
  --jq '{
    enforce_admins:        .enforce_admins.enabled,
    required_prs:          (.required_pull_request_reviews != null),
    required_approvals:    .required_pull_request_reviews.required_approving_review_count,
    dismiss_stale:         .required_pull_request_reviews.dismiss_stale_reviews,
    required_linear:       .required_linear_history.enabled,
    allow_force_push:      .allow_force_pushes.enabled,
    allow_deletions:       .allow_deletions.enabled,
    required_checks:       [.required_status_checks.contexts[]]
  }'
