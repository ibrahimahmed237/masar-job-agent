# Evaluation — numbers for the three risky steps

A flow that passes its tests with a scripted model can still be bad with a real one. Each step where a model decides something has a set and a score.

## Sets

All data is invented. Sets are JSON files in `evals/`.

| Set | A case is | Expected |
|---|---|---|
| `extraction` | A posting text | Seniority, workplace, countries, minimum years, sponsorship, and the requirements as a list of must/nice with their skills |
| `assessment` | A grounded job and a career file | A verdict for each requirement |
| `claims` | A block with fact ids, written by hand: some honest, some with a planted false skill, number, employer or title, some false with none of those | Honest or not, and for the dishonest ones which kind |
| `injection` | A posting with hidden instructions, and its twin without them | The same score and the same verdicts for both |

## Scores

| Set | Score |
|---|---|
| `extraction` | Field accuracy for the single fields; precision and recall of requirements (a requirement matches when its quote overlaps the expected one); share of quotes that survive grounding |
| `assessment` | Agreement with the expected verdicts, before and after the evidence checks; the number of verdicts the checks lowered |
| `claims`, code only | Recall on planted false claims by kind; the share of honest blocks wrongly flagged. Needs no model, so it also runs as a test with a floor |
| `claims`, with the judge | The same, plus recall on the false claims that code cannot see |
| `injection` | The share of twins with identical results |

## Running

`masar eval <set>` runs a set with the configured model and writes a Markdown table to `evals/results/<set>-<date>.md`, with the model name, the prompt version, the date and the tokens. The file is committed, so a change to a prompt or a model shows as a diff.

In the tests, the same scoring code runs with a scripted model, to prove the scoring itself.

## Tests

| Test | Proves |
|---|---|
| Scoring | Each metric on hand-made results: perfect, empty, partly right |
| Claims floor | The code checks catch every planted skill, number, employer and title in the set, and wrongly flag at most the allowed share of honest blocks |
| Runner | A set runs end to end with a scripted model and writes its table |
