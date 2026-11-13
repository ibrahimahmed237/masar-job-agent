# ADR-0006: One SQLite file, plain SQL

- **Status:** Accepted
- **Date:** 2026-11-13

## Context

Masar has one user and one machine. The data is a few thousand rows.

## Decision

- One SQLite file in the Masar folder, in WAL mode, with foreign keys on.
- Plain SQL through the standard `sqlite3` module, behind the store port. No ORM.
- The schema is created by numbered migration scripts, applied at start, recorded in a table.
- JSON columns hold the structured job, the assessment and the document blocks. The columns used for listing and filtering are real columns.

## Consequences

- **Good:** nothing to install or run; backup is copying a file.
- **Good:** the store is tested against a real database file in every test run.
- **Cost:** not built for many users or many writers. That is a non-goal.
