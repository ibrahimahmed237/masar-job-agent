# Matching — screen, evidence checks and score

All of this is code in `masar.domain`, with no model ([ADR-0007](../adr/0007-score-by-code.md)).

## Screen

`screen(job, career, today)` returns flags. A **blocker** means "skip unless you know better". A **warning** means "look at this".

| Flag | Severity | When |
|---|---|---|
| `COMPANY_EXCLUDED` | blocker | The company is in `limits.exclude_companies` (compared case-folded) |
| `EMPLOYMENT_NOT_WANTED` | blocker | The job's employment type is known and not in `limits.employment` (when that list is not empty) |
| `REMOTE_NOT_WANTED` | blocker | The job is remote and `limits.remote` is false |
| `COUNTRY_NOT_WANTED` | blocker | The job is not remote, every location has a country, and none is in `limits.countries` (when that list is not empty) |
| `NO_RELOCATION` | blocker | The job is on-site or hybrid, none of its countries is the person's own, and `limits.relocation` is false |
| `SPONSORSHIP_NOT_OFFERED` | blocker | The job is not remote, none of its countries is in `work_authorization`, and the posting says it does not sponsor |
| `SPONSORSHIP_UNKNOWN` | warning | The same, and the posting does not say |
| `YEARS_FAR_BELOW` | blocker | The posting asks for more years than the person has plus `years_gap_allowed` |
| `YEARS_BELOW` | warning | The posting asks for more years than the person has, within the allowed gap |
| `SENIORITY_ABOVE` | warning | The posting gives no number of years, and its seniority usually means more than the person has plus the allowed gap (junior 0, mid 2, senior 5, lead 7, principal 10). A warning, because it is a guess |
| `LANGUAGE_MISSING` | blocker | A required language is not among the person's languages |
| `REMOTE_REGION` | warning | The job is remote but names countries, and none is in `work_authorization` |
| `LOCATION_UNKNOWN` | warning | The job is not remote and has no location with a country |
| `WORKPLACE_UNKNOWN` | warning | The workplace type is unknown |

Rule of thumb: **missing information never blocks.** A posting that does not say is a warning.

- When the workplace type is unknown, the job may be remote. The location rules (`COUNTRY_NOT_WANTED`, `NO_RELOCATION`, `SPONSORSHIP_NOT_OFFERED`) then give warnings with the same codes instead of blockers.
- When the career file lists no languages, the language rule is skipped. When it lists no `work_authorization`, a job abroad gives `SPONSORSHIP_UNKNOWN`, whatever the posting says.

A cheaper filter runs before any model call, on the posting's title alone: `title_matches(title, limits)` keeps a title that contains one of `title_keywords` (when not empty) and none of `title_exclude`.

## Evidence checks

The assess step returns, for each requirement, a verdict and fact ids. `check_evidence(job, career, raw_assessment)` returns the assessment that code can stand behind.

| # | Check | Result |
|---|---|---|
| E1 | A fact id that is not in the career file | Removed from the evidence (`EVIDENCE-UNKNOWN-FACT`) |
| E2 | `met` or `partial` with no evidence left | `missing` (`EVIDENCE-NONE`) |
| E3 | The requirement names skills | The person's facts that have those skills are added to the evidence. `met` stays only if the person has one of the skills (all of them when `all_skills`). With some of the skills it becomes `partial`. With none of them it becomes `missing`: the model said something that code can see is false, and nothing of it stands (`EVIDENCE-SKILL`). A `partial` from the model for a skill the person lacks stays: "something close" is a judgement, and it is never more than partial |
| E4 | A requirement the model did not assess | `missing`, by code (`EVIDENCE-NOT-ASSESSED`) |
| E5 | An assessment for a requirement that does not exist, or a second one for the same requirement | Ignored (`EVIDENCE-UNKNOWN-REQUIREMENT`) |
| E6 | A note longer than 300 characters | Cut |
| — | The model says `missing` for a requirement that names a skill the person has | The verdict stays `missing`, and a warning says which facts show the skill (`EVIDENCE-OVERLOOKED`) |

Code only lowers a verdict. Nothing in this step can turn `missing` into `met`. It may add evidence that it can verify itself (E3). Each entry says who decided it (`model`, or `code` with the verdict it was lowered from).

What code cannot check: a verdict on a requirement that names no technology ("a degree in computer science", "experience with large teams"). Such a verdict is the model's reading of the cited facts, and the job page shows it as "by the model".

## Score

| Verdict | Value | | Kind | Weight |
|---|---|---|---|---|
| `met` | 1 | | must-have | 3 |
| `partial` | 0.5 | | nice-to-have | 1 |
| `missing` | 0 | | | |

`score = round(100 × Σ(weight × value) / Σ(weight))`. A job with no requirements has no score.

| Recommendation | When |
|---|---|
| `skip` | Any blocker flag, or a score under 50 |
| `maybe` | No blocker, score 50 to 69, or no score |
| `apply` | No blocker, score 70 or more |

The two limits (50, 70) and the two weights are settings.

## Tests

| Test | Proves |
|---|---|
| One case per flag | It fires when it should, and not when the information is missing |
| Evidence checks | Each of E1 to E6; code never raises a verdict (property test over random assessments) |
| Score | Known cases by hand; always 0 to 100; replacing a verdict with a better one never lowers the score (property test) |
| Recommendation | Each row of the table, and the edges at 50 and 70 |
