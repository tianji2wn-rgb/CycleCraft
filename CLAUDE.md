# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CycleCraft (自动化设备动作时序图计算软件) — an industrial automation cycle-time (CT) and throughput (UPH) estimator. It models multi-station equipment operations as a DAG of timed action nodes with FS/SS dependencies, computes absolute start/end times, identifies the critical path (bottleneck), and calculates theoretical UPH.

## Commands

```bash
# Run the CLI demo (prints timing table + UPH + critical path)
uv run main.py

# Run the NiceGUI web app (starts server on 127.0.0.1:8080)
uv run gui.py
```

No test suite, linter, or CI/CD is configured.

## Architecture

```
src/cyclecraft/          # Core library (importable package)
  models.py              # ActionNode, Dependency, DependencyType(FS/SS)
  engine.py              # SequenceCalculator (DAG engine) + calculate_uph()
  __init__.py            # Re-exports all public API
main.py                  # CLI demo: hardcoded 6-node pipeline
gui.py                   # NiceGUI web app: interactive Gantt chart editor
```

### DAG Engine (`engine.py`)

`SequenceCalculator` builds an **event-level** directed graph using NetworkX:
- Each `ActionNode` becomes two events: `S_{id}` (start) and `E_{id}` (end), connected by an edge weighted with `duration`.
- A virtual `Start` and `End` node anchor the graph. Every action's start connects from `Start`; every action's end connects to `End`.
- **FS** (Finish-to-Start) edges go from `E_pred -> S_succ` (with optional delay).
- **SS** (Start-to-Start) edges go from `S_pred -> S_succ` (with optional delay).
- Cycle detection (`nx.is_directed_acyclic_graph`) runs before computation.
- Critical path = longest path from `Start` to `End` via topological sort (SSLP algorithm).

### GUI (`gui.py`)

Single-file NiceGUI app (~700 lines). Key state:
- `calculator` — global `SequenceCalculator` instance (the single source of truth).
- `row_action_ids` — maps Gantt chart bar indices to action IDs.

Features: add/edit/delete actions, inline duration editing in the data table, project save/load as JSON, ECharts Gantt/swimlane chart with critical path highlighted in red, dashboard showing CT/UPH/critical path.

### Data Model (`models.py`)

All dataclasses. `DependencyType` is an enum with two values: `FS` and `SS`. Durations and delays are in **milliseconds**.

## Conventions

- **Language**: Code comments, docstrings, UI labels, and user-facing messages are in **Chinese**.
- **Python version**: 3.8+ (declared in `pyproject.toml`; `.venv` runs 3.14).
- **Dependency management**: `uv` (lockfile: `uv.lock`). Do not use `pip` directly.
- **Module path**: Both `main.py` and `gui.py` manually insert `src/` into `sys.path` — the package is not installed in editable mode.
- **Serialization**: Project files use JSON with `ensure_ascii=False` for Chinese text. `deserialize_project` is transactional — it rolls back on failure.
- **No tests exist** — when adding tests, use `pytest` and create a `tests/` directory.
