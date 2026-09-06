"""Tunable constants for the outbreak simulator.

EVERY value the simulation depends on lives here as a named constant with
a comment, exactly as in ``microcluster/config.py``. Nothing elsewhere in
the ``simulation`` package hard-codes a tunable number.

None of these figures is clinical or epidemiological. They are chosen to
produce a legible demonstration outbreak on a small population, not
measured from real data. Tune them before drawing any real conclusion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from microcluster.config import BACKGROUND_RATE, DETECTION_WINDOW_HOURS
from microcluster.models import Category

# ---------------------------------------------------------------------------
# Infection state machine: state durations (illustrative, NOT clinical)
# ---------------------------------------------------------------------------

# On infection an agent spends this many days INCUBATING (already
# infectious, not yet reporting) before turning SYMPTOMATIC. Drawn
# uniformly per agent from this inclusive range. Kept short, together with
# SYMPTOMATIC_DAYS below, so a seeded suite's outbreak runs its course
# (and can burn out at a PARTIAL attack rate) inside the 30-day smoke
# window, rather than smouldering indefinitely -- see
# SUITE_TRANSMISSION_PROBABILITY below for how the two are tuned jointly.
INCUBATION_DAYS_MIN: int = 1
INCUBATION_DAYS_MAX: int = 2

# Once SYMPTOMATIC an agent stays symptomatic this many days before moving
# to RECOVERED. Drawn uniformly per agent from this inclusive range.
SYMPTOMATIC_DAYS_MIN: int = 1
SYMPTOMATIC_DAYS_MAX: int = 5


# ---------------------------------------------------------------------------
# Contact model: tiered by scope, reached through the ScopeRegistry
# ---------------------------------------------------------------------------
#
# Contact is not suite-only. On each daily step an infectious agent can
# transmit to a susceptible agent that shares its SUITE, its FLOOR (a
# different suite on the same floor), or its BUILDING (a different floor
# in the same building) -- at three different, decreasing per-contact
# probabilities. Campus-level contact is not modelled: two people who only
# share a campus are assumed not to meet. Which suite/floor/building an
# agent belongs to is read from the ScopeRegistry (chain_to_root), never
# hard-coded from id strings.
#
# Each probability compounds over however many infectious contacts an
# agent has at that tier:
#   P(infected today) = 1 - (1-p_suite)**k_suite
#                          * (1-p_floor)**k_floor
#                          * (1-p_building)**k_building
#
# All three, together with the state durations above, are chosen jointly
# and EMPIRICALLY (by running the model, not solved analytically) so that
# a single seeded suite typically reaches a PARTIAL, seed-varying attack
# rate -- roughly in the 40-70% range on most seeds, occasionally higher,
# occasionally fizzling out entirely from just the one index case -- rather
# than either dying out every time or deterministically infecting everyone.
# A small, fully-mixed suite is close to an all-or-nothing branching
# process: a real outbreak sometimes just fails to take off, and that is
# reported honestly (a low attack rate), not smoothed away. Floor and
# building transmission are lower than suite transmission but not
# negligible, so the outbreak reaches a second suite, and sometimes a
# second floor, well before it reaches everyone on the first floor.

# Probability that one infectious agent infects one susceptible SUITE-mate
# on a single day.
SUITE_TRANSMISSION_PROBABILITY: float = 0.008

# Probability that one infectious agent infects one susceptible agent in a
# DIFFERENT suite on the SAME FLOOR, on a single day. Lower than the suite
# rate: floor-mates share common areas but not a room.
FLOOR_TRANSMISSION_PROBABILITY: float = 0.003

# Probability that one infectious agent infects one susceptible agent on a
# DIFFERENT floor of the SAME BUILDING, on a single day. Lower still: the
# only shared contact is building-wide common space.
BUILDING_TRANSMISSION_PROBABILITY: float = 0.001


# ---------------------------------------------------------------------------
# Reporting behaviour
# ---------------------------------------------------------------------------

# Each agent is assigned, once at population creation, a personal
# probability of filing a symptom report while SYMPTOMATIC. Not everyone
# reports. Drawn uniformly per agent from this inclusive range.
REPORTING_PROBABILITY_MIN: float = 0.30
REPORTING_PROBABILITY_MAX: float = 0.70

# The outbreak clusters at ONE category, chosen once per simulation (rule
# 2: clustering is at category level only). The specific symptom text is
# still drawn from the fixed CHECKLIST for realism, but -- as everywhere
# else in this project -- it is never used for matching.
OUTBREAK_CATEGORY: Category = Category.RESPIRATORY

# BACKGROUND NOISE. Agents who are NOT currently symptomatic from the
# outbreak also file unrelated reports (a sore throat that is just a sore
# throat, a stomach bug that has nothing to do with any of this), each day,
# independently, at this rate, in a category OTHER than OUTBREAK_CATEGORY.
#
# This is what makes the detection problem real. Without background noise,
# every single report in the stream is outbreak signal, the absolute
# detector's BACKGROUND_RATE comparison is meaningless (there is no
# background to compare against), and detection is trivial. With it, the
# detector has to find a category-level cluster inside a stream that also
# contains ordinary, everyday, unrelated complaints.
#
# Chosen to land in the neighbourhood of microcluster.config.BACKGROUND_RATE
# (the illustrative fraction of a population expected to report per
# DETECTION_WINDOW_HOURS window under ordinary conditions), spread evenly
# across that window's days: BACKGROUND_RATE / (DETECTION_WINDOW_HOURS / 24).
BACKGROUND_NOISE_DAILY_RATE: float = BACKGROUND_RATE / (DETECTION_WINDOW_HOURS / 24)

# Reference wall-clock instant for simulated day 0. Every Report's
# ``submitted_at`` and every call to ``microcluster.engine.analyze`` is
# timestamped relative to this, so the 72-hour detection window is
# evaluated against SIMULATED time, never the real clock.
SIMULATION_START: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Seeding and run length
# ---------------------------------------------------------------------------

# Agents infected at day 0 when a run starts.
DEFAULT_SEED_INFECTIONS: int = 1

# Length of the smoke-test run, in days.
DEFAULT_RUN_DAYS: int = 30

# Random seeds the smoke-test entry point iterates over.
DEFAULT_SMOKE_SEEDS: tuple[int, ...] = (1, 2, 3, 4, 5)


# ---------------------------------------------------------------------------
# Experiment runner (simulation.experiments): establishment and the sweep
# ---------------------------------------------------------------------------
#
# A single seeded index case is a stochastic branching process: a real
# fraction of runs fail to take off at all, purely by chance, before the
# detector or the disclosure policy ever get a say. An outbreak counts as
# ESTABLISHED once its cumulative (ever-infected) case count reaches this
# many -- below it, the run is a fade-out from the index case, not a real
# event. This is a METHODOLOGICAL CHOICE, not a modelling fact: see
# simulation/experiments.py's module docstring for why it matters and how
# it is applied (report the fade-out rate on its own; condition every
# other statistic on establishment; never condition the false-alarm rate
# on it, since that is measured over the runs that did NOT establish).
ESTABLISHED_MIN_INFECTIONS: int = 5

# Default number of random seeds the experiment runner sweeps over.
DEFAULT_EXPERIMENT_SEEDS: int = 500

# The delay-versus-infections curve sweeps the DISCLOSURE gates, not the
# detection threshold. An earlier attempt swept ABSOLUTE_EXCESS_RATIO and
# found time-to-disclosure completely invariant to it: with detection
# firing well before disclosure clears anyway, it is the disclosure gates
# that set the timing. Detection config is held at defaults for all three
# sweeps below.
#
# Every one of these gates ultimately compares an INTEGER qualifying-report
# count (or a declared population) against a threshold, so each parameter
# only changes behaviour when it crosses a discrete boundary -- the scope
# populations are 25 / 75 / 150 (suite / floor / building = campus, since
# the default structure has one building), and ceil(sqrt(n)) is 5 / 9 / 13.
# The ranges below are deliberately WIDE enough that adjacent settings land
# in different regimes; a finer range would just print duplicate rows.

# microcluster.config.MIN_SCOPE_POPULATION -- privacy gate: n >= this.
# Regimes, given scope populations 25 / 75 / 150:
#   20  -> suite (n=25) still allowed        -> finest disclosure = SUITE
#   50  -> suite out, floor (n=75) allowed   -> finest = FLOOR
#   100 -> floor out, building (n=150) only  -> finest = BUILDING
#   200 -> nothing passes the privacy gate   -> nothing is ever disclosed
# 20 is the shipped default.
MIN_SCOPE_POPULATION_SWEEP: tuple[int, ...] = (20, 50, 100, 200)

# microcluster.config.STATISTICAL_GATE_FLOOR -- statistical gate:
# qualifying >= max(this, ceil(sqrt(n))). Below ceil(sqrt(25))=5 it does
# nothing to suite-level claims (5 is the shipped default). Each step up
# from there forces disclosure coarser and later: 8 and 12 keep it at
# FLOOR level but demand more evidence first; 16 and 25 push it to
# BUILDING. A suite is fraction-capped at 12 reports, so any floor >= 13
# makes suite-level disclosure impossible outright.
STATISTICAL_GATE_FLOOR_SWEEP: tuple[int, ...] = (5, 8, 12, 16, 25)

# microcluster.config.MAX_REPORT_FRACTION -- privacy gate:
# qualifying / n <= this. For a suite (n=25) the allowed count is
# floor(25 * fraction). Only three regimes exist in this scenario:
#   0.08 -> floor(2): even a floor cannot be named -> nothing disclosed
#   0.15 -> floor(3): suite forbidden (needs >= 5)  -> finest = FLOOR
#   0.25 -> floor(6): suite allowed                 -> finest = SUITE
# The shipped default (0.5 -> floor(12)) lands in the SAME regime as 0.25:
# suite report fractions never climb anywhere near it, so tightening from
# 0.5 down to ~0.2 changes nothing. It only starts to bite below that.
MAX_REPORT_FRACTION_SWEEP: tuple[float, ...] = (0.08, 0.15, 0.25)


# ---------------------------------------------------------------------------
# Benchmark (simulation.benchmark): learned detector vs the authored rules
# ---------------------------------------------------------------------------
#
# The benchmark builds a labelled dataset from simulated runs -- one row
# per (run, day), features taken from microcluster.detection's three plain
# findings, label taken from ground truth -- trains a small classifier on
# it, and scores that classifier against the hand-authored threshold rules
# in microcluster/config.py + detection.py on HELD-OUT runs. The model
# never replaces the authored rules; it is only ever scored beside them.
#
# Like every other figure in this file these are CHOSEN, not measured.

# Fraction of simulation RUNS (never days -- adjacent days from one
# outbreak are correlated and must not straddle the split) held out for
# evaluation.
BENCHMARK_TEST_RUN_FRACTION: float = 0.30

# Fixed seed for the train/test run split, so the benchmark is reproducible.
BENCHMARK_SPLIT_SEED: int = 20260906

# Max depth of the shallow decision tree (the legible alternative to
# logistic regression). Kept small on purpose: a deep tree just memorises
# this simulator.
BENCHMARK_TREE_MAX_DEPTH: int = 3

# Default number of seeds the benchmark simulates for its in-distribution
# dataset.
BENCHMARK_DEFAULT_SEEDS: int = 300

# CROSS-REGIME TEST. A model trained on this simulator learns this
# simulator. To see whether it learned anything transferable, it is also
# evaluated on runs generated with a DIFFERENT suite transmission
# probability than it trained on. Training uses the shipped
# SUITE_TRANSMISSION_PROBABILITY; evaluation additionally uses each of
# these (a slower and a faster epidemic).
BENCHMARK_TRAIN_SUITE_TRANSMISSION: float = SUITE_TRANSMISSION_PROBABILITY
BENCHMARK_TEST_SUITE_TRANSMISSIONS: tuple[float, ...] = (0.005, 0.012)


# ---------------------------------------------------------------------------
# Default structure: 1 campus > 1 building > 2 floors > 3 suites > 25 agents
# ---------------------------------------------------------------------------

# 1 * 2 * 3 * 25 = 150 agents. Declared populations then come out as
# suite n=25, floor n=75, building n=150, campus n=150.
DEFAULT_BUILDINGS: int = 1
DEFAULT_FLOORS_PER_BUILDING: int = 2
DEFAULT_SUITES_PER_FLOOR: int = 3
DEFAULT_AGENTS_PER_SUITE: int = 25

# Scope id and display label for the single campus root. Building / floor /
# suite ids are derived from this by the population builder.
CAMPUS_SCOPE_ID: str = "C"
CAMPUS_LABEL: str = "Campus"


@dataclass(frozen=True)
class SimulationConfig:
    """Tunable inputs to one simulation run. Defaults come from the module
    constants above; override per run for experiments."""

    incubation_days_min: int = INCUBATION_DAYS_MIN
    incubation_days_max: int = INCUBATION_DAYS_MAX
    symptomatic_days_min: int = SYMPTOMATIC_DAYS_MIN
    symptomatic_days_max: int = SYMPTOMATIC_DAYS_MAX
    suite_transmission_probability: float = SUITE_TRANSMISSION_PROBABILITY
    floor_transmission_probability: float = FLOOR_TRANSMISSION_PROBABILITY
    building_transmission_probability: float = BUILDING_TRANSMISSION_PROBABILITY
    reporting_probability_min: float = REPORTING_PROBABILITY_MIN
    reporting_probability_max: float = REPORTING_PROBABILITY_MAX
    outbreak_category: Category = OUTBREAK_CATEGORY
    background_noise_daily_rate: float = BACKGROUND_NOISE_DAILY_RATE
    simulation_start: datetime = SIMULATION_START
    seed_infections: int = DEFAULT_SEED_INFECTIONS
    campus_scope_id: str = CAMPUS_SCOPE_ID
    campus_label: str = CAMPUS_LABEL

    def __post_init__(self) -> None:
        for lo, hi, name in (
            (self.incubation_days_min, self.incubation_days_max, "incubation_days"),
            (self.symptomatic_days_min, self.symptomatic_days_max, "symptomatic_days"),
            (
                self.reporting_probability_min,
                self.reporting_probability_max,
                "reporting_probability",
            ),
        ):
            if lo > hi:
                raise ValueError(f"{name}: min {lo!r} exceeds max {hi!r}")
        if self.incubation_days_min < 1 or self.symptomatic_days_min < 1:
            raise ValueError("state durations must be at least 1 day")
        for probability in (
            self.suite_transmission_probability,
            self.floor_transmission_probability,
            self.building_transmission_probability,
            self.reporting_probability_min,
            self.reporting_probability_max,
            self.background_noise_daily_rate,
        ):
            if not 0.0 <= probability <= 1.0:
                raise ValueError(f"probability {probability!r} must be in [0, 1]")
        if not isinstance(self.outbreak_category, Category):
            raise ValueError(f"outbreak_category must be a Category, got {self.outbreak_category!r}")
        if self.seed_infections < 0:
            raise ValueError("seed_infections must be >= 0")


DEFAULT_SIMULATION_CONFIG = SimulationConfig()
