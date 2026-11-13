"""A job to test with, and helpers to change one thing in it."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from masar.domain.job import (
    Employment,
    Job,
    JobLocation,
    Requirement,
    RequirementKind,
    Seniority,
    Sponsorship,
    Workplace,
)


def requirement(
    index: int, text: str, *skills: str, kind: RequirementKind = RequirementKind.MUST, all_skills: bool = False
) -> Requirement:
    return Requirement(f"r{index}", text, kind, quote=text, skills=skills, all_skills=all_skills)


def example_job(**changes: Any) -> Job:
    """A hybrid backend job in Riyadh that the example person fits well."""
    job = Job(
        title="Backend Engineer",
        company="Tamween",
        seniority=Seniority.MID,
        employment=Employment.FULL_TIME,
        workplace=Workplace.HYBRID,
        locations=(JobLocation("Riyadh", "SA"),),
        min_years=3,
        sponsorship=Sponsorship.OFFERED,
        languages=("en",),
        requirements=(
            requirement(1, "3+ years of experience building backend services"),
            requirement(2, "Strong knowledge of Node.js or Python", "Node.js", "Python"),
            requirement(3, "Experience with Postgres and Kafka in production", "PostgreSQL", "Kafka", all_skills=True),
            requirement(4, "Experience with Kubernetes", "Kubernetes", kind=RequirementKind.NICE),
        ),
    )
    return replace(job, **changes)
