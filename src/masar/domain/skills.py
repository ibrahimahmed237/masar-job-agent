"""Skills are compared by canonical name, and found in text as whole tokens.

A table maps the spellings people use to one name. A name the table does not know is its own
canonical name. Some names are also everyday words ("Go", "Spring", "React"): those match only
in their exact spelling, so "go to market" is not the Go language.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property

# display name, other spellings, exact spelling only?
# An alias that starts with "=" also matches only in its exact spelling ("=Node": "Node", never "a node").
_TABLE: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    # Languages
    ("Python", ("python3",), False),
    ("JavaScript", ("=JS", "ecmascript", "es6"), False),
    ("TypeScript", ("=TS",), False),
    ("Java", (), False),
    ("C#", ("csharp", "c sharp"), False),
    ("C++", ("cpp",), False),
    ("C", (), True),
    ("Go", ("Golang",), True),
    ("Rust", (), True),
    ("Ruby", (), False),
    ("PHP", (), False),
    ("Kotlin", (), False),
    ("Swift", (), True),
    ("Scala", (), False),
    ("R", (), True),
    ("Dart", (), True),
    ("Elixir", (), False),
    ("SQL", (), False),
    ("Bash", ("shell scripting",), False),
    # Backend frameworks
    ("Node.js", ("=Node", "nodejs", "node js"), False),
    ("NestJS", ("nest.js", "nest js"), False),
    ("Express", ("express.js", "expressjs"), True),
    ("FastAPI", ("fast api",), False),
    ("Django", (), False),
    ("Flask", (), True),
    ("Spring Boot", ("springboot",), False),
    ("Spring", ("Spring Framework",), True),
    (".NET", ("dotnet", "asp.net", "asp.net core", ".net core"), False),
    ("Rails", ("ruby on rails",), True),
    ("Laravel", (), False),
    ("GraphQL", (), False),
    ("gRPC", (), False),
    ("REST", ("rest api", "rest apis", "restful"), True),
    # Frontend
    ("React", ("react.js", "reactjs"), True),
    ("Next.js", ("nextjs",), False),
    ("Angular", ("angularjs",), False),
    ("Vue", ("vue.js", "vuejs"), False),
    ("HTML", ("html5",), False),
    ("CSS", ("css3",), False),
    ("Tailwind", ("tailwind css", "tailwindcss"), False),
    # Data stores
    ("PostgreSQL", ("postgres", "psql"), False),
    ("MySQL", (), False),
    ("SQLite", (), False),
    ("SQL Server", ("mssql", "ms sql"), False),
    ("Oracle", (), True),
    ("MongoDB", ("mongo",), False),
    ("Redis", (), False),
    ("Elasticsearch", ("elastic search", "opensearch"), False),
    ("Cassandra", (), False),
    ("DynamoDB", (), False),
    ("ClickHouse", (), False),
    ("Snowflake", (), True),
    ("BigQuery", (), False),
    ("pgvector", (), False),
    ("Prisma", (), False),
    ("TypeORM", (), False),
    ("Hibernate", (), False),
    ("Entity Framework", ("ef core", "entity framework core"), False),
    # Messaging and streaming
    ("Kafka", ("apache kafka",), False),
    ("RabbitMQ", ("rabbit mq",), False),
    ("SQS", ("amazon sqs", "aws sqs"), False),
    ("BullMQ", ("bull mq",), False),
    ("NATS", (), False),
    ("Pub/Sub", ("pubsub", "google pub/sub"), False),
    ("Spark", ("apache spark", "pyspark"), True),
    ("Airflow", ("apache airflow",), False),
    ("Flink", (), False),
    # Cloud and operations
    ("AWS", ("amazon web services",), False),
    ("GCP", ("google cloud", "google cloud platform"), False),
    ("Azure", ("microsoft azure",), False),
    ("Docker", (), False),
    ("Kubernetes", ("k8s",), False),
    ("Terraform", (), False),
    ("Ansible", (), False),
    ("Helm", (), True),
    ("ECS", ("amazon ecs",), False),
    ("Lambda", ("aws lambda",), True),
    ("S3", ("amazon s3",), False),
    ("CI/CD", ("ci cd", "cicd", "continuous integration"), False),
    ("GitHub Actions", (), False),
    ("GitLab CI", ("gitlab ci/cd",), False),
    ("Jenkins", (), False),
    ("Linux", (), False),
    ("Nginx", (), False),
    ("Git", (), False),
    # Observability
    ("Prometheus", (), False),
    ("Grafana", (), False),
    ("Datadog", (), False),
    ("Kibana", (), False),
    ("OpenTelemetry", ("otel",), False),
    ("Sentry", (), True),
    # AI
    ("LangChain", (), False),
    ("LangGraph", (), False),
    ("LlamaIndex", (), False),
    ("OpenAI", (), False),
    ("RAG", ("retrieval-augmented generation", "retrieval augmented generation"), True),
    ("LLM", ("llms", "large language model", "large language models"), False),
    ("MCP", ("model context protocol",), False),
    ("PyTorch", (), False),
    ("TensorFlow", (), False),
    ("scikit-learn", ("sklearn", "scikit learn"), False),
    ("pandas", (), False),
    ("NumPy", (), False),
    ("Hugging Face", ("huggingface",), False),
    ("NLP", ("natural language processing",), False),
    ("OCR", (), False),
    ("Machine Learning", ("=ML",), False),
    # Practices and protocols
    ("Microservices", ("micro-services", "microservice"), False),
    ("Event-driven", ("event driven", "event-driven architecture"), False),
    ("WebSockets", ("websocket",), False),
    ("OAuth", ("oauth2", "oauth 2.0"), False),
    ("JWT", (), False),
    ("Agile", (), True),
    ("Scrum", (), False),
    ("TDD", ("test-driven development",), False),
    # Test tools
    ("Jest", (), True),
    ("pytest", (), False),
    ("JUnit", (), False),
    ("xUnit", (), False),
    ("Cypress", (), True),
    ("Playwright", (), False),
    ("Selenium", (), False),
    # Payments and others
    ("Stripe", (), True),
    ("PayPal", (), False),
    ("Twilio", (), False),
    ("Firebase", (), False),
    ("Supabase", (), False),
    ("Shopify", (), False),
    ("Salesforce", (), False),
    ("SAP", (), True),
)

_BOUNDARY_BEFORE = r"(?<![A-Za-z0-9_])(?<![A-Za-z0-9]\.)"
_BOUNDARY_AFTER = r"(?![A-Za-z0-9_+#])(?!\.[A-Za-z0-9])"


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()


_CANONICAL: dict[str, str] = {}
_DISPLAY: dict[str, str] = {}
_EXACT: dict[str, tuple[str, ...]] = {}
_SURFACES: dict[str, tuple[str, ...]] = {}
for _display, _aliases, _exact in _TABLE:
    _name = _key(_display)
    _DISPLAY[_name] = _display
    _plain = tuple(a.removeprefix("=") for a in _aliases)
    _SURFACES[_name] = (_display, *_plain)
    for _surface in (_display, *_plain):
        _CANONICAL.setdefault(_key(_surface), _name)
    # The display form of an ambiguous name, and the aliases marked with "=", match in their exact spelling only.
    _EXACT[_name] = ((_display,) if _exact else ()) + tuple(a[1:] for a in _aliases if a.startswith("="))


def canonical(name: str) -> str:
    """The one name a skill is compared by. Unknown names are their own canonical name."""
    key = _key(name)
    return _CANONICAL.get(key, key)


def display(name: str) -> str:
    """How a canonical name is written for people."""
    return _DISPLAY.get(canonical(name), name.strip())


def spellings(name: str) -> tuple[str, ...]:
    """Every way the table writes a skill, the given name first."""
    return tuple(dict.fromkeys((name.strip(), *_SURFACES.get(canonical(name), ()))))


def is_known(name: str) -> bool:
    return _key(name) in _CANONICAL


@dataclass(frozen=True, slots=True)
class SkillHit:
    """A skill found in a text: its canonical name, the words as written, and where."""

    name: str
    surface: str
    start: int
    end: int


class SkillLexicon:
    """The skill names to look for in a text: the built-in table, plus the names given.

    A given name that the table does not know is looked for as written, in any case.
    """

    def __init__(self, names: Iterable[str] = ()) -> None:
        self._extra = {canonical(n): n.strip() for n in names if n.strip() and not is_known(n)}

    @cached_property
    def _patterns(self) -> tuple[re.Pattern[str], re.Pattern[str] | None]:
        loose: dict[str, str] = {}
        exact: dict[str, str] = {}
        for name, surfaces in _SURFACES.items():
            for surface in surfaces:
                if len(surface) == 1:
                    # "C" and "R" are too easy to meet by accident ("Series C", "R&D"). They are skills
                    # when listed as skills, and are not looked for in running text.
                    continue
                if surface in _EXACT.get(name, ()):
                    exact[surface] = name
                else:
                    loose[_key(surface)] = name
        for name, surface in self._extra.items():
            loose[_key(surface)] = name
        self._loose_names = loose
        self._exact_names = exact
        return _compile(loose.keys(), re.IGNORECASE), (_compile(exact.keys(), 0) if exact else None)

    def find(self, text: str) -> list[SkillHit]:
        """Every skill in the text, longest match first where two overlap, in order of appearance."""
        loose, exact = self._patterns
        hits = [
            SkillHit(self._loose_names[_key(m.group(0))], m.group(0), m.start(), m.end()) for m in loose.finditer(text)
        ]
        if exact is not None:
            hits += [
                SkillHit(self._exact_names[m.group(0)], m.group(0), m.start(), m.end()) for m in exact.finditer(text)
            ]
        hits.sort(key=lambda h: (h.start, -(h.end - h.start)))
        kept: list[SkillHit] = []
        for hit in hits:
            if not kept or hit.start >= kept[-1].end:
                kept.append(hit)
        return kept

    def names_in(self, text: str) -> set[str]:
        return {hit.name for hit in self.find(text)}


def _compile(surfaces: Iterable[str], flags: int) -> re.Pattern[str]:
    # Longest first, so "Node.js" wins over "Node" and "C++" over "C".
    ordered = sorted(surfaces, key=lambda s: (-len(s), s))
    body = "|".join(re.escape(s).replace(r"\ ", r"\s+") for s in ordered)
    return re.compile(f"{_BOUNDARY_BEFORE}(?:{body}){_BOUNDARY_AFTER}", flags)


def canonical_set(names: Iterable[str]) -> frozenset[str]:
    return frozenset(canonical(n) for n in names if n.strip())
