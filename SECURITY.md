# Security Policy

PRJX LP Sentinel is intended to be a read-only monitor.

## Supported use

- Read Project X LP position state through public HyperEVM RPC calls.
- Estimate range status, collectable fees, ROI, APR, and impermanent-loss signals.
- Emit local console output or optional Telegram alerts.

## Out of scope for this repository

- Transaction signing.
- Transaction submission.
- Automated LP entry, exit, mint, burn, collect, swap, or rebalance operations.
- Storing wallet signing material or other sensitive operational values.

## Reporting issues

Please open a GitHub issue for bugs that do not include private wallet details.
For sensitive reports, contact the maintainer privately and avoid posting:

- wallet-specific local configs,
- alert targets,
- `.state/` files,
- signing material,
- API credentials,
- private logs.

## Local configuration safety

The repository intentionally tracks only `config/prjx_lp_monitor.example.json`.
Create `config/prjx_lp_monitor.json` locally and keep it out of Git. The project
`.gitignore` excludes the local config, local override configs, and `.state/`.
