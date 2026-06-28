# Rebalancing Accounting

The dashboard supports dated portfolio snapshots so a rebalance does not rewrite earlier YTD performance.

## Files

- `backend/portfolios/main.json` is the current or target book.
- `backend/portfolios/main.rebalances.json` is the accounting ledger.

## How It Works

The ledger has frozen snapshots and an `activeConfigEffectiveDate`.

- Before `activeConfigEffectiveDate`, YTD performance uses the frozen snapshot.
- From `activeConfigEffectiveDate` onward, YTD performance uses `main.json`.
- The rebalance segment starts from the previous close before the effective date.
- Old positions can still contribute to YTD after they are removed from `main.json`; their current exposure becomes zero.

## Rebalance Workflow

1. Before changing the book, make sure the old book is frozen in `main.rebalances.json`.
2. Set `activeConfigEffectiveDate` to the trading date when the new book should start counting.
3. Edit `main.json` to the new target book.
4. Run the dashboard and check the header shows `Dated book`.
5. Compare YTD return, YTD contribution, gross exposure, and exited positions before trusting the result.

## Important

Do not delete old tickers from the ledger snapshot. They are needed so first-half results still count after the rebalance.
