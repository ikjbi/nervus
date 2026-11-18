# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Simulation engine: block base class, diagrams, width propagation, execution ordering, algebraic loop
  detection, sample-time inheritance, multi-rate discrete scheduling.
- Solvers: fixed-step Euler and RK4; variable-step RK45, RK23, DOP853, Radau, BDF and LSODA (via SciPy).
  Variable-step solvers stop exactly at discontinuities declared by blocks.
- Simulation results with access by block name, CSV and pandas export.
- Block library (30 blocks): Constant, Step, Ramp, Sine Wave, Pulse Generator, Clock, From Workspace, Gain,
  Sum, Product, Abs, Saturation, Math Function, Integrator, Derivative, Transfer Fcn, State-Space, Unit Delay,
  Zero-Order Hold, Discrete-Time Integrator, Discrete Transfer Fcn, PID Controller, Discrete PID Controller,
  Scope, To Workspace, Terminator, Mux, Demux, Switch, Python Function.
- Project setup: packaging (uv/hatchling), linting (ruff), type checking (mypy), tests (pytest), CI, docs skeleton.
