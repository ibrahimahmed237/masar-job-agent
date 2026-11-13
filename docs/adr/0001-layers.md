# ADR-0001: A pure domain, ports, thin hosts

- **Status:** Accepted
- **Date:** 2026-11-13

## Context

The rules that keep Masar honest (screening, scoring, claim checks) must be easy to test and impossible to skip. If they live inside a graph node or a CLI command, a second caller will forget one.

## Decision

| Layer | Package | May import |
|---|---|---|
| Hosts | `masar.cli`, `masar.mcp_server` | Everything |
| Adapters | `masar.adapters` | Everything below |
| Use cases | `masar.app` | `agent`, `ports`, `domain` |
| Agent | `masar.agent` | `ports`, `domain` |
| Ports | `masar.ports` | `domain` |
| Domain | `masar.domain` | Nothing of ours |

- The domain has no I/O, no clock, no network and no model. It imports the standard library and Pydantic.
- LangGraph is imported only in `masar.agent`. SQLite and HTTP only in `masar.adapters`.
- A test reads the imports of every source file and fails on a forbidden one.

## Consequences

- **Good:** every rule runs in a unit test with no setup, and every host gets the same rules.
- **Good:** the model, the database and the job boards can each be replaced by a fake.
- **Cost:** some wiring code in `masar.app` that a smaller tool would not need.
