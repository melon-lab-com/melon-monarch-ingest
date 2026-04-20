# Architecture Decision Records

Captured decisions live here, one per file. Format: [MADR](https://adr.github.io/madr/)-lite.

Filename: `NNNN-kebab-title.md`, where `NNNN` is a zero-padded sequence
number. Once merged, ADRs are append-only — supersede them with a new
ADR rather than editing the old one.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-stack-choice.md) | Core stack: Python 3.12, SQLite, FastAPI, HTMX, uv | Accepted |
| [0005](0005-branch-protection-deferred.md) | Server-side branch protection on `main`: deferred | Accepted |
| [0006](0006-cloud-deployment-target.md) | Cloud deployment: Hetzner VPS + Kamal 2 + SQLite | Accepted |
| [0007](0007-account-identity-and-content-hash.md) | Account identity: drop `UNIQUE(mask)`, rewrite `content_hash` with canonical account name | Accepted |
| [0008](0008-auth-strategy.md) | Authentication: Tailscale edge + self-hosted session cookie | Accepted |
