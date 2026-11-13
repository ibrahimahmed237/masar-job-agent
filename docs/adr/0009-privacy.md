# ADR-0009: Least data to the model; everything else stays local

- **Status:** Accepted
- **Date:** 2026-11-13

## Context

A career file holds personal data. A model provider is a third party.

## Decision

| Data | Goes to the model? |
|---|---|
| The posting text | Yes |
| The facts chosen for the step (id, text, skills, organization, role, period) | Yes |
| Name, email, phone, links, address | No. Code adds them to the finished document |
| Limits (visa, salary floor, excluded companies) | No. Screening is code |
| Other postings, the database, earlier documents | No |

- The database, the career file and the exports stay on the machine. Masar has no telemetry.
- Keys come from the environment and are never written to the database or a log.
- The examples and the tests use an invented person.

## Consequences

- **Good:** the provider sees a work history without a name attached by Masar.
- **Cost:** a fact's own text can still identify a person. The person decides what to write in the file, and can use a local model through the same port.
