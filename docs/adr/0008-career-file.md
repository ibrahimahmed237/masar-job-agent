# ADR-0008: The career file: facts with ids, written by the person

- **Status:** Accepted
- **Date:** 2026-11-13

## Context

To check a claim, there must be something to check it against. A free-text CV is not that: the same achievement appears in three wordings, and nothing has a name.

## Decision

- The person writes one YAML file: who they are, their limits, and a list of **facts**.
- A fact is one thing that may be claimed: a job, a project, an achievement, a degree. It has an id, a kind, a text, and when they apply: an organization, a role, a period, the skills it shows, and the numbers it may be quoted with.
- Ids are short, stable slugs (`rabbit-inventory`). Documents and assessments point at facts by id.
- Masar reads the file and never writes it.
- Results store the file's checksum, so a result made from an older file is marked.

## Consequences

- **Good:** every claim has an address. "Where does this sentence come from?" always has an answer.
- **Good:** the person controls exactly what can be said about them, once.
- **Cost:** an hour of careful writing before the first use. `masar init` gives a commented example, and `masar profile check` reports what is weak.
