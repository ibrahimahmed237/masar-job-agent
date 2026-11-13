# Glossary

| Word | Meaning |
|---|---|
| **Career file** | The YAML file the person writes: who they are, their limits, their facts |
| **Fact** | One thing that may be claimed about the person: a job, a project, a degree. It has an id |
| **Limits** | What the person will not accept: countries, remote or not, relocation, employment type |
| **Posting** | A job advertisement as published: raw text |
| **Job** | The structured reading of a posting: seniority, workplace, locations, requirements |
| **Requirement** | One thing a posting asks for, with the quote it comes from. A must-have or a nice-to-have |
| **Quote** | The exact words of the posting that a requirement or a field rests on |
| **Grounding** | Checking that something is supported by its source: a requirement by the posting, a claim by the facts |
| **Screen** | The check of a job against the person's limits. It returns flags |
| **Flag** | One result of the screen: a blocker or a warning |
| **Verdict** | `met`, `partial` or `missing`, for one requirement |
| **Evidence** | The ids of the facts that support a verdict |
| **Assessment** | The verdicts of all requirements of a job, after the evidence checks |
| **Score** | A number from 0 to 100, computed by code from the verdicts |
| **Recommendation** | `apply`, `maybe` or `skip`, from the score and the flags |
| **Block** | One sentence, bullet or paragraph of a draft, with the facts it rests on |
| **Claim** | A statement about the person. A claim block must name its facts |
| **Violation** | A reason a block may not stay: an unsupported skill, number, employer or title |
| **Judge** | A second model call that says if a block is supported by its facts |
| **Draft** | A document that waits for the person's decision |
| **Document** | A CV, a cover letter or an outreach message, as Markdown |
| **Application** | The person's progress with one job: found, shortlisted, drafted, applied, … |
| **Watchlist** | The companies whose public job boards Masar reads |
| **Run** | One execution of a flow, with its trace |
| **Trace** | The saved steps of a run: model, tokens, time, output |
| **Checkpoint** | The saved state of a paused flow |
| **Lexicon** | The skill names Masar looks for in a text: the person's, the job's, and a built-in table |
