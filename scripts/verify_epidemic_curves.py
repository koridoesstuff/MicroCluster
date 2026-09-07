"""Week 1 sanity check: do the simulator's epidemic curves look plausible?

    python -m scripts.verify_epidemic_curves

Runs the headless simulator across a range of seeds and prints, per seed,
the peak active count, the day it peaks, the final attack rate, and the
curve shape. Then a PASS/FAIL summary: not always-zero, not
always-everyone, most established outbreaks rise then turn over. This is a
milestone record, not a test -- the assertions live in
tests/test_simulation.py::EpidemicCurvePlausibilityTest.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulation.infection import InfectionState  # noqa: E402
from simulation.simulator import Simulation  # noqa: E402

SEEDS = range(1, 41)
DAYS = 30
ESTABLISHED = 10


def main() -> None:
    total = len(Simulation(seed=1).agents)
    established = fizzled = turned_over = 0
    worst_attack = 0.0

    print(f"{total} agents, {DAYS} days, seeds {SEEDS.start}..{SEEDS.stop - 1}")
    print(f"{'seed':>4} {'peak':>5} {'peak_day':>8} {'attack%':>8}  shape")
    for seed in SEEDS:
        history = Simulation(seed=seed, seed_infections=1).run(DAYS)
        active = [
            h.count(InfectionState.INCUBATING) + h.count(InfectionState.SYMPTOMATIC)
            for h in history
        ]
        cumulative = sum(
            1 for a in history[-1].agents if a.state is not InfectionState.SUSCEPTIBLE
        )
        peak = max(active)
        peak_day = active.index(peak)
        attack = cumulative / total * 100
        worst_attack = max(worst_attack, attack)

        shape = []
        if cumulative >= ESTABLISHED:
            established += 1
            if peak > active[0]:
                shape.append("rise")
            if peak_day <= DAYS - 3 and active[-1] < peak:
                shape.append("decline")
                turned_over += 1
        elif cumulative <= 3:
            fizzled += 1
            shape.append("fizzle")
        print(f"{seed:>4} {peak:>5} {peak_day:>8} {attack:>7.1f}  {'/'.join(shape)}")

    n = len(list(SEEDS))
    checks = [
        (established > 5, f"established outbreaks: {established}/{n} (> 5)"),
        (established < n, f"non-degenerate: {n - established}/{n} did not take off"),
        (fizzled > 0, f"index-case fizzle happens: {fizzled}/{n}"),
        (worst_attack > 40.0, f"a real outbreak occurs: worst attack {worst_attack:.0f}% (> 40)"),
        (worst_attack < 100.0, f"never everyone: worst attack {worst_attack:.0f}% (< 100)"),
        (
            turned_over >= 0.6 * established,
            f"most established outbreaks peak then decline: {turned_over}/{established}",
        ),
    ]
    print()
    ok = True
    for passed, label in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    print()
    print("RESULT:", "believable outbreaks" if ok else "SOMETHING IS OFF")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
