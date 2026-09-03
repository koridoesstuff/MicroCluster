"""Model-level validation: the fixed checklist is the only accepted input."""

from __future__ import annotations

import unittest
from datetime import timedelta

from microcluster.models import (
    CHECKLIST,
    Category,
    Onset,
    Report,
    Scope,
    ScopeLevel,
    ScopeRegistry,
)

from tests.fixtures import NOW


def _report(**overrides) -> Report:
    kwargs = dict(
        category=Category.RESPIRATORY,
        symptom="cough",
        onset=Onset.TODAY,
        location_id="X",
        submitted_at=NOW - timedelta(hours=1),
    )
    kwargs.update(overrides)
    return Report(**kwargs)


class ReportValidationTest(unittest.TestCase):
    def test_symptom_not_in_the_fixed_checklist_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _report(category=Category.RESPIRATORY, symptom="chest x-ray abnormality")
        self.assertIn("not in the fixed checklist", str(ctx.exception))

    def test_symptom_from_a_different_category_is_rejected(self) -> None:
        # "diarrhea" is a real checklist symptom, but not under RESPIRATORY.
        self.assertIn("diarrhea", CHECKLIST[Category.GASTROINTESTINAL])
        with self.assertRaises(ValueError):
            _report(category=Category.RESPIRATORY, symptom="diarrhea")

    def test_free_text_category_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _report(category="respiratory-ish")  # type: ignore[arg-type]

    def test_free_text_onset_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _report(onset="a while ago")  # type: ignore[arg-type]

    def test_every_valid_checklist_symptom_is_accepted(self) -> None:
        for category, symptoms in CHECKLIST.items():
            for symptom in symptoms:
                _report(category=category, symptom=symptom)  # no raise


class ScopeValidationTest(unittest.TestCase):
    def test_declared_population_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            Scope("z", "Zero", ScopeLevel.CAMPUS, population=0)

    def test_non_campus_scope_needs_a_parent(self) -> None:
        with self.assertRaises(ValueError):
            Scope("b", "Orphan building", ScopeLevel.BUILDING, 100)

    def test_registry_rejects_unknown_parent(self) -> None:
        with self.assertRaises(ValueError):
            ScopeRegistry(
                {"b": Scope("b", "B", ScopeLevel.BUILDING, 100, parent_id="missing")}
            )


if __name__ == "__main__":
    unittest.main()
