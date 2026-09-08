# MicroCluster

A privacy-preserving health-signal system for small shared communities (a
dorm floor, an office floor, a co-op), with a headless agent-based
outbreak simulator wrapped around it so the detection and disclosure
engines can be exercised end to end.

**Thesis: it detects the signal without identifying the reporter, and
won't name a group too small or too covered to name safely.**

This is an illustrative simulation. Every parameter is chosen for
demonstration, not measured; it predicts nothing about any real building,
and no one is diagnosed or treated by it.

## What is here

| Package | Purpose |
|---|---|
| `microcluster/` | detection engine (relative + absolute detectors) and disclosure engine (two gates, scope selection). The foundation; unchanged by the simulator. |
| `simulation/` | agent-based SIR-style model, tiered contact, anonymous report generation, and the pipeline that feeds the real engines day by day. |
| `simulation/experiments.py` | the disclosure-gate sweep: how much later disclosure happens, and how many more infections, as each privacy gate is tightened. |
| `simulation/benchmark.py` | a small classifier trained on the three detection findings, scored against the authored threshold rules on held-out runs, in and out of the training regime. |
| `adversarial/` | a self-test: an observer who sees only what the UI shows runs the differencing attack against exact counts and against bands. |
| `api/` + `web/` | a FastAPI service and a plain-JS floor-plan animation with a live gate table, a resolution slider, and the precomputed results panels. |
| `scripts/` | `precompute_results.py` (caches the three analyses to `results/*.json`), `verify_epidemic_curves.py` (Week-1 curve sanity check). |
| `docs/` | demo video script, one-page submission doc (`.md` source, `.html` print source, generated `.pdf`), a red-team `anticipated_questions.md`, deployment notes. |

## Run it

Python 3.10 or newer (developed on 3.14; every module uses
`from __future__ import annotations`, so nothing needs a specific point
release).

```
pip install -r requirements.txt
python -m pytest                         # full suite: 223 passing
python -m unittest discover -s tests     # same tests, stdlib runner
python -m scripts.precompute_results     # regenerate results/*.json (~30s)
uvicorn api.app:app                      # then open http://127.0.0.1:8000/
```

**Regenerate the submission PDF.** `docs/one_pager.html` is the print
source for `docs/one_pager.pdf`. With any Chromium on PATH:

```
chrome --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf=docs/one_pager.pdf docs/one_pager.html
```

Keep the prose in `docs/one_pager.html` and `docs/one_pager.md` in sync.

`python -m microcluster.demo` prints the seven reference disclosure
scenarios; `python -m adversarial` prints the differencing-attack numbers;
`python -m scripts.verify_epidemic_curves` prints the epidemic-curve
plausibility check.

To deploy the web app to a free host, see [`docs/deployment.md`](docs/deployment.md)
(`render.yaml` is ready; only account creation and connecting the repo are
manual).

## Prior art

Neither of the two ideas this project builds on is original here.

**Agent-based epidemic simulation.** Compartmental epidemic models go back
to Kermack & McKendrick (1927); the susceptible / incubating / symptomatic
/ recovered progression this simulator uses is the standard SEIR shape.
Agent-based implementations of it are a mature field with many mature
tools (Covasim, FRED, EpiModel, Mesa, and others). The transmission,
contact, incubation and reporting numbers here are not calibrated to
anything and are stated as illustrative throughout.

**Small-cell suppression in published data.** Refusing to release a
statistic about a group too small or too completely covered to be safe is
long-standing practice in official and public-health statistics: cell
suppression and complementary suppression in tabular releases, the
"minimum cell size" rules used by statistical agencies, k-anonymity
(Sweeney, 2002), and, as the modern formal treatment, differential privacy
(Dwork, 2006). The two-gate disclosure policy here (a statistical gate
that scales up with population, a privacy gate that scales down) is a
plain instance of that family, not a new mechanism.

**What is combined here.** The disclosure policy is wired directly into
the output of an anomaly detector, so the signal and its suppression are
one server-side pipeline rather than two separate steps, and the whole
thing is framed for a specific deployment: anonymous, fixed-checklist
symptom reports from the residents of one shared building. The measurement
attached to it -- how many extra infections each day of
privacy-mandated delay costs, and what an observer can still infer from
the banded output -- is the part worth looking at.

## Limitations

Stated in full on every page of the web UI and in
`simulation/config.py`. In short: synthetic data, chosen parameters, no
real-world validation, indirect health impact (understanding, not
intervention). The learned model is kept beside the authored rules for
comparison and never replaces them.
