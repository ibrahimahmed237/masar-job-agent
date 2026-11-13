# Review 005 — M7: evaluations

- **Date:** 2026-11-13
- **Scope:** the four evaluation sets, the scoring in `masar.app.evaluation`, the set files in `masar.adapters.evalsets`, the command `masar eval`, and what the first run of the claims set changed in the domain.
- **Method:** the [review checklist](../../CONTRIBUTING.md#review-checklist); each measure computed by hand for a scripted model and compared; the claims set written before looking at what the checks do with it; then 29 deliberate bugs.

## What the first run of the claims set showed

The set was written first, then run. Three things came out, and each changed code.

| # | Area | Finding | Fix |
|---|---|---|---|
| 1 | Truth | "At Google I built …" passed every check. Google is not an employer of the career file, so the employer rule did not look at it, and it is written like an ordinary word, so the product rule did not either. The same for "on Qdrant", "on Temporal", "in Berlin". | A capitalized word that does not begin a sentence is a name, and a name must be in the cited facts (or be a language the career file lists; in a plain block, be in the posting). 4 of the 5 planted names are now caught. The fifth begins its sentence, which is a limit that stays, and is written down. |
| 2 | Truth | "I owned payments" passed. The prompt tells the model that `owned` is a word of ownership; the check did not know it. | `owned`, `owner`, `ownership`, `responsible for`, `in charge of`, `headed`, `supervised`, `mentored`, and two Arabic forms, joined the words of rank. |
| 3 | Docs | The design listed `leading`, `staff`, `head` and `managing` as checked words. The code never had them. | The design now lists exactly the words the code checks. |

## What writing the assessment tests showed

| # | Area | Finding | Fix |
|---|---|---|---|
| 4 | Truth | A model that says `met` for a technology the person does not have at all was lowered to `partial`, and kept half of the weight. In the test with a model that says `met` to everything, three such verdicts were "lowered" and still wrong. | With none of the named skills, `met` becomes `missing`. With some of them it becomes `partial`. A `partial` from the model stays the model's call. The same test now ends with the three verdicts right. |

## Other findings

| # | Area | Finding | Fix |
|---|---|---|---|
| 5 | Honesty | A table of 100% rows invites a wrong reading. The set and the checks have one author, and checks were changed after the first run. | The design page says this next to the numbers, and says what the numbers do and do not show. |
| 6 | Honesty | Three of the four sets need a model. The build had no key, so there is no result for them. | The design page says "not run yet" and gives the commands. No number was made up. |
| 7 | Correctness | Two extracted requirements that both overlap one expected quote would both count as found, and recall could pass 100%. | One expected requirement is matched once. |
| 8 | Correctness | A case whose model step fails would have ended the whole run. | It counts as a miss and is named. Only a provider that cannot be reached stops the run. |
| 9 | Design | An evaluation should not eat the day's tokens or write into the person's database. | It builds its own sessions, uses the example career file, and touches no store. The command says so. |

## Experiments

| Result | Count |
|---|---|
| Caught by a test at once | 21 |
| Not caught, test added | 7 |
| Pattern not found (the code had been reformatted), repeated and caught | 1 |

The seven were all in the scoring: a judge that gives no verdict counted as a rejection; quotes compared by equality in place of overlap; countries compared in order; a lowered verdict counted as right without looking; twins compared by score alone; any change of score counted as "raised"; tokens of the last case in place of the sum.

## Checked, no finding

| Check | Result |
|---|---|
| Is any data in the sets real? | No: every person, company and posting is invented |
| Do the expected verdicts of the assessment set contradict the evidence checks? | No: a model that gives exactly the expected verdicts keeps all 18 after the checks |
| Do the twins of the injection set differ only by the hidden instructions? | Yes: a test compares them line by line |
| Does the claims floor fail when a check gets weaker? | Yes: removing the name rule, the ownership words or the month list each breaks a test |

## Result

Tests pass. Line coverage is 99% overall. Ruff and mypy (strict) are clean.
