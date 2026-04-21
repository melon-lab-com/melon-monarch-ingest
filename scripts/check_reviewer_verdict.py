"""Read PR comments from $COMMENTS_JSON and match the sentinel for $HEAD_SHA.

Prints APPROVED / CHANGES_REQUESTED / PENDING and exits 0.
Called by .github/workflows/code-reviewer-gate.yml.

Rules:
- "body": null comments (deleted) are silently skipped.
- The last matching verdict for $HEAD_SHA wins (a CHANGES REQUESTED posted
  after an APPROVED for the same SHA revokes the approval).
- No author check: this is a solo-contributor repo; the code-reviewer agent
  runs as the repo owner and posts verdicts under their account. The SHA
  anchor is the meaningful integrity mechanism. For multi-contributor repos
  add: `if comment.get("author") == os.environ.get("PR_AUTHOR"): continue`.
"""

import json
import os

head_sha = os.environ["HEAD_SHA"]
comments: list[dict[str, str | None]] = json.loads(os.environ["COMMENTS_JSON"])

APPROVED = "[code-reviewer] verdict: APPROVED"
REJECTED = "[code-reviewer] verdict: CHANGES REQUESTED"

result: str | None = None

for comment in comments:
    body = comment.get("body")
    if not body:
        continue
    lines = body.strip().splitlines()
    if not lines:
        continue
    first = lines[0].strip()
    if first not in (APPROVED, REJECTED):
        continue
    for line in lines[1:]:
        if line.strip().startswith("reviewed-sha:"):
            sha = line.split(":", 1)[1].strip()
            if sha == head_sha:
                # Keep iterating — last matching verdict wins.
                result = "APPROVED" if first == APPROVED else "CHANGES_REQUESTED"
                break

print(result if result is not None else "PENDING")
