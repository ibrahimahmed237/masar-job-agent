# ADR-0007: The score is computed by code from per-requirement verdicts

- **Status:** Accepted
- **Date:** 2026-11-13

## Context

A model asked for "a match score from 0 to 100" gives a number that cannot be explained, changes between runs, and can be pushed up by a sentence in the posting.

## Decision

- The model gives one verdict per requirement: `met`, `partial` or `missing`, with fact ids as evidence.
- Code checks the evidence and may lower a verdict. It never raises one.
- The score is `100 × Σ(weight × value) / Σ(weight)`, with `met = 1`, `partial = 0.5`, `missing = 0`, weight 3 for a must-have and 1 for a nice-to-have.
- The recommendation comes from the score and the screen flags: a blocker means `skip`; else `apply` from 70, `maybe` from 50, `skip` below. The limits are settings.
- A job with no requirements has no score.

## Consequences

- **Good:** every score can be shown as a table of requirements, verdicts and facts.
- **Good:** the same verdicts always give the same score.
- **Cost:** the weights are simple. They are settings, and the evaluation shows if a change helps.
