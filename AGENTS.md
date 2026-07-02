# Agent Instructions

## Portfolio History Is Accounting Data

The portfolio files are not ordinary config churn. They are part of the performance audit trail.

- `backend/portfolios/main.json` is the current or target active book.
- `backend/portfolios/main.rebalances.json` is the dated accounting ledger that preserves older books.
- Do not delete old frozen snapshots from `main.rebalances.json`.
- Do not rewrite a past snapshot to make current results look cleaner. Add a new dated change instead.
- Do not force-push or rewrite Git history after portfolio JSON changes unless the user explicitly asks for history surgery.
- When changing the active book, commit `main.json` and `main.rebalances.json` together when both are affected.
- Run `python backend/validate_portfolio_history.py` before committing portfolio changes.
- Use descriptive commit messages for portfolio changes, including the effective date when relevant.

To inspect the historical portfolio state later:

```bash
git log -- backend/portfolios/main.json backend/portfolios/main.rebalances.json
git show <commit-hash>:backend/portfolios/main.json
git show <commit-hash>:backend/portfolios/main.rebalances.json
```
