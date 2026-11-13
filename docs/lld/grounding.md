# Grounding — the claim checks and the document

The promise: **no sentence about the candidate reaches a document without a fact behind it** ([ADR-0002](../adr/0002-model-writes-code-verifies.md)). This page is the code that keeps it. It lives in `masar.domain` and needs no model.

## Blocks

A model writes a document as a list of blocks.

| Field | Meaning |
|---|---|
| `section` | Where the block goes: `summary`, `experience`, `project`, `body` |
| `fact` | For `experience` and `project`: the fact this bullet belongs to |
| `kind` | `claim`: says something about the candidate. `plain`: interest in the company, a sentence about the role, a closing. Anything that is not clearly `plain` is a claim. In a CV every block is a claim, whatever it calls itself: only a letter has room for a sentence that is not about the person |
| `text` | The sentence or bullet |
| `facts` | The ids of the facts the text rests on |

## Checks

`check_block(block, career, lexicon, today)` returns violations. `check_document` runs it on every block and adds the document-level checks.

| Code | Applies to | Violation |
|---|---|---|
| `UNKNOWN_FACT` | any | A fact id that is not in the career file |
| `CLAIM_WITHOUT_FACT` | claim | No fact ids |
| `WRONG_SECTION_FACT` | experience, project | The block's `fact` is not among its `facts`, or is not a fact of that kind |
| `UNSUPPORTED_SKILL` | claim | A skill found in the text is not a skill of the cited facts |
| `UNSUPPORTED_TERM` | claim | A product-like name in the text (see below) is not in the cited facts |
| `UNSUPPORTED_NUMBER` | claim | A number in the text is not in the cited facts' text or periods, and is not the person's years of experience |
| `NUMBERS_NOT_WANTED` | claim | `style.metrics` is off and the text has a number other than the years of experience |
| `UNSUPPORTED_ORG` | claim | An organization of the career file is named, and no cited fact belongs to it |
| `UNSUPPORTED_TITLE` | claim | A seniority or ownership word is in the text and in none of the cited facts |
| `PLAIN_BLOCK_CLAIMS` | plain | A plain block contains a skill, an organization of the career file or a seniority word; or a number or product-like name that is not in the posting |
| `PLACEHOLDER` | any | Text such as `[Your Name]`, `{company}` or `XXX` |
| `FORMAT` | any | A line break, a URL, an HTML tag, or Markdown control characters at the start |
| `WRONG_LANGUAGE` | any | An Arabic document's block has no Arabic letters, or an English document's block is mostly Arabic |
| `TOO_LONG` | any | Over the limit for its place (see below) |
| `WRONG_SECTION` | any | A section the document does not have: a `body` block in a CV, a `summary` in a letter |

### How each thing is found in a text

Before anything is looked for, the job's own title and company name are masked in the text. "The Senior Backend Engineer role at Acme" is not a claim to be senior.

| Thing | How |
|---|---|
| Skills | The skill matcher of the [domain](domain.md#skills), with the lexicon: the person's skills, the job's skills, the built-in table |
| Product-like names | Tokens that are written like a name of a product or a technology and are not in the lexicon: all capitals with 2 to 6 characters (`AWS`, `ETL`), capitals or digits inside the word (`GraphQL`, `gRPC`, `OAuth2`, `3x`), or a dot between two words (`socket.io`). `-` and `/` split tokens, so `AI-powered` is checked as `AI`. Everyday short forms are allowed (`API`, `UI`, `CV`, `KSA`, `B2B`, …). This catches a technology that no list knows |
| Numbers | Digits in Latin or Arabic-Indic form, with `%`, `+`, `k`, `x`, decimal points and ranges; and the number words `dozen`, `decade`, `hundred`, `thousand`, `million`, and "two … fifteen" directly before "year". Digits inside a word (`S3`, `EC2`) and inside a matched skill are not numbers |
| Organizations | The `org` names of the career file, as whole phrases, case folded |
| Seniority and ownership words | `senior`, `lead`, `led`, `leading`, `principal`, `staff`, `head`, `manager`, `managed`, `managing`, `director`, `architect`, `expert`, `chief`, `founder`, `co-founder`, and the Arabic `قائد`, `قدت`, `أدرت`, `مدير`, `خبير`, `كبير` |

A product-like name "is in a fact" when the same token, case folded, is in the fact's text, its skills, its organization or its role.

A number "is in a fact" when the same number, normalized (`93%` = `93`, `٩٣` = `93`, `10k` = `10000`), is in the fact's text, or is a year of its period.

The person's years of experience, rounded down, may be stated in any claim, but only as years: "5 years", "5+ years of", "five years", "5 سنوات". The same digit elsewhere ("5 times faster") is a number like any other.

What these checks do not see: a product with an ordinary capitalized name that is in no list and not asked for by the posting ("Temporal"). The posting's own skills are always in the lexicon, so the claim a model is most tempted to make, "I know what you ask for", is covered.

### Limits

| Document | Limits |
|---|---|
| CV | Up to 3 summary blocks; up to 4 bullets per fact; a bullet or summary block up to 240 characters |
| Cover letter | 2 to 6 body blocks; a block up to 700 characters; 1,800 characters in total |
| Outreach message | 1 to 4 body blocks; 700 characters in total |

A leading list mark (`- `) in a block is removed when the draft is read: it is habit, not content.

Language: for an Arabic document, at least half of a block's letters must be Arabic, after the names of technologies are set aside. For an English document, at most a fifth may be Arabic.

## What the code checks cannot see

A false sentence with no skill, number, employer or title in it: "I enjoy mentoring large teams." Two more layers cover it:

1. The **judge**: a second model call that reads each block with its facts and answers `supported` or `unsupported`, and for plain blocks whether it makes a claim about the candidate. Its answer is one more source of violations (`JUDGE_UNSUPPORTED`, `JUDGE_PLAIN_CLAIMS`). It can only add violations.
2. The **person**, who approves every draft.

## Assembling a document

`assemble(kind, language, blocks, career, job)` builds Markdown. Code writes everything that is not a block:

| Part | Source |
|---|---|
| Name, headline, contacts | The career file |
| Section titles, in English or Arabic | Code |
| Each experience and project heading: organization, role, period | The career file |
| Bullets and paragraphs | The blocks that passed every check |
| Education | The career file's `education` facts, as written |
| Skills list | The person's skills, the job's skills first |
| Greeting and signature | Code: the company's name and the person's name |

A block that still has a violation after the repairs is **dropped** and listed with its reason. An experience fact with no bullet left keeps its heading and its own text from the career file, which is true by definition. A cover letter or message with fewer blocks than its minimum is a failed draft, not a short one.

A CV always shows the whole history: every experience fact, grouped by employer, role and period, newest first, then projects and education. The model improves the wording of what it was given; it cannot leave a job out.

## Manual edits

When the person edits a draft, the edited blocks go through the same code checks. Violations are shown as warnings: the person may keep their own words, and the document records that it was edited by hand.

## Tests

| Test | Proves |
|---|---|
| One case per violation code | It fires, and names the word or number |
| Clean cases | A block made of its fact's own words passes (property test over the example career file) |
| Skills | A technology from the posting that the person lacks is caught; an alias of a cited skill passes; an ambiguous name in a normal sentence is not flagged |
| Numbers | Percent, ranges, Arabic-Indic digits, number words; a year of the fact's period passes |
| Metrics off | Every number except the years of experience is refused |
| Assembly | Contacts come only from the file; dropped blocks are listed; the fallback text; minimum blocks; Arabic titles |
