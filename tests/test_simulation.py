"""Simulation core tests: state machine, contact model, population builder.

These do not touch the detection or disclosure engines -- they prove the
simulated world behaves before any Report is generated from it.
"""

from __future__ import annotations

import random
import unittest

from microcluster.models import ScopeLevel, ScopeRegistry

from simulation.config import SimulationConfig
from simulation.contact import suite_ancestor_ids
from simulation.infection import STATE_ORDER, InfectionState, order_index
from simulation.population import StructureSpec, build_population
from simulation.simulator import Simulation

# Derived from the default spec, not hard-coded.
_SPEC = StructureSpec()
_TOTAL_AGENTS = (
    _SPEC.buildings
    * _SPEC.floors_per_building
    * _SPEC.suites_per_floor
    * _SPEC.agents_per_suite
)


class ZeroInfectedTest(unittest.TestCase):
    def test_population_with_no_seed_stays_fully_susceptible(self) -> None:
        sim = Simulation(seed=1, seed_infections=0)
        history = sim.run(30)

        total = len(sim.agents)
        for snapshot in history:
            self.assertEqual(snapshot.count(InfectionState.SUSCEPTIBLE), total)
            self.assertEqual(snapshot.count(InfectionState.INCUBATING), 0)
            self.assertEqual(snapshot.count(InfectionState.SYMPTOMATIC), 0)
            self.assertEqual(snapshot.count(InfectionState.RECOVERED), 0)


class CrossSuiteTransmissionTest(unittest.TestCase):
    """Contact is tiered (suite / floor / building), so an outbreak is no
    longer trapped in its starting suite -- but the floor/building rates
    are lower, so crossing a suite boundary should stay rarer than
    transmitting within one."""

    def test_cross_suite_transmission_occurs_but_is_rarer_than_within_suite(
        self,
    ) -> None:
        total_within = 0
        total_cross = 0
        for seed in range(1, 41):
            sim = Simulation(seed=seed, seed_infections=1)
            sim.run(30)
            total_within += sim.total_within_suite_infections
            total_cross += sim.total_cross_suite_infections

        self.assertGreater(
            total_cross, 0, "cross-suite transmission never occurred over 40 seeds"
        )
        self.assertLess(
            total_cross,
            total_within,
            f"cross-suite transmission ({total_cross}) was not rarer than "
            f"within-suite transmission ({total_within})",
        )


class WithinSuiteAttackRateTest(unittest.TestCase):
    """A seeded suite's final attack rate should be a real, seed-dependent
    outcome -- never a guaranteed 100%, and not the same number every
    time."""

    def _suite_attack_rate(self, seed: int, days: int = 30) -> float:
        sim = Simulation(seed=seed, seed_infections=1)
        seeded_suite = next(
            a.suite_id for a in sim.agents if a.state is not InfectionState.SUSCEPTIBLE
        )
        history = sim.run(days)
        last = history[-1]
        n = sum(1 for s in last.agents if s.suite_id == seeded_suite)
        infected = sum(
            1
            for s in last.agents
            if s.suite_id == seeded_suite and s.state is not InfectionState.SUSCEPTIBLE
        )
        return infected / n

    def test_attack_rate_is_below_100_percent_and_varies_across_seeds(self) -> None:
        rates = [self._suite_attack_rate(seed) for seed in range(1, 11)]

        self.assertTrue(
            all(rate < 1.0 for rate in rates),
            f"some seed reached a 100% within-suite attack rate: {rates}",
        )
        self.assertGreater(
            max(rates) - min(rates),
            0.1,
            f"within-suite attack rate did not vary meaningfully across seeds: {rates}",
        )


class SecondFloorReachedTest(unittest.TestCase):
    def test_infection_reaches_a_second_floor_at_least_sometimes(self) -> None:
        reached_second_floor = False
        for seed in range(1, 31):
            sim = Simulation(seed=seed, seed_infections=1)
            history = sim.run(30)

            touched_floors = {
                suite_ancestor_ids(sim.registry, s.suite_id)[0]
                for s in history[-1].agents
                if s.state is not InfectionState.SUSCEPTIBLE
            }
            if len(touched_floors) > 1:
                reached_second_floor = True
                break

        self.assertTrue(
            reached_second_floor,
            "no seed among the first 30 reached a second floor within 30 days",
        )


class CertainTransmissionTest(unittest.TestCase):
    def test_probability_one_infects_the_whole_suite_in_a_single_step(self) -> None:
        # With p = 1.0 a single infectious agent infects every susceptible
        # suite-mate in one daily step, so the expected number of steps to
        # a fully-infected suite is 1.
        config = SimulationConfig(suite_transmission_probability=1.0)
        sim = Simulation(seed=3, seed_infections=1, config=config)
        seeded_suite = next(
            a.suite_id for a in sim.agents if a.state is not InfectionState.SUSCEPTIBLE
        )

        history = sim.run(5)
        day_one = history[1]
        in_suite = [s for s in day_one.agents if s.suite_id == seeded_suite]

        self.assertEqual(len(in_suite), _SPEC.agents_per_suite)
        self.assertTrue(
            all(s.state is not InfectionState.SUSCEPTIBLE for s in in_suite)
        )


class ForwardProgressionTest(unittest.TestCase):
    def test_states_never_regress_and_never_skip(self) -> None:
        config = SimulationConfig(suite_transmission_probability=1.0)
        sim = Simulation(seed=5, seed_infections=1, config=config)
        history = sim.run(30)

        sequences: dict[str, list[InfectionState]] = {}
        for snapshot in history:
            for agent_snapshot in snapshot.agents:
                sequences.setdefault(agent_snapshot.id, []).append(agent_snapshot.state)

        for agent_id, states in sequences.items():
            for previous, following in zip(states, states[1:]):
                delta = order_index(following) - order_index(previous)
                self.assertGreaterEqual(delta, 0, f"{agent_id} moved backwards")
                self.assertLessEqual(delta, 1, f"{agent_id} skipped a state")

        # Non-vacuous: the p=1.0 suite runs the full course within 30 days.
        self.assertGreater(history[-1].count(InfectionState.RECOVERED), 0)


class ConservationTest(unittest.TestCase):
    def test_agent_count_is_conserved_across_states_every_step(self) -> None:
        config = SimulationConfig(suite_transmission_probability=0.5)
        sim = Simulation(seed=2, seed_infections=2, config=config)
        history = sim.run(30)

        total = len(sim.agents)
        for snapshot in history:
            self.assertEqual(sum(snapshot.counts.values()), total)
            self.assertEqual(len(snapshot.agents), total)
            self.assertEqual(set(snapshot.counts), set(STATE_ORDER))


class RegistryPopulationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = StructureSpec()
        self.agents, self.registry = build_population(self.spec, random.Random(0))

    def test_declared_populations_equal_actual_agent_counts(self) -> None:
        for scope_id, scope in self.registry.scopes.items():
            actual = sum(
                1
                for agent in self.agents
                if self.registry.contains(scope_id, agent.suite_id)
            )
            self.assertEqual(scope.population, actual, f"scope {scope_id}")

    def test_populations_per_level_match_the_spec(self) -> None:
        expected_suite = self.spec.agents_per_suite
        expected_floor = self.spec.suites_per_floor * expected_suite
        expected_campus = _TOTAL_AGENTS

        per_level: dict[ScopeLevel, set[int]] = {}
        for scope in self.registry.scopes.values():
            per_level.setdefault(scope.level, set()).add(scope.population)

        self.assertEqual(per_level[ScopeLevel.SUITE], {expected_suite})
        self.assertEqual(per_level[ScopeLevel.FLOOR], {expected_floor})
        self.assertEqual(per_level[ScopeLevel.CAMPUS], {expected_campus})
        self.assertEqual(len(self.agents), expected_campus)
        # The concrete acceptance numbers from the task.
        self.assertEqual(expected_suite, 25)
        self.assertEqual(expected_floor, 75)
        self.assertEqual(expected_campus, 150)

    def test_registry_passes_scoperegistry_validation(self) -> None:
        # Rebuilding from the produced scopes must not raise.
        rebuilt = ScopeRegistry(dict(self.registry.scopes))
        self.assertEqual(rebuilt.campus_population(), len(self.agents))

    def test_a_suite_reaches_campus_through_the_registry(self) -> None:
        suite_id = next(
            s.id for s in self.registry.scopes.values() if s.level is ScopeLevel.SUITE
        )
        chain = self.registry.chain_to_root(suite_id)
        self.assertEqual(
            [s.level for s in chain],
            [
                ScopeLevel.SUITE,
                ScopeLevel.FLOOR,
                ScopeLevel.BUILDING,
                ScopeLevel.CAMPUS,
            ],
        )

    def test_suite_at_or_below_privacy_minimum_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_population(
                StructureSpec(agents_per_suite=20), random.Random(0)
            )

    def test_nonpositive_structure_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_population(StructureSpec(buildings=0), random.Random(0))


class DeterminismTest(unittest.TestCase):
    def test_same_seed_same_history(self) -> None:
        a = Simulation(seed=42, seed_infections=1).run(20)
        b = Simulation(seed=42, seed_infections=1).run(20)
        self.assertEqual(
            [s.counts for s in a],
            [s.counts for s in b],
        )


if __name__ == "__main__":
    unittest.main()
