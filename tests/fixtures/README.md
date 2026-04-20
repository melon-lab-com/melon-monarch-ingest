# Test fixtures

Synthetic data only. Everything here is made up — fake merchants, fake
account masks, fake amounts, fake rental property, fake household members
(Alice, Bob, Shared). Used for unit and integration tests.

**Do not replace these with real Monarch exports.** The repo's pre-commit
guard will refuse any file matching `Transactions_*.csv` / `Balances_*.csv`
anywhere in the tree, including this directory.

## Files

- `sample_transactions.csv` — mirrors the Monarch transactions export schema
  (`Date, Merchant, Category, Account, Original Statement, Notes, Amount,
  Tags, Owner`). Covers: income, outflow, shared vs per-owner, transfers,
  credit-card payment pair, a refund (positive amount for otherwise outflow
  merchant), repeated merchants (for dedup tests), commas inside quoted
  fields, empty notes/tags, rental income.
- `sample_balances.csv` — mirrors the Monarch balances export schema
  (`Date, Balance, Account`). Three monthly snapshots across five accounts
  including a credit card (negative) and a fixed-book-value rental
  property.
