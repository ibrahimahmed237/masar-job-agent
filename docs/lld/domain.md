# Domain — the career file, jobs and applications

`masar.domain` holds the data models and every rule that needs no I/O. It imports the standard library and Pydantic. Anything that depends on "today" takes the date as an argument.

## The career file

Written by the person, in YAML ([ADR-0008](../adr/0008-career-file.md)). Masar reads it and never writes it.

```yaml
person:
  name: Sara Al-Najjar
  headline: Backend engineer
  email: sara@example.com
  phone: "+20 100 000 0000"
  links: ["https://github.com/sara-example"]
  location: { city: Cairo, country: EG }
  languages: [{ code: ar, level: native }, { code: en, level: professional }]
  work_authorization: [EG]        # countries where no visa sponsorship is needed

limits:
  countries: [SA, AE, EG]         # where the person wants to work; empty means anywhere
  remote: true                    # accepts remote jobs
  relocation: true                # accepts moving for an on-site job
  employment: [full-time]         # empty means any
  years_gap_allowed: 2            # how many years above the person's experience a posting may ask
  exclude_companies: []
  title_keywords: [backend, software engineer]   # a posting title must contain one; empty means any
  title_exclude: [intern, sales]

style:
  metrics: true                   # false: no numbers in documents

facts:
  - id: acme-allocation
    kind: experience              # experience | project | education | skill | other
    org: Acme Retail
    role: Software Engineer
    period: { from: 2023-03, to: present }
    text: Built an event-driven inventory allocation service that raised store availability to 93%.
    skills: [NestJS, Kafka, PostgreSQL]
```

### Rules of the file

| Rule | Code |
|---|---|
| Fact ids are unique, lower-case slugs: letters, digits, `-`; 2 to 40 characters | `CAREER-ID` |
| Every fact has a text of 10 to 600 characters | `CAREER-TEXT` |
| An `experience` fact has an organization, a role and a period | `CAREER-EXPERIENCE` |
| A period's start is not after its end; `to` may be `present` | `CAREER-PERIOD` |
| Country codes are two upper-case letters; language codes two lower-case letters | `CAREER-CODE` |
| At least one fact | `CAREER-EMPTY` |
| Unknown keys are refused, so a typo is found | `CAREER-FIELD` |

Warnings, shown by `masar profile check` and never blocking: a fact with no skills, an experience with no numbers when `style.metrics` is on, fewer than three facts.

### Derived values

| Value | How |
|---|---|
| Years of experience | The months covered by `experience` periods, counted once where they overlap, up to a given date, divided by 12 |
| The person's skills | The union of the facts' skills, as canonical names |
| The file's checksum | SHA-256 of the file's bytes; stored with every result |

## Skills

A skill is compared by its **canonical name**, not by its spelling.

- A built-in table maps aliases to canonical names: `Postgres`, `PostgreSQL`, `psql` → `postgresql`; `K8s` → `kubernetes`; `Node`, `NodeJS`, `Node.js` → `node.js`.
- A name the table does not know is its own canonical name, lower-cased.
- **Finding skills in a text** uses the lexicon of the moment: the person's skills, the job's skills, and the built-in table. A name matches as a whole token, also when it has symbols (`C#`, `C++`, `.NET`, `Node.js`).
- **Ambiguous names** (`Go`, `R`, `C`, `Swift`, `Rust`, `Spring`, `Express`, `Dart`, `Flow`, `Chef`, `Puppet`, `Julia`, `Assembly`) match only in their exact spelling, so "go to market" is not the Go language.

## Postings and jobs

| Model | What | Made by |
|---|---|---|
| `Posting` | The raw text as published: source, company, title, URL, location text, text, external id, checksum | An adapter or the person |
| `Job` | The structured reading of a posting | The extract step, then the ground step |

```text
Job
├── title, company
├── seniority      intern | junior | mid | senior | lead | principal | unknown
├── employment     full-time | part-time | contract | internship | unknown
├── workplace      onsite | hybrid | remote | unknown
├── locations      [{ city?, country? }]
├── min_years      { value, quote }?
├── sponsorship    { status: offered | not_offered | unknown, quote? }
├── languages      [{ code, quote }]
└── requirements   [{ id, text, kind: must | nice, skills[], all_skills, quote }]
```

### Grounding a job

The extract step's output is not trusted. `ground_job(candidate, posting_text)` returns the job that code can stand behind, and a finding for everything it removed.

| Check | If it fails |
|---|---|
| A requirement's quote is in the posting text | The requirement is dropped (`JOB-QUOTE`) |
| Each skill of a requirement is in that requirement's quote, under any of its aliases | The skill is dropped (`JOB-SKILL`) |
| The quote of `min_years` is in the text and contains the number | `min_years` becomes unknown (`JOB-YEARS`) |
| The quote of a sponsorship statement is in the text | The status becomes `unknown` (`JOB-SPONSORSHIP`) |
| The quote of a required language is in the text | The language is dropped (`JOB-LANGUAGE`) |
| More than 40 requirements | The rest are dropped (`JOB-TOO-MANY`) |

Text is compared after normalization: Unicode NFKC, case folded, runs of white space as one space, curly quotes as straight ones. Requirement ids are given by code (`r1`, `r2`, …) after grounding.

## Applications

One application per job. The states and the moves are in the [design](../DESIGN.md#63-an-applications-life).

| Rule | Why |
|---|---|
| A move not in the table is refused with the allowed moves | No silent jumps |
| Only `drafted` is ever set by Masar itself, when a document is approved, and only from `found` or `shortlisted` | Approving a document shows interest; everything else is the person's act |
| Every move is an event with the time and a note | The history is the record |
| `offer`, `rejected` and `withdrawn` are final | A new chance at the same company is a new job |

`needs_attention(applications, today)` returns: `shortlisted` with no draft, drafts waiting for a decision, `applied` with no event for 10 days, `interviewing` with no event for 7 days.

## Results, not exceptions

Rules return a result: the value and a list of findings. A finding has a code, a severity (`error` or `warning`), a path and a message. Exceptions are for bugs.

## Tests

| Test | Proves |
|---|---|
| Career file cases | Each rule above, with the path of the fault; unknown keys; the example file is valid |
| Years of experience | Overlaps counted once; `present`; a gap; before the first job |
| Skill matching | Aliases, symbols, token borders, the ambiguous names in both spellings |
| Grounding | Each check drops exactly what it should and reports it; normalization of quotes |
| Application states | Every allowed move, every refused move, final states, the attention list |
