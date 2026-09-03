"""Data model: the fixed checklist, scopes, and reports.

There is no free text anywhere in this module and no medical concept
finer than a *category* (rule 1, rule 2). A ``Report`` records a specific
symptom only for the reporter's own clarity; nothing in the engines ever
reads ``Report.symptom`` for matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum


class Category(str, Enum):
    """The four fixed checklist categories. Clustering happens here and
    nowhere finer."""

    RESPIRATORY = "Respiratory"
    GASTROINTESTINAL = "Gastrointestinal"
    GENERAL = "General"
    OTHER = "Other"


# The fixed checklist: 3-5 named symptoms per category. The symptom text is
# a closed vocabulary chosen at design time -- it is NOT free text, and it
# is never used for matching (rule 2). It exists so a reporter can pick the
# thing that matches what they feel.
CHECKLIST: dict[Category, tuple[str, ...]] = {
    Category.RESPIRATORY: (
        "cough",
        "sore throat",
        "shortness of breath",
        "runny or blocked nose",
        "fever with cough",
    ),
    Category.GASTROINTESTINAL: (
        "nausea",
        "vomiting",
        "diarrhea",
        "stomach cramps",
    ),
    Category.GENERAL: (
        "fever",
        "fatigue",
        "body aches",
        "headache",
        "chills",
    ),
    Category.OTHER: (
        "skin rash",
        "dizziness",
        "loss of taste or smell",
    ),
}


class Onset(str, Enum):
    """Coarse onset buckets. Deliberately imprecise."""

    TODAY = "today"
    ONE_TO_TWO_DAYS = "1-2 days"
    THREE_TO_SEVEN_DAYS = "3-7 days"
    ONE_WEEK_PLUS = "1+ week"


class ScopeLevel(IntEnum):
    """Hierarchy depth. Larger value == finer scope. Used to pick the
    'finest' scope in rule 9 -- there is no hardcoded tier list, only this
    ordering over whatever scopes exist."""

    CAMPUS = 1
    BUILDING = 2
    FLOOR = 3
    SUITE = 4


@dataclass(frozen=True)
class Scope:
    """One node in the location hierarchy.

    ``population`` is DECLARED at group creation (rule 7). It is never the
    number of people who reported. Every gate in the disclosure engine
    uses this number.
    """

    id: str
    label: str
    level: ScopeLevel
    population: int
    parent_id: str | None = None

    def __post_init__(self) -> None:
        if self.population <= 0:
            raise ValueError(f"scope {self.id!r}: declared population must be positive")
        if self.level == ScopeLevel.CAMPUS and self.parent_id is not None:
            raise ValueError(f"scope {self.id!r}: a CAMPUS scope has no parent")
        if self.level != ScopeLevel.CAMPUS and self.parent_id is None:
            raise ValueError(f"scope {self.id!r}: non-CAMPUS scope needs a parent_id")


@dataclass(frozen=True)
class ScopeRegistry:
    """The declared set of scopes. Built once, at group creation."""

    scopes: dict[str, Scope]

    def __post_init__(self) -> None:
        for scope_id, scope in self.scopes.items():
            if scope.id != scope_id:
                raise ValueError(f"registry key {scope_id!r} != scope id {scope.id!r}")
            if scope.parent_id is not None and scope.parent_id not in self.scopes:
                raise ValueError(f"scope {scope_id!r}: unknown parent {scope.parent_id!r}")

    def get(self, scope_id: str) -> Scope:
        try:
            return self.scopes[scope_id]
        except KeyError:
            raise KeyError(f"unknown scope id: {scope_id!r}") from None

    def chain_to_root(self, scope_id: str) -> list[Scope]:
        """``scope_id`` itself, then each ancestor, up to the campus root."""
        out: list[Scope] = []
        current: str | None = scope_id
        seen: set[str] = set()
        while current is not None:
            if current in seen:
                raise ValueError(f"scope cycle detected at {current!r}")
            seen.add(current)
            scope = self.get(current)
            out.append(scope)
            current = scope.parent_id
        return out

    def contains(self, ancestor_id: str, scope_id: str) -> bool:
        """True if ``scope_id`` is ``ancestor_id`` or sits below it."""
        return any(s.id == ancestor_id for s in self.chain_to_root(scope_id))

    def roots(self) -> list[Scope]:
        return [s for s in self.scopes.values() if s.parent_id is None]

    def campus_population(self) -> int:
        """Total declared population: the sum of the root scopes'
        declared populations. Used as the comparison denominator by both
        detectors."""
        roots = self.roots()
        if not roots:
            raise ValueError("registry has no root (CAMPUS) scope")
        return sum(s.population for s in roots)


@dataclass(frozen=True)
class Report:
    """One anonymous submission from the fixed checklist.

    ``session_id`` is an opaque, ephemeral token used only for the
    intake-time submission caps (rule 11). The engines never read it.
    """

    category: Category
    symptom: str
    onset: Onset
    location_id: str
    submitted_at: datetime
    session_id: str | None = field(default=None)

    def __post_init__(self) -> None:
        if not isinstance(self.category, Category):
            raise ValueError(f"category must be a Category, got {self.category!r}")
        if not isinstance(self.onset, Onset):
            raise ValueError(f"onset must be an Onset, got {self.onset!r}")
        if self.symptom not in CHECKLIST[self.category]:
            raise ValueError(
                f"symptom {self.symptom!r} is not in the fixed checklist for "
                f"category {self.category.value!r}"
            )
