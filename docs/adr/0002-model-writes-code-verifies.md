# ADR-0002: The model writes, the code verifies

- **Status:** Accepted
- **Date:** 2026-11-13

## Context

A model writes fluent text and invents details with the same fluency. In a CV or a cover letter, an invented skill, number, employer or title is a lie with the candidate's name under it.

## Decision

A fixed line separates the two:

| Task | Who does it |
|---|---|
| Read a posting into fields | Model, into a fixed schema, with a quote for every requirement |
| Decide that a quote is really in the posting | Code |
| Check hard limits (location, visa, seniority, language) | Code |
| Judge one requirement against the facts | Model, with fact ids as evidence |
| Decide that the evidence exists and covers a named technology | Code |
| Compute the score and the recommendation | Code ([ADR-0007](0007-score-by-code.md)) |
| Write sentences for a document | Model, as blocks that name their facts |
| Decide that a block may stay | Code first (technologies, numbers, employers, seniority words), then a model judge |
| The header, contacts, education, skills list | Code, from the career file |
| Approve a document, move an application | The person ([ADR-0003](0003-no-outside-actions.md)) |

More rules:

- Every model output is parsed and checked before use. Output that does not fit the schema is an error, not a guess.
- A block that fails a check is repaired or removed. It is never kept "because it is probably fine".
- The model judge can only make the result stricter. It cannot bring back a block that the code checks removed.

## Consequences

- **Good:** the worst a wrong model answer can do is cost a retry or shorten a document.
- **Good:** the checks work the same with any model, and are tested with none.
- **Cost:** word lists make mistakes. A correct sentence can be flagged; the evaluation measures how often.
- **Watch:** a false claim with no technology, number, employer or title in it passes the code checks. The judge and the person are the answer, and the docs say so.
