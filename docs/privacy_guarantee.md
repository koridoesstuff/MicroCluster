# What the two gates guarantee, in established terms

This is the exact privacy property the gates provide, mapped onto the
standard vocabulary, followed by what they do **not** provide. Nothing here
claims more than the gates enforce. The property is a deterministic
invariant on every disclosure; it is not a probabilistic guarantee.

## The mechanism, restated

A disclosure names at most one scope `S`, with declared population `n`
(fixed at group creation, never counted from reports) and `q` qualifying
reports in the current detection window. The engine evaluates, on the exact
`q`, server side:

- **Evidence gate:** `q >= max(5, ceil(sqrt(n)))`
- **Privacy gate:** `n >= 20` **and** `q / n <= 0.5`

`S` may be named only if both pass. The page is only ever shown a band for
`q` (`5-9`, `10-19`, ...), never the exact count.

## The invariant (what is guaranteed)

For every scope the system names, at every moment:

```
n  >=  20                       (group-size floor)
q  >=  max(5, ceil(sqrt(n)))    (minimum support)
q  <=  n / 2                    (prevalence cap)
```

This holds by construction: the disclosure is selected from the evaluation
table and cannot be produced without passing both gates. It was also checked
independently of the engine on about 540,000 scope evaluations across
150 to 2,000 agents (`results/scale.json`): zero formula violations, zero
selected-without-both-gates.

### 1. Group-size floor: a k-anonymity-style property, k = 20

The released statement is "scope `S` shows unusual illness activity". The
only quasi-identifier in the release is the location group, and reports
carry nothing finer than a group (fixed checklist, no free text, no room).
Every named group has at least 20 declared members, so the statement cannot
single out an individual by location: any member of `S` is indistinguishable,
within this release, from the other `n - 1 >= 19`. That is k-anonymity in the
sense of Samarati and Sweeney (2002), with k = the declared group size,
floored at 20.

Precisely scoped: it is anonymity of the *group the statement is about*, not
of the reporters. It says nothing about who inside the group reported.

### 2. Minimum support: a threshold rule

No scope is named on fewer than 5 reports, and larger scopes need more
(`ceil(sqrt(n))`). This is the classic minimum-frequency / small-cell
threshold rule of statistical disclosure control. Its job is evidential (do
not name a big group on thin evidence) and it doubles as a small-cell floor
(a single report can never produce a disclosure). The `sqrt(n)` growth is a
chosen policy shape, not a derived bound.

### 3. Prevalence cap: a bound on the homogeneity attack

k-anonymity's known weakness is homogeneity: if everyone in the group shares
the sensitive attribute, membership discloses it. Here the sensitive
attribute is "filed a report". Because distinct reporters are at most `q`,
and `q <= n / 2`, at most half the group can be reporters. An observer who
knows only "person X is in the named group" can therefore assign X a
probability of having reported of at most `q / n <= 0.5` (uniform prior, no
side information). Naming a group where most members reported would be
naming a roster; the cap forbids it.

This is in the spirit of l-diversity and t-closeness (do not let group
membership determine the sensitive value) and of the dominance rule in cell
suppression (do not publish a cell one contributor pattern dominates). It is
**not** literally either: it is a simple prevalence cap, and there is no
diversity or distribution-distance measure behind it.

**Summary in established terms:** a k-anonymity-style group-size floor
(k >= 20) plus a minimum-support threshold rule plus a prevalence cap, all
deterministic, all on declared population and exact server-side counts.

## What it does not guarantee

### It is not differential privacy

Differential privacy requires that adding or removing any one person's data
changes the output distribution by at most a factor of `e^epsilon` (plus a
small `delta`), for every dataset and every output, typically by injecting
calibrated randomness. The gates are the opposite kind of object:

- **Deterministic threshold on exact counts.** There is no noise. Whether a
  scope is named is a step function of `q`. One report can move `q` from
  `threshold - 1` to `threshold`, flipping the output from "nothing" to
  "names S" with probability 0 versus 1. The likelihood ratio between
  neighbouring datasets is unbounded, so epsilon is infinite.
- **No privacy budget and no composition.** DP composes: each release spends
  budget and the total is accountable. k-anonymity-style rules do not
  compose. The system releases a disclosure every day over overlapping
  windows of nearly the same data, and the sequence leaks more than any one
  release (composition attacks on k-anonymity are documented; here it shows
  up as the differencing residual and scope wandering below).
- **No robustness to auxiliary information.** DP holds against an adversary
  who knows everything except one record. The gates do not. An adversary who
  controls or knows `q - 1` of the reports (report injection, see below)
  learns one bit about the last report from whether the scope is named: the
  boundary itself is the leak.

### Other things it does not guarantee

- **Repeated releases.** Bands remove the exact one-person overnight pin
  (358 pins against exact counts, 0 against bands), but the direction of the
  overnight change is still forced on 204 of 1,171 same-scope day-pairs, and
  with scope stability off a run names about 3.1 distinct groups versus 1.6.
  Leakage reduced, not removed (`results/adversarial.json`).
- **Side information.** A target's group is named; an attacker who already
  knows the target lives there and has an out-of-band signal about them gets
  a weak update, never confirmation.
- **Injection.** The submission cap is rate limiting, not authentication. An
  attacker rotating session ids manufactures a false disclosure at the same
  report cost (9 reports for a 75-person floor); see
  `adversarial/injection.py`.
- **Group-level harm.** Naming a group at all says "this group has unusual
  illness". The gates bound how small or how saturated that group may be;
  they do not make it harmless to the people in it.
- **Truthfulness of `n`.** `k` is the *declared* population. The system does
  not verify membership; an operator declaring a misleading `n` defeats the
  floor.
- **Distinct reporters.** `q` counts reports, and one person can file up to
  the session cap. The prevalence bound is on reports (an upper bound on
  distinct reporters), not a minimum number of distinct people.
- **Protection from the operator.** The server holds the reports; the
  guarantee concerns what is disclosed, not what is stored.
- **A derived constant.** 20, 5, `sqrt(n)` and 0.5 are policies chosen for
  legibility, not values derived from a stated risk model.

## The claim, in one sentence

Every disclosed group has at least 20 people, is supported by at least five
reports, and has at most half its members among the reporters; nothing is
promised beyond that.
