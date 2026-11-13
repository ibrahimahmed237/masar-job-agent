# Review 001 — M0 to M3: foundation and the domain

- **Date:** 2026-11-13
- **Scope:** the package and its tooling; `masar.domain`: the career file, skills, postings and jobs, application states, screening, evidence checks, the score, the claim checks, document assembly.
- **Method:** the [review checklist](../../CONTRIBUTING.md#review-checklist); every rule of the low-level designs traced to a test; then 62 deliberate bugs, each a small change to one rule, to see that a test fails.

## Findings

| # | Area | Finding | Fix |
|---|---|---|---|
| 1 | Truth | The person's years of experience were allowed as a number in any claim. For a person with five years, "improved it by 5%" passed with no fact behind it. | The number is allowed only when it is said as years: "5 years", "5+ years of", "five years", "5 سنوات". |
| 2 | Truth | Skill names that are everyday words would be found in honest sentences ("a three-node cluster", "take a rest", "the ml team"), and a writer would learn to ignore the check. | Such names, and the aliases marked for it (`Node`, `REST`, `ML`, `JS`), match only in their exact spelling. |
| 3 | Truth | "Series C" and "R&D" were the C and R languages. | Single-letter names are skills when listed, and are not looked for in running text. |
| 4 | Truth | `Main.java` and `server.go` were Java and Go. | A name directly after a dot is a file ending. |
| 5 | Truth | Numbers with a unit glued on ("3x", "200ms") were not seen as numbers at all, so "3x faster" needed no fact. | A number may carry a unit; digits inside a name (`S3`, `EC2`) are still not numbers. |
| 6 | Truth | "AI-powered" was one token, so the check asked for the whole word in the facts and always failed; "TCP/IP" the same. | `-` and `/` split tokens for the product-name check. |
| 7 | Correctness | A posting that does not say if a job is remote was treated as on-site, so its country could block it. That breaks "missing information never blocks". | With an unknown workplace, the location rules warn instead of block. |
| 8 | Correctness | A person who lists no languages was blocked from every posting with a required language; one who lists no work authorization was treated as needing a visa everywhere, silently. | The language rule is skipped when the file lists none. No work authorization gives a warning that says so. |
| 9 | Correctness | The title filter matched inside words: "intern" excluded "Internal Tools Engineer". | Whole words only; a hyphen inside a word is ignored ("Back-end"). |
| 10 | Correctness | A quote of one letter is "in the posting" by accident, so a made-up requirement could keep it. | Quotes shorter than 12 characters are refused. |
| 11 | Design | The model's own title and company for the job were going to be kept. They are one more thing to trust for no gain. | The title and company come from the posting record. |
| 12 | Usefulness | When the model says `missing` for a skill the person has, code must not raise the verdict, but saying nothing hides a miss. | The verdict stays; a warning names the facts that show the skill. |
| 13 | Tests | Seven deliberate bugs broke no test: the boundary after a dot, the quote check of the years, rounding of the score, a product name in a plain block, and three others. | A test for each (see below). |

## Experiments

| Result | Count |
|---|---|
| Caught by a test at once | 55 |
| Not caught, test added | 4 |
| Pattern not found (the code had been reformatted), repeated and caught | 3 |

The four that were not caught: a name after a dot (finding 4); the years quote not being in the posting; the score rounding down instead of half up; a product-like name in a plain block that is not in the posting.

## Checked, no finding

| Check | Result |
|---|---|
| Can a check raise a verdict? | No. A property test over 300 random assessments shows every verdict is equal or lower, and every remaining verdict has evidence that exists |
| Does a block made of a fact's own words pass? | Yes, for every fact of the example file, whole and in random mixes of its words |
| Is the score in range and monotonic? | Yes, by property test: a better verdict never lowers it |
| Does the domain do I/O? | No: the architecture test forbids it, and was shown to fail on a planted import |
| Do contact details print? | `Person` prints as `Person(***)` |

## Result

223 tests pass. Domain line coverage is 98%. Ruff and mypy (strict) are clean.
