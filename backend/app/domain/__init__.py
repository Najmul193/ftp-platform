"""Pure domain layer.

This package MUST NOT import from `app.models`, `app.repositories`, `app.api`
or any other infrastructure package. It contains only pure functions and value
objects over `Decimal`, which is what makes the parity suite (docs plan §16)
runnable in CI with no database.

The rule is enforced by import-linter; see `.importlinter`.
"""
