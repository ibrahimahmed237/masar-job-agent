# Review 000 — the design

- **Date:** 2026-11-13
- **Scope:** the high-level design, the low-level designs and the ADRs, before any code.
- **Method:** two passes. First: walk every flow step by step and ask what a wrong model answer, a hostile posting, a second process or a changed file does at that step. Second: read each promise in the design and look for the sentence that would break it.

## Findings, first pass

| # | Area | Finding | Fix |
|---|---|---|---|
| 1 | Truth | The skill check knows only the names in its lexicon. A technology that is in no list ("Temporal", a new framework) written by the model would pass. | A new check, `UNSUPPORTED_TERM`: tokens written like a product name (capitals inside, all capitals, digits or symbols inside) must be in the cited facts. |
| 2 | Truth | A cover letter names the job: "the Senior Backend Engineer role". The title check would flag "Senior" in an honest sentence, and people would learn to ignore the check. | The job's own title and company are masked before any check. |
| 3 | Truth | A plain block may talk about the company ("your 10 million users"). The rule "no numbers in plain blocks" would refuse it; allowing all numbers would let "my 10 years" in. | Numbers and product-like names in a plain block must be in the posting. Skills, the person's employers and seniority words are never allowed there. |
| 4 | Truth | The model does not know the person's name, so it may write `[Your Name]`, or a link taken from the posting. | `PLACEHOLDER` and `FORMAT` violations: no placeholders, no URLs, no HTML, no line breaks in a block. Contacts and links are written by code. |
| 5 | Correctness | The evidence check lowered a `met` when the cited facts lacked the named skill, even when another fact of the person has it. The model's mistake in picking evidence would cost the person a requirement they meet. | The check looks at all the person's facts and adds the ones that have the skill to the evidence. Code still never raises a verdict. |
| 6 | Correctness | A posting titled "Senior" with no number of years raised no flag for a person with two years. | `SENIORITY_ABOVE`, a warning (it is a guess from the title, so it never blocks). |
| 7 | Correctness | A requirement's skill had to be in its quote letter by letter. A model that writes "PostgreSQL" for a posting that says "Postgres" would lose the skill. | The check accepts any alias of the skill. |
| 8 | Correctness | Approving a document while the application was still `found` had no allowed move. | `found → drafted` is allowed, by Masar, on approval. |

## Findings, second pass

| # | Area | Finding | Fix |
|---|---|---|---|
| 9 | Correctness | LangGraph runs an interrupted node again from its start when it resumes. A node that saves the draft and then pauses would save it twice. | The approval node does nothing before the pause. Saving is the use case's job, outside the graph. |
| 10 | Structure | The graphs were going to save to the store themselves, which ties the agent to storage and makes a node hard to test. | The graphs return plain data; `masar.app` saves it. The agent needs only the model port. |
| 11 | Truth | The career file can change between a draft and its approval, for example a fact removed. The draft's checks were made against the old file. | Approval runs the code checks again against the current file, and refuses if a block no longer passes. |
| 12 | Concurrency | The CLI and the MCP server can run at the same time. Two approvals of one draft, or two moves of one application, could both succeed. | Updates name the state they expect, in one transaction with the event; the connection waits for locks. |
| 13 | Correctness | Two fetches, or a paste of a posting already fetched, would make two rows. | A checksum over company, title and text; the existing row is returned. |
| 14 | Correctness | "Digits are numbers" would flag `S3`, `EC2` and `Python 3` in honest sentences. | Digits inside a word, and inside a matched skill, are not numbers. |
| 15 | Security | Answers of the MCP tools carry text from postings into an assistant's context, and two tools spend tokens. | Said in the interface design: posting text is returned as data fields, and the daily token limit is the ceiling for any caller. |
| 16 | Honesty of the docs | The matching page read as if code verified every verdict. It can verify only requirements that name a technology. | The page says what code cannot check, and the job page marks such verdicts "by the model". |

## Checked, no finding

| Check | Result |
|---|---|
| Can the model set a score, a recommendation or a state? | No. It returns verdicts and blocks; code computes and the person decides |
| Can a posting make Masar act? | No. The model has no tools; Masar has no sending code |
| Does any step send contacts or limits to the model? | No. Screening is code; the header is written by code |
| Do the loops end? | The repair loop has a counter and the graph a recursion limit; budgets bound calls, tokens and time |
| Is every part testable with no network and no model? | Yes: a scripted model, recorded job-board answers, a real SQLite file |

## Result

The design changed in 16 places. The pages are updated. Build starts with M0.
