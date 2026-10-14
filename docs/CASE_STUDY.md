# Portfolio case study: from grid plans to wheel-driven robots

## Problem

A grid planner can produce connected joint checkpoints while the motion between
them loses communication or causes contacts. This project explores that gap by
executing CC-MAPF plans with wheel-driven robots in MuJoCo.

## Engineering contribution

The extension adds continuous transition scheduling, feedback from measured
robot state, predicted communication-tree selection, native wheel/roller physics,
and reproducible checks for contacts, connectivity, tracking and final goals.
The original CC-MAPF planner supplies the reference plans. Robot geometry comes
from Robot Soccer Kit via MuJoCo Menagerie / Rhoban Team; those assets retain
their MIT license and attribution. These components are not claimed as original
work of the extension.

## Demonstrated result

The frozen four-robot 16×16 warehouse demo completes 39.5 simulated seconds with
zero sampled robot/obstacle contacts, zero sampled disconnection and a maximum
final goal error of 10.082 mm. Maximum tracking error is 143.812 mm under the
`same_timestamp_v2` definition. Windows/Python 3.12 GitHub Actions runs the
focused tests and repeats the headless demo against its reference.

The broader historical four-robot evidence includes 48 regression runs and 12
validation runs with safety and goal passes. These are repeated conditions,
not 60 independent maps, and retain their historical tracking definitions.

## Trade-off and limits

The six-robot obstacle-feedback screen achieves safety and goal passes in three
executed nominal cases, but checkpoint error reaches 1.105 m in the open case.
A formation case times out during scheduling. Increasing team size therefore
remains experimental. Sampled simulation results do not establish formal safety,
real-time control or hardware performance.

The useful engineering lesson is to measure physical safety, tracking, goal
attainment and computation separately: a run can reach every goal while following
its planned trajectory poorly.

## Reproduce and inspect

- [Run the demo](../README.md#run-the-validated-demo).
- [Video and metric versions](DEMO.md).
- [Protocols, per-run evidence and known test timeout](RESULTS.md).
- [Current demo validation](results/demo-metric-v2-validation.json).
- [Robot asset attribution](../src/cc_mapf/assets/robot_soccer_kit/ATTRIBUTION.md).
