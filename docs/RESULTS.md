# Execution evidence and limitations

Reference planner: `connected_step` at
`4e7419e584f6f1633624ffd440296a14d8da769e`. Generation isolates the original
source. All physical runs use 1 m/cell, radius-1 Manhattan connectivity, a 1 m/s
velocity cap, native wheel physics and a 2 ms integration step.

## Four-robot tree selection

The candidate ranks an MST at positions predicted from measured velocity.
Every selected edge must currently be within range; otherwise it falls back to
the current-position MST. Motion prediction is 250 ms, settling prediction
125 ms, and quarter-waypoint timing 0.625 s. The paired comparison changes
tree selection while retaining the other controller settings.

Saved regression: 12 cases on 16×16, 20×20 and 24×24 grids, with four families
(open, corridor, warehouse, formation shift). Six profiles on 16×16 cases and
three on larger cases total 48 runs. New validation uses four 28×28 seed-109
cases with nominal and two combined profiles, totaling 12 runs.

Position perturbations sample robots within a 20 mm disk, conditioned on initially
connected, contact-free states, with seeds 7 and 19. Dynamics multiply mass and
inertia by 1.2 and geometry friction by 0.7. These are simulator parameter
variations, not identified hardware uncertainty.

A safety/goal pass requires completion, zero disconnected samples, zero robot
or obstacle contact samples, zero numerical warnings and final goal error below
20 mm. Tracking error is separate and is not a pass threshold.

| Metric | Current-tree baseline | Future-tree candidate |
|---|---:|---:|
| Saved safety/goal passes | 48/48 | 48/48 |
| Worst checkpoint error | 589.866 mm | 152.367 mm |
| Worst error across 2 ms samples | 590.321 mm | 175.700 mm |
| Physical duration | Paired reference | Unchanged |

Seven runs improve by more than 1 mm, none worsen by more than 1 mm and 41
remain within ±1 mm. Maximum worsening is 0.389 mm. The reporting threshold
is separate from the safety/goal criterion. New validation: 12/12 passes,
checkpoint maximum 152.528 mm, all-sample maximum 152.832 mm and final-goal
maximum 11.542 mm. The candidate is fixed before new physical runs; previous
larger-map holdouts are development data.

- [Aggregate audit](results/four-robot-summary.json)
- [Paired comparison](results/four-robot-comparison.csv)
- [48 regression records](results/four-robot-regression.csv)
- [12 new validation records](results/four-robot-validation.csv)

Generate new reference plans and evaluate the same protocol:

```bash
python scripts/dev/prepare_tracking_holdout.py --size 28 --seed 109 --output artifacts/mujoco/new-reference
python scripts/dev/validate_traction.py --future-tree --step-seconds .625 --reference artifacts/mujoco/new-reference --cases open_28x28_4a_s109 corridor_28x28_4a_s109 warehouse_28x28_4a_s109 formation_shift_28x28_4a_s109 --profiles nominal combined-s07 combined-s19 --output artifacts/mujoco/new-validation
```

The pinned commit must exist in the checkout. Planner choices may depend on
elapsed-time budgets. These commands reproduce the protocol; the bundled demo
reproduces one exact frozen plan.

## Six-robot feasibility screen

Six-agent scheduling and feedback require explicit experimental opt-in. The
initial future-tree open 20×20 seed-1 execution records 24 contact samples,
despite maintaining connectivity and reaching goals.

The obstacle candidate adds box-clearance halfspaces and projects speed bounds
inside the joint radio/pair/obstacle loop: 64 iterations maximum, 20 mm obstacle
margin, residual tolerance 1 micrometre. Both obstacle handling and projection
ordering change, so improvement cannot be attributed solely to the obstacle term.

| Six-robot nominal case | Contact samples | Disconnected time | Checkpoint error | Final goal error |
|---|---:|---:|---:|---:|
| Open | 0 | 0 s | 1105.002 mm | 10.019 mm |
| Corridor | 0 | 0 s | 875.876 mm | 10.460 mm |
| Warehouse | 0 | 0 s | 650.919 mm | 9.911 mm |
| Formation | Not executed | Not executed | Not executed | Scheduling timeout |

Open duration stays 77 s, but checkpoint error grows from 368.625 to 1105.002 mm.
Four nominal four-robot anchors also pass; they do not replace the 48-run regression.
Three physical successes do not establish a complete four-family pipeline pass.
[Nominal records, including anchors](results/six-robot-nominal.csv).

Reproduce the exact open-case screen from the bundled frozen input:

```bash
python scripts/dev/evaluate_six_robot.py --variant obstacle --reference configs/reference/six_robot --cases open_20x20_6a_s01 --profiles nominal --step-seconds .625 --output artifacts/mujoco/six-screen
```

This expensive offline experiment is separate from the four-robot demo. Its
[reference metrics](results/six-open-reference.json) document the expected
tracking trade-off. Generated outputs retain raw reports and residual audits.

At the reproduced open peak, feedback commands a bridge robot away from its
waypoint. The desired replacement link is 1.433 m apart, beyond the unchanged
1 m radius. Measured velocity closely follows the constrained command. Removing
obstacle constraints at that snapshot does not change it. This identifies a
link-handoff problem at that state, not a universal explanation.

Controller median/p95: open 4.178/8.826 ms, corridor 3.724/8.635 ms, warehouse
5.841/12.272 ms. Some runs share CPU load. Timing excludes physics and audit
instrumentation and exceeds the 2 ms simulated interval. Real-time execution is
unproven. Formation's five-second local detour search times out; this does not
prove that a feasible detour cannot exist. Contact counts are 2 ms samples,
not distinct collision events.

No six-robot disturbance sweep, independent seeds or 8/10-robot physical
expansion is claimed. Next priority: coordinated link handoff with acceptable
tracking while preserving all safety checks.

## Interpretation

The contribution is an execution and validation layer around the original
planner. Checkpoint validity, physical safety, tracking fidelity and compute
cost are separate metrics. Sampled simulation success is empirical evidence for
these tests, not a continuous-time guarantee. One predicted MST plus fallback
is a heuristic. Bounded projection provides neither an optimal command nor an
infeasibility certificate. Hardware, other radio models and robot geometries,
and dense 8/10-robot teams remain untested.

## Publication checks

The local full test run records **99 passed, 1 failed**. The remaining failure is
`test_connected_step_solves_representative_large_formation_case`: 12 robots on
32×32 with a 12 s planner budget time out on the tested machine. This limit is
reported rather than weakening the assertion or claiming a fully passing suite.
An isolated run of the pinned original planner also times out under that same
12 s budget (observed runtime 12.267 s), reproducing the limit before the extension.
The simulator, scheduler and protocol tests pass. Graphics fixes cover the
supported Matplotlib API and portable manifest paths on Windows.

The Python wheel builds successfully with all 30 STL files and the asset license.
The four-robot demo also reproduces its reference metrics from a checkout
containing only the selected publication files. Rendering reproduces the same
physical metrics; the 1080p MP4 decodes through its final frame.

The bundled six-robot open reference is rerun during publication. Its safety,
duration, checkpoint tracking and final goals reproduce the previous candidate
result within 1 micrometre. The 1105 mm tracking error remains. This repeat is
a reproducibility check, not an independent validation case.
[Tested environment](results/tested-environment.json) records the local package
versions. Equivalent execution on other operating systems is not validated.
