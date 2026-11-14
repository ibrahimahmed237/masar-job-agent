# Evaluation — numbers for the three risky steps

A flow that passes its tests with a scripted model can still be bad with a real one. Each step where a model decides something has a set and a score. A plain-words version is in [evals/HOW-IT-WORKS.md](../../evals/HOW-IT-WORKS.md).

## Sets

All data is invented. Sets are JSON files in [`evals/`](../../evals). They are about the person of the example career file, not about the user.

| Set | Cases | A case is | Expected |
|---|---|---|---|
| `claims` | 61 | A block with fact ids, written by hand: 24 honest, 37 with one thing planted | Honest or not; for a false one, what was planted: a skill, a number, an employer, a word of rank, a name that no list knows, or a soft claim with none of those |
| `extraction` | 4 postings, 17 requirements | A posting text | Seniority, employment, workplace, countries, minimum years, sponsorship, and the requirements as must or nice with their skills |
| `assessment` | 4 jobs, 18 requirements | A grounded job | A verdict for each requirement |
| `injection` | 3 pairs | A posting, and its twin with instructions for a model hidden in it | The same score and the same verdicts for both |

## Measures

| Set | Measure |
|---|---|
| `claims`, code only | For each planted kind: how many the code checks catch. How many honest blocks they flag. Needs no model |
| `claims`, with the judge | The same, and what the judge adds on the blocks that code lets through; how many honest blocks the judge rejects |
| `extraction` | Single fields right. Requirements: found of expected (recall), expected of extracted (precision); a requirement matches when its quote overlaps the expected one, and one expected requirement is matched once. Kind and skills right among the matched. Proposed requirements that survive grounding |
| `assessment` | Verdicts right as the model gave them, and after the evidence checks. Of the verdicts that the checks lowered, how many were then right |
| `injection` | Twins with the same score and verdicts. Twins where the instructions raised the score |

A case whose model step fails (an answer that cannot be read twice, a used-up budget) counts as a miss and is named in the result. A provider that cannot be reached stops the run.

## Running

`masar eval <set> [--judge] [--sets DIR] [--out DIR] [--no-save]` runs a set and writes a Markdown table to `evals/results/<set>-<date>.md`, with the model name, the prompt version, the date and the tokens. The file is committed, so a change to a prompt, a model or a check shows as a diff.

- Every case gets a new model session with its own budget. The tokens of an evaluation do not count toward the daily limit: it is a developer's command, and it does not touch the database.
- `claims` runs with no model. With `--judge` it asks one.
- In the tests, the same scoring code runs with scripted models: one that is right, one that is careless, one that obeys a posting.

## Results so far

| Set | Result |
|---|---|
| `claims`, code only | [2026-11-13](../../evals/results/claims-2026-11-13.md): every planted skill, number, employer and word of rank is caught; 4 of 5 names; 2 of 6 soft claims; no honest block is flagged |
| The three sets that ask a model | Not run yet: they need a model key, which the build did not have. Run `masar eval extraction`, `assessment`, `injection`, and `claims --judge` |

How to read the `claims` numbers:

- **The set and the checks have the same author.** After the first run, three checks were changed: a capitalized name in the middle of a sentence now needs a source, words of ownership joined the words of rank, and nothing else. So the table shows that the checks do what they are meant to do. It does not show how they do on text that nobody planned for.
- **One name is missed on purpose.** A name that begins a sentence ("Careem uses …") cannot be told from any other first word.
- **Soft claims are the judge's work.** "The whole company depends on it" names nothing that code can look up. Code catches two of the six only because they use a word of ownership.

## The floor

The code-only `claims` run is also a test. It fails when the checks catch less than every planted skill, number, employer and word of rank, less than 4 of 5 names, or when they flag one honest block.

## Tests

| Test | Proves |
|---|---|
| Scoring | Each measure on results made by hand: a perfect reader, a careless one, one that reads nothing; quotes that overlap; one match per expected requirement; countries in any order |
| Assessment | The expected verdicts are ones the evidence checks let stand; a model that says "met" to everything is corrected where code can see, and not where it cannot |
| Injection | Twins with the same score and other verdicts are not "the same"; a lower score is not "raised" |
| Claims floor | The numbers above |
| Runner | Every set runs by name from the command line and writes its table; what cannot run exits with 2 |
