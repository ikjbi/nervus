# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Desktop editor (`nervus` command), built with PySide6 in a Model–View–Controller structure: canvas with
  drag-and-drop blocks and wires, block library with search, property editor with expressions and MATLAB-style
  matrices, undo/redo for every edit, copy/paste, diagnostics panel, threaded simulation with progress and stop,
  scope windows with hover readout, simulation settings dialog, recent files, light and dark themes.
- In-app help: user guide pages and the full block reference (F1 on a selected block), with typeset LaTeX
  equations and explanatory figures.
- Block figures (`scripts/gen_figures.py`) and editor screenshots (`scripts/screenshots.py`) for the docs.
- LaTeX equations in every block's documentation.
- Automatic left-to-right layout for diagrams without block positions.
- Simulation engine: block base class, diagrams, width propagation, execution ordering, algebraic loop
  detection, sample-time inheritance, multi-rate discrete scheduling.
- Solvers: fixed-step Euler and RK4; variable-step RK45, RK23, DOP853, Radau, BDF and LSODA (via SciPy).
  Variable-step solvers stop exactly at discontinuities declared by blocks.
- Simulation results with access by block name, CSV and pandas export.
- Model files (`.nervus`, JSON) with schema versioning and migrations; simulation settings stored per diagram.
- Examples: PID control of a mass-spring-damper, electronic throttle control with a discrete PI.
- Documentation: getting started, concepts, coming from Simulink, model files, architecture, writing blocks,
  and a block reference generated from the code.
- Block library (30 blocks): Constant, Step, Ramp, Sine Wave, Pulse Generator, Clock, From Workspace, Gain,
  Sum, Product, Abs, Saturation, Math Function, Integrator, Derivative, Transfer Fcn, State-Space, Unit Delay,
  Zero-Order Hold, Discrete-Time Integrator, Discrete Transfer Fcn, PID Controller, Discrete PID Controller,
  Scope, To Workspace, Terminator, Mux, Demux, Switch, Python Function.
- Project setup: packaging (uv/hatchling), linting (ruff), type checking (mypy), tests (pytest), CI, docs skeleton.
