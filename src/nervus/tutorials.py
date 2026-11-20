"""The tutorials, by category: the single source for the tutorial overview, the docs navigation, the in-app help
list and the "at a glance" box and "Next" link of every tutorial (``scripts/gen_block_reference.py`` writes them).

Every tutorial is a page ``docs/tutorials/<slug>.md`` with a finished model in ``examples/``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tutorial:
    slug: str
    title: str
    category: str
    subcategory: str
    level: str  # beginner, intermediate, advanced
    minutes: int
    learn: str
    models: tuple[str, ...]
    before: tuple[str, ...] = ()
    """Slugs of tutorials to do first."""
    read_first: str = ""
    """A guide page to read first, as a docs link, e.g. ``[Physical modelling](../physical.md)``."""
    app_page: str = ""
    """Name of the in-app help page (default: ``tutorial_<slug with _>``)."""

    @property
    def help_page(self) -> str:
        return self.app_page or "tutorial_" + self.slug.replace("-", "_")


CATEGORIES: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("Getting started", "Start here: the editor, and how to organise larger models.", [("", "")]),
    ("Control engineering", "The experiments of a control-engineering lab course, each with a plant you can "
     "touch in the lab and the controller design that goes with it.",
     [("Classic lab experiments", "")]),
    ("Powertrain and engine control", "ECU functions of a petrol engine and its transmission, as they run in "
     "production cars.",
     [("Engine management", ""), ("Transmission and driveline", "")]),
    ("Vehicle dynamics and energy", "How a vehicle moves, uses energy, and stays controllable.",
     [("Longitudinal dynamics and energy", ""), ("Chassis control", "")]),
    ("Electrics and electronics", "Circuits from the textbook to the car's wiring harness and the ECU's "
     "circuit board, simulated like in LTspice.",
     [("Circuit fundamentals", ""), ("Vehicle electrical system", ""), ("ECU hardware and PCB", "")]),
    ("ECU software, communication and diagnostics", "What happens inside and between ECUs: networks, "
     "calibration, diagnostics and the C code itself.",
     [("Vehicle networks", ""), ("Diagnostics", ""), ("From model to ECU code", "")]),
    ("Testing and verification", "Showing that a function does what it should: requirements, tests and "
     "tolerances.", [("", "")]),
]  # fmt: skip

_ENGINE = "Powertrain and engine control"
_VEH = "Vehicle dynamics and energy"
_EL = "Electrics and electronics"
_ECU = "ECU software, communication and diagnostics"

TUTORIALS: list[Tutorial] = [
    # ------------------------------------------------------------------ getting started
    Tutorial("first-model", "Your first model: a cruise control", "Getting started", "", "beginner", 30,
             "the editor, blocks and wires, workspace variables, scopes, the Data Inspector, PI control and "
             "integrator windup", ("cruise_control.nervus",)),
    # ------------------------------------------------------------------ control labs
    Tutorial("mass-spring-damper", "Position control of a mass-spring-damper", "Control engineering",
             "Classic lab experiments", "beginner", 30,
             "what the P, I and D terms do, natural frequency and damping ratio, steady-state error, actuator "
             "limits and anti-windup", ("mass_spring_damper_pid.nervus",), ("first-model",)),
    Tutorial("dc-motor", "DC motor speed and position control", "Control engineering", "Classic lab experiments",
             "intermediate", 45, "system identification from a step response, PI design by pole-zero "
             "cancellation, PD design from damping and natural frequency, a physical motor model and a 1 kHz "
             "controller", ("dc_motor_speed.nervus", "dc_motor_position.nervus"), ("mass-spring-damper",)),
    Tutorial("coupled-tanks", "Level control of coupled water tanks", "Control engineering", "Classic lab experiments",
             "intermediate", 40, "a nonlinear process, linearization at an operating point, PI design for a "
             "second-order process, gain scheduling, actuator limits", ("coupled_tanks.nervus",),
             ("dc-motor",)),
    Tutorial("inverted-pendulum", "Balancing an inverted pendulum with state feedback", "Control engineering",
             "Classic lab experiments", "advanced", 45, "an unstable plant, state-space models, LQR state "
             "feedback, non-minimum-phase behaviour, redesigning a gain in the Console",
             ("inverted_pendulum.nervus",), ("dc-motor",)),
    # ------------------------------------------------------------------ engine
    Tutorial("idle-speed-control", "Idle speed control", _ENGINE, "Engine management", "beginner", 45,
             "how an ECU holds the idle speed: a mean-value engine model, a PI controller with feed-forward, "
             "requirements as test cases, C code", ("idle_speed_control.nervus",), ("first-model",), app_page="tutorial_idle"),
    Tutorial("lambda-control", "Lambda control and fuel trims", _ENGINE, "Engine management", "intermediate", 45,
             "why petrol engines run at lambda = 1, closed-loop fuel control with a lambda sensor, short- and "
             "long-term fuel trims (as read over OBD-II), an ECU task in an atomic subsystem",
             ("lambda_control.nervus",), ("idle-speed-control",), app_page="tutorial_lambda"),
    Tutorial("ignition-knock", "Ignition timing and knock control", _ENGINE, "Engine management", "intermediate", 30,
             "spark advance from a speed/load map (2-D lookup table), knock and the knock limit, a knock "
             "controller that retards and recovers, noisy sensors", ("ignition_knock.nervus",),
             ("idle-speed-control", "lambda-control"), app_page="tutorial_ignition"),
    Tutorial("fuel-film", "Wall wetting and learned fuel trims", _ENGINE, "Engine management", "intermediate", 30,
             "fuel film dynamics (x-tau) and transient compensation, a switching lambda sensor, long-term trims "
             "learned per load cell (Adaptive Map)", ("fuel_film.nervus",), ("lambda-control",)),
    Tutorial("gear-shift", "Gear-shift logic", _ENGINE, "Transmission and driveline", "intermediate", 60,
             "an automatic gearbox's shift schedule, hysteresis, a State Chart in its own ECU task, kickdown and "
             "hills, fuel consumption per gear", ("gear_shift.nervus",), ("first-model", "drive-cycle"),
             "[State machines](../statecharts.md)"),
    Tutorial("truck", "A truck on a mountain road", _ENGINE, "Transmission and driveline", "intermediate", 30,
             "heavy-duty vehicles: a diesel's narrow torque band, a 12-speed automated gearbox (State Chart), "
             "cruise control, an exhaust brake on a descent", ("truck.nervus",), ("drive-cycle", "gear-shift")),
    # ------------------------------------------------------------------ vehicle
    Tutorial("drive-cycle", "A car on a drive cycle", _VEH, "Longitudinal dynamics and energy", "beginner", 40,
             "vehicle longitudinal dynamics, a driver model, standard drive cycles (ECE-15, WLTC, FTP-75), where "
             "the energy goes, fuel consumption", ("drive_cycle.nervus",), ("first-model",)),
    Tutorial("traction-control", "Tyre slip and traction control", _VEH, "Chassis control", "intermediate", 30,
             "tyre slip and Pacejka's magic formula, wheel and vehicle dynamics, a traction control ECU on dry, "
             "wet and snowy roads", ("traction_control.nervus",), ("first-model",), app_page="tutorial_traction"),
    # ------------------------------------------------------------------ electrics and electronics
    Tutorial("circuits", "Rectifier, relay driver, buck converter and active filter", _EL, "Circuit fundamentals",
             "advanced", 45, "circuit simulation like LTspice: a rectifier, a relay driver and its freewheeling "
             "diode, a buck converter, an active filter; SPICE netlists",
             ("rectifier.nervus", "relay_driver.nervus", "buck_converter.nervus", "active_filter.nervus"),
             ("physical-models",)),
    Tutorial("physical-models", "Starter motor and electronic throttle", _EL, "Vehicle electrical system",
             "intermediate", 45, "physical modelling (circuits, shafts, springs connected by links instead of "
             "signals): cranking an engine on a weak battery, a drive-by-wire throttle servo",
             ("starter_motor.nervus", "electronic_throttle.nervus"), ("first-model",),
             "[Physical modelling](../physical.md)", app_page="tutorial_physical"),
    # ------------------------------------------------------------------ ECU software
    Tutorial("can-network", "A vehicle network (CAN)", _ECU, "Vehicle networks", "advanced", 40,
             "ECUs on simulated CAN buses: DBC files, arbitration and bus load, a gateway, rest-bus simulation, "
             "E2E protection, fault injection and timeouts, the bus trace", ("can_network.nervus",),
             ("first-model",), "[CAN communication](../can.md)"),
]  # fmt: skip


def by_slug() -> dict[str, Tutorial]:
    return {t.slug: t for t in TUTORIALS}


def ordered() -> list[Tutorial]:
    """All tutorials in the order of the categories and subcategories."""
    out = []
    for cat, _intro, subs in CATEGORIES:
        for sub, _ in subs:
            out += [t for t in TUTORIALS if t.category == cat and t.subcategory == sub]
    return out
