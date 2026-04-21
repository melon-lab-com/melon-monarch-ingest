"""Read PR comments from $COMMENTS_JSON and match the sentinel for $HEAD_SHA.

Exits 0 and prints APPROVED / CHANGES_REQUESTED / PENDING.
Called by .github/workflows/code-reviewer-gate.yml.
"""

import json
import os
import sys

head_sha = os.environ["HEAD_SHA"]
comments: list[dict[str, str]] = json.loads(os.environ["COMMENTS_JSON"])

APPROVED = "[code-reviewer] verdict: APPROVED"
REJECTED = "[code-reviewer] verdict: CHANGES REQUESTED"

for comment in comments:
    lines = comment["body"].strip().splitlines()
    if not lines:
        continue
    first = lines[0].strip()
    if first not in (APPROVED, REJECTED):
        continue
    for line in lines[1:]:
        if line.strip().startswith("reviewed-sha:"):
            sha = line.split(":", 1)[1].strip()
            if sha == head_sha:
                print("APPROVED" if first == APPROVED else "CHANGES_REQUESTED")
                sys.exit(0)

print("PENDING")
