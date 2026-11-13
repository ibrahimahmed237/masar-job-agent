# Review 006 — M8 and the final review

- **Date:** 2026-11-13
- **Scope:** everything: the code of all packages, the designs, the decisions, the README, the sets, the commits.
- **Method:** a pass over every place where text from outside enters or leaves (postings, model answers, files, the terminal, tool answers); the whole source searched for anything that acts on the outside world; the package built and installed into a clean environment; every design page read against the code; the demo written as a script and read as a user would read it; then 16 deliberate bugs.

## Findings

| # | Area | Finding | Fix |
|---|---|---|---|
| 1 | Security | A posting is printed in a terminal and returned to assistants. It could hold control characters (an escape sequence recolours or hides text) and the marks that reorder text on screen. | Text from outside is cleaned when it is let in, for pasted and fetched postings alike. What a model writes about a requirement is cleaned the same way. A block that holds such a character is a `FORMAT` violation. |
| 2 | Security | The company name of a posting goes into the greeting of a letter. `[Evil](https://…)` or `<b>` in it would become markup in the exported document. | The name goes in as a name: the characters Markdown and HTML act on are removed. |
| 3 | Security | The address of a posting was stored as given, `javascript:` and `file:` included. | Only `http://` and `https://` addresses are kept. |
| 4 | Secrets | `masar config` hides the key, but an address like `https://user:password@proxy/v1` was printed whole. | The part before `@` is shown as `***`. |
| 5 | Truth | The prompts told the model which words need a fact, and did not mention names, which the checks now look for. A model that is not told a rule breaks it and pays in repairs. | The rule names "a name of any kind". The prompt version was raised. |
| 6 | Honesty | The tagline was "a job-hunt agent that cannot invent claims". Section 13 of the design says, rightly, that Masar does not prove a document true. | "…that may only say about you what you wrote yourself", and the README has a section on what Masar does not promise, with the two things that get past the code checks. |
| 7 | Honesty | Nothing said plainly that no real model has run yet. | The README and the status page say it, with the commands that would change it. |
| 8 | Docs | Pydantic was a dependency, a mypy plugin, and "what the domain imports" in four pages. The code never used it. | Removed from the package and from the pages. |
| 9 | Docs | The main design was behind the build in six places: a config file that does not exist, `today` listing new jobs, "a posting cannot raise its own score", "recorded answers", a list of commands without `facts`, `config` and `check`, and a tailor diagram without the edit path. | Each brought in line. The claim about scores now points to [ADR-0012](../adr/0012-untrusted-postings.md), which lists what an injection can still do. |
| 10 | Correctness | A fetched posting that is empty after cleaning, or far too long, was dropped without being counted. | It counts as skipped, and the report shows it. |
| 11 | Tests | Two test files held a real invisible character where an escape was meant. | Written as escapes. A test now searches every text file of the repository for characters that cannot be seen. |
| 12 | Usability | Output had trailing spaces; an education line read "BSc in Computer Science. — Cairo University". | Lines are trimmed; the full stop goes when more follows. Both were seen in the demo page. |
| 13 | Process | The commit subjects were noun phrases, some over 72 characters. [CONTRIBUTING](../../CONTRIBUTING.md#commits) asks for the imperative and 72. | Rewritten before the first push. Nothing had been published. |
| 14 | Process | CONTRIBUTING said expected failures are results, never exceptions. That is the rule of the domain; the use cases raise `Refused` and `AppError`. | The page now says which rule holds where. |

## The demo

[docs/demo.md](../demo.md) is written by [scripts/demo.py](../../scripts/demo.py). A test runs the script and compares, so the page cannot go stale. The model of the demo makes five mistakes on purpose, and the page shows what becomes of each.

## Checked, no finding

| Check | Result |
|---|---|
| Can any code act on the outside world? | No module imports a way to: no process, mail, browser or socket. The only network calls are one GET to a job board and one POST to a model. Three tests now hold this |
| Can an assistant decide anything? | The server's source never calls `decide`, `approved_document`, `move_application` or `fetch`. A test reads the source to see |
| Does the built package work outside the repository? | Yes: the wheel holds the migration and the two templates; `masar init`, `profile check`, `check` and `masar-mcp` ran from a clean environment |
| Does any prompt, tool answer, checkpoint or error hold the name or the contacts? | No, by the tests of M4 and M6, read again |
| Is anything real in the repository? | No: the person, the companies, the postings and the board answers are invented. A test checks the ignore rules and the sets |
| Does every design page match the code? | After finding 9, yes. The link checker passes on every page and every diagram renders |

## Experiments

| Result | Count |
|---|---|
| Caught by a test at once | 15 |
| Not caught, test added | 1 |

Over the whole project: 258 deliberate bugs. 229 were caught by a test (4 of them on a second try, after the code they aimed at had been reformatted). 25 broke no test and got one. 4 showed code that was not needed, which was removed.

## What is left

Only the owner can do these. None blocks reading or using the code.

| # | What | Why it waits |
|---|---|---|
| 1 | A first run with a real model, on real postings | It needs a model key |
| 2 | Results for `extraction`, `assessment`, `injection` and `claims --judge` | The same |
| 3 | The name | "Masar" is a working name |

## Result

654 tests pass. Line coverage is 99% overall and 98% in the domain. Ruff and mypy (strict) are clean.
