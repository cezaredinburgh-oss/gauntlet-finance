# Gauntlet Finance App – Project Rules

## Ports
- Backend API: 8020
- Frontend: 5190
Document any deviation.

## Non-negotiables
- Statements-only ledger (Bank statements/ or fixtures). Never import from external portfolio apps.
- Google Sheets is the primary store (service account). InMemory only for tests.
- Decimal for all money. Never float.
- Internal transfers must set is_internal_transfer = true and must not affect income/expense.
- Revolut crypto Buys: qty_net = qty_gross * (1 - fees/value)
- Digital Assets Europe cash legs → internal + Crypto funding category.
- Czech 3-year (1095 days) tax exemption tracked on open lots.
- Transaction rows: statement-native amount + currency; historical secondary only when stored (never invent FX). Dashboard / spend totals: USD.
- Dark Desk-like glass theme. Home = executive summary.

## Process
- Follow the Gauntlet Loop in the prompt: design first, adversarial review to zero open issues, then PR-sized implementation.
- When unsure of a formula, read the Collective reference app first, then improve and note the deviation in docs/BUILD_LOG.md.
- Never commit secrets or real .env files.
- Prefer simple readable code.

## Commands
- Backend tests: pytest
- Frontend typecheck/build: as defined in package.json