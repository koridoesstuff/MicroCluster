"""Simulation core tests: state machine, contact model, population builder.

These do not touch the detection or disclosure engines -- they prove the
simulated world behaves before any Report is generated from it.
"""

from __future__ import annotations

import random
import unittest
from collections import Counter

from microcluster.models import ScopeLevel, ScopeRegistry

from simulation import contact, infection
from simulation.agent import Agent
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


def _force_state(agent: Agent, target: InfectionState) -> None:
    while order_index(agent.state) < order_index(target):
        infection.set_state(agent, STATE_ORDER[order_index(agent.state) + 1], 0)


def _curve(seed: int, days: int) -> tuple[list[int], list[int]]:
    history = Simulation(seed=seed, seed_infections=1).run(days)
    active = [
        h.count(InfectionState.INCUBATING) + h.count(InfectionState.SYMPTOMATIC)
        for h in history
    ]
    cumulative = [
        sum(1 for a in h.agents if a.state is not InfectionState.SUSCEPTIBLE)
        for h in history
    ]
    return active, cumulative


class EpidemicCurvePlausibilityTest(unittest.TestCase):
    """Sept 7 milestone: across seeds the headless simulator produces
    believable outbreaks -- a rise, a peak, a decline -- and is neither
    always-zero nor always-everyone."""

    DAYS = 30
    SEEDS = tuple(range(1, 41))
    ESTABLISHED = 10  # cumulative infections that count as a real outbreak

    @classmethod
    def setUpClass(cls) -> None:
        cls.runs = [(s, *_curve(s, cls.DAYS)) for s in cls.SEEDS]
        cls.total = len(Simulation(seed=1).agents)

    def _established(self):
        return [(s, a, c) for s, a, c in self.runs if c[-1] >= self.ESTABLISHED]

    def test_no_seed_infects_the_whole_population(self) -> None:
        for seed, _active, cum in self.runs:
            self.assertLess(cum[-1], self.total, f"seed {seed} infected everyone")

    def test_some_seeds_fizzle_and_some_take_off(self) -> None:
        established = self._established()
        fizzled = [r for r in self.runs if r[2][-1] <= 3]
        self.assertGreater(len(established), 5, "almost no seed produced an outbreak")
        self.assertLess(
            len(established), len(self.runs),
            "every seed produced an outbreak; the branching process is degenerate",
        )
        self.assertGreater(len(fizzled), 0, "no seed ever fizzled from its index case")

    def test_a_real_outbreak_reaches_a_large_share_of_the_population(self) -> None:
        worst = max(cum[-1] for _s, _a, cum in self.runs)
        self.assertGreater(worst, self.total * 0.4)

    def test_cumulative_infections_never_decrease(self) -> None:
        for seed, _active, cum in self.runs:
            for earlier, later in zip(cum, cum[1:]):
                self.assertLessEqual(earlier, later, f"seed {seed} cumulative fell")

    def test_established_outbreaks_rise_off_day_zero_and_mostly_turn_over(self) -> None:
        established = self._established()
        self.assertTrue(established)
        turned_over = 0
        for seed, active, _cum in established:
            peak = max(active)
            peak_day = active.index(peak)
            self.assertGreater(peak, active[0], f"seed {seed} never rose")
            self.assertGreaterEqual(peak_day, 2, f"seed {seed} peaked at day {peak_day}")
            if peak_day <= self.DAYS - 3 and active[-1] < peak:
                turned_over += 1
        self.assertGreaterEqual(
            turned_over, 0.6 * len(established),
            "most established outbreaks did not peak and decline inside the window",
        )

    def test_a_long_run_burns_out_to_zero_active(self) -> None:
        seed = self._established()[0][0]
        active, _cum = _curve(seed, 90)
        self.assertEqual(active[-1], 0, f"seed {seed} still active at day 90")


class InfectionStateMachineTest(unittest.TestCase):
    def _agent(self) -> Agent:
        return Agent(id="a", suite_id="s", reporting_probability=0.5)

    def test_infect_moves_to_incubating_and_draws_durations_in_range(self) -> None:
        cfg = SimulationConfig()
        rng = random.Random(0)
        for _ in range(50):
            agent = self._agent()
            infection.infect(agent, 0, rng, cfg)
            self.assertIs(agent.state, InfectionState.INCUBATING)
            self.assertGreaterEqual(agent.incubation_days, cfg.incubation_days_min)
            self.assertLessEqual(agent.incubation_days, cfg.incubation_days_max)
            self.assertGreaterEqual(agent.symptomatic_days, cfg.symptomatic_days_min)
            self.assertLessEqual(agent.symptomatic_days, cfg.symptomatic_days_max)

    def test_time_progression_respects_the_drawn_durations(self) -> None:
        cfg = SimulationConfig(
            incubation_days_min=2, incubation_days_max=2,
            symptomatic_days_min=3, symptomatic_days_max=3,
        )
        agent = self._agent()
        infection.infect(agent, 0, random.Random(1), cfg)
        infection.advance_time_based(agent, 1)
        self.assertIs(agent.state, InfectionState.INCUBATING)
        infection.advance_time_based(agent, 2)
        self.assertIs(agent.state, InfectionState.SYMPTOMATIC)
        infection.advance_time_based(agent, 4)
        self.assertIs(agent.state, InfectionState.SYMPTOMATIC)
        infection.advance_time_based(agent, 5)
        self.assertIs(agent.state, InfectionState.RECOVERED)

    def test_advance_makes_at_most_one_transition_per_call(self) -> None:
        cfg = SimulationConfig(
            incubation_days_min=1, incubation_days_max=1,
            symptomatic_days_min=1, symptomatic_days_max=1,
        )
        agent = self._agent()
        infection.infect(agent, 0, random.Random(1), cfg)
        infection.advance_time_based(agent, 100)
        self.assertIs(agent.state, InfectionState.SYMPTOMATIC)

    def test_set_state_rejects_backward_and_skipping(self) -> None:
        agent = self._agent()
        infection.set_state(agent, InfectionState.INCUBATING, 0)
        with self.assertRaises(ValueError):
            infection.set_state(agent, InfectionState.SUSCEPTIBLE, 1)
        with self.assertRaises(ValueError):
            infection.set_state(agent, InfectionState.RECOVERED, 1)


class ContactModelTest(unittest.TestCase):
    def _floor(self, *, floors=1, suites=2, per_suite=25):
        spec = StructureSpec(
            buildings=1, floors_per_building=floors,
            suites_per_floor=suites, agents_per_suite=per_suite,
        )
        agents, registry = build_population(spec, random.Random(0))
        by_suite: dict[str, list[Agent]] = {}
        for agent in agents:
            by_suite.setdefault(agent.suite_id, []).append(agent)
        floor_of: dict[str, str] = {}
        building_of: dict[str, str] = {}
        for suite_id in by_suite:
            floor_id, building_id = suite_ancestor_ids(registry, suite_id)
            floor_of[suite_id] = floor_id
            building_of[suite_id] = building_id
        return by_suite, floor_of, building_of

    def test_all_susceptible_produces_no_infections(self) -> None:
        by_suite, floor_of, building_of = self._floor()
        cfg = SimulationConfig(suite_transmission_probability=1.0)
        self.assertEqual(
            contact.new_infections(by_suite, floor_of, building_of, random.Random(0), cfg),
            ([], []),
        )

    def test_zero_probabilities_never_infect(self) -> None:
        by_suite, floor_of, building_of = self._floor()
        _force_state(next(iter(by_suite.values()))[0], InfectionState.SYMPTOMATIC)
        cfg = SimulationConfig(
            suite_transmission_probability=0.0,
            floor_transmission_probability=0.0,
            building_transmission_probability=0.0,
        )
        self.assertEqual(
            contact.new_infections(by_suite, floor_of, building_of, random.Random(0), cfg),
            ([], []),
        )

    def test_recovered_agents_do_not_transmit(self) -> None:
        by_suite, floor_of, building_of = self._floor()
        _force_state(next(iter(by_suite.values()))[0], InfectionState.RECOVERED)
        cfg = SimulationConfig(
            suite_transmission_probability=1.0,
            floor_transmission_probability=1.0,
            building_transmission_probability=1.0,
        )
        self.assertEqual(
            contact.new_infections(by_suite, floor_of, building_of, random.Random(0), cfg),
            ([], []),
        )

    def test_floor_contact_infects_the_neighbouring_suite_not_the_source(self) -> None:
        by_suite, floor_of, building_of = self._floor(suites=2)
        source, neighbour = list(by_suite)
        _force_state(by_suite[source][0], InfectionState.SYMPTOMATIC)
        cfg = SimulationConfig(
            suite_transmission_probability=0.0,
            floor_transmission_probability=1.0,
            building_transmission_probability=0.0,
        )
        within, cross = contact.new_infections(
            by_suite, floor_of, building_of, random.Random(0), cfg
        )
        self.assertEqual(within, [])
        self.assertEqual({a.id for a in cross}, {a.id for a in by_suite[neighbour]})

    def test_building_contact_reaches_another_floor(self) -> None:
        by_suite, floor_of, building_of = self._floor(floors=2, suites=1)
        source, other_floor = list(by_suite)
        _force_state(by_suite[source][0], InfectionState.SYMPTOMATIC)
        cfg = SimulationConfig(
            suite_transmission_probability=0.0,
            floor_transmission_probability=0.0,
            building_transmission_probability=1.0,
        )
        within, cross = contact.new_infections(
            by_suite, floor_of, building_of, random.Random(0), cfg
        )
        self.assertEqual(within, [])
        self.assertEqual({a.id for a in cross}, {a.id for a in by_suite[other_floor]})


class TimeSteppingTest(unittest.TestCase):
    def test_history_has_one_snapshot_per_day_including_day_zero(self) -> None:
        history = Simulation(seed=1, seed_infections=1).run(25)
        self.assertEqual(len(history), 26)
        self.assertEqual([h.day for h in history], list(range(26)))

    def test_seed_infections_are_present_at_day_zero(self) -> None:
        sim = Simulation(seed=1, seed_infections=3)
        self.assertEqual(sim.history[0].count(InfectionState.INCUBATING), 3)
        self.assertEqual(
            sim.history[0].count(InfectionState.SUSCEPTIBLE), len(sim.agents) - 3
        )

    def test_an_agent_infected_today_cannot_be_symptomatic_today(self) -> None:
        cfg = SimulationConfig(suite_transmission_probability=1.0)
        sim = Simulation(seed=2, seed_infections=1, config=cfg)
        day_zero = {s.id: s.state for s in sim.history[0].agents}
        day_one = sim.run(1)[1]
        became_infected = [
            s for s in day_one.agents
            if day_zero[s.id] is InfectionState.SUSCEPTIBLE
            and s.state is not InfectionState.SUSCEPTIBLE
        ]
        self.assertTrue(became_infected)
        self.assertTrue(
            all(s.state is InfectionState.INCUBATING for s in became_infected)
        )


class PopulationGenerationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = StructureSpec()
        self.agents, self.registry = build_population(self.spec, random.Random(7))

    def test_agent_ids_are_unique(self) -> None:
        ids = [a.id for a in self.agents]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_agent_belongs_to_one_declared_suite(self) -> None:
        suite_ids = {
            s.id for s in self.registry.scopes.values() if s.level is ScopeLevel.SUITE
        }
        for agent in self.agents:
            self.assertIn(agent.suite_id, suite_ids)

    def test_reporting_probability_is_within_the_config_range(self) -> None:
        cfg = SimulationConfig()
        for agent in self.agents:
            self.assertGreaterEqual(agent.reporting_probability, cfg.reporting_probability_min)
            self.assertLessEqual(agent.reporting_probability, cfg.reporting_probability_max)

    def test_each_suite_holds_exactly_the_specified_headcount(self) -> None:
        by_suite = Counter(a.suite_id for a in self.agents)
        self.assertTrue(all(n == self.spec.agents_per_suite for n in by_suite.values()))
        self.assertEqual(
            len(by_suite),
            self.spec.buildings * self.spec.floors_per_building * self.spec.suites_per_floor,
        )

    def test_a_custom_structure_scales_every_level(self) -> None:
        spec = StructureSpec(
            buildings=2, floors_per_building=3, suites_per_floor=2, agents_per_suite=30
        )
        agents, registry = build_population(spec, random.Random(0))
        self.assertEqual(len(agents), 2 * 3 * 2 * 30)
        per_level: dict[ScopeLevel, set[int]] = {}
        for scope in registry.scopes.values():
            per_level.setdefault(scope.level, set()).add(scope.population)
        self.assertEqual(per_level[ScopeLevel.SUITE], {30})
        self.assertEqual(per_level[ScopeLevel.FLOOR], {60})
        self.assertEqual(per_level[ScopeLevel.BUILDING], {180})
        self.assertEqual(per_level[ScopeLevel.CAMPUS], {360})


if __name__ == "__main__":
    unittest.main()
