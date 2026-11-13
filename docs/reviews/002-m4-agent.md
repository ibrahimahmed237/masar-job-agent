# Review 002 — M4: the model session and the two flows

- **Date:** 2026-11-13
- **Scope:** `masar.ports` (model, clock), `masar.agent` (session, prompts, fact selection, the intake graph, the tailor graph), the codec for plain data, the scripted model.
- **Method:** the [review checklist](../../CONTRIBUTING.md#review-checklist); each row of the design's test table traced to a test; a pass with one question, "what can a model that does exactly what an attacker wants still change?"; then 68 deliberate bugs.

## Findings

| # | Area | Finding | Fix |
|---|---|---|---|
| 1 | Truth | A block of kind `plain` was checked by code for skills, numbers and names, and was never shown to the judge. "I have deep experience in distributed systems" names nothing code looks for, so a model could say anything soft about the person by calling the block plain. | The judge now gets plain blocks too, with their own question: does it say anything about the candidate? In a CV every block is a claim, whatever it calls itself. |
| 2 | Privacy | The design kept the career file in the graph state. With the SQLite checkpointer, the person's email and phone would have been written into every checkpoint. | The career file, the date and the session are given to the graph when it is built. The state holds only what the run produced. A test reads the checkpoint of a paused run. |
| 3 | Truth | The design ran the check "is this draft still true?" in the use case, before resuming. A second host could forget it. | The check is the `decide` node of the graph. A draft whose fact changed is not approved, and says why. |
| 4 | Security | A posting could contain `</posting>` and continue with text that looks like instructions outside the data block. | Text that looks like a block label is removed from data before it is sent. |
| 5 | Truth | A posting over 30,000 characters is cut for the model, but grounding compared quotes with the whole text. A "quote" could then come from a part the model never read. | Grounding uses the same cut text. |
| 6 | Truth | A repair returns new blocks. If it could set the kind, a failed claim could come back as a plain block and be checked less. | A repair changes the text and the cited facts only. It cannot touch a block that passed. |
| 7 | Truth | A judge's answer was trusted too far: a verdict for a block it was not asked about, or `"supported": "yes"`. | A verdict counts only for a block that was asked about, and only as `true` or `false`. A block with no verdict leaves the document marked as not judged. |
| 8 | Docs | ADR-0012 said a posting's instructions change no score. That is more than the code can promise: a verdict on a requirement with no named technology is the model's reading, and injected text can be quoted as a requirement. | The ADR now lists what an injection can still do, with the bound for each. The tests use a model that obeys the posting in full and assert those bounds. |
| 9 | Cost | After a repair, every block was sent to the judge again. | The same words on the same facts are judged once. Changing only the cited facts counts as a change. |
| 10 | Correctness | A model answer with the wrong shape (a JSON object without `requirements`) failed the run at once, while an answer with no JSON got a second try. | The shape check is part of the same single retry. |
| 11 | Simplicity | Three conditions could never be false where they stood (found by experiments that broke no test). | Removed, and the paths they were meant for now have tests. |

## Experiments

| Result | Count |
|---|---|
| Caught by a test at once | 58 |
| Not caught, test added | 7 |
| Not caught because the code was redundant; code removed | 3 |

The seven: the token budget counted only tokens received; a repair that relabels a claim as plain; the judge being asked again after it had stopped; a repair being tried after the judge had stopped; a plain block using a number from the posting; the judge's memory keyed by text alone; `all_skills` lost on the way to plain data.

## Checked, no finding

| Check | Result |
|---|---|
| Does any prompt hold the name, email, phone, links, city or limits? | No, on every recorded call of both flows, including repairs |
| Can a run be approved without a decision? | No. `approved` is set in one place, after an `approve` that passed the checks |
| Can a decided draft be decided again? | No: `NotPaused` |
| Does a paused run survive a restart? | Yes: a new connection, a new graph object, a model that would fail if asked |
| Is the loop bounded? | Twice: two repairs, and a recursion limit of 25 |
| Does the agent layer touch the disk or the network? | No: the architecture test passes; the checkpointer is handed in |

## Result

316 tests pass. Line coverage is 98% overall, 98% in the domain. Ruff and mypy (strict) are clean.
