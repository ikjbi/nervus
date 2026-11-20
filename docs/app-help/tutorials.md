# Tutorials

14 tutorials, grouped by topic. Each one uses a finished model in `examples/`: open it in the editor, run it, read why it behaves as it does, then change it. They are built around problems from the automotive industry and the classic experiments of engineering lab courses.

Every tutorial has the same parts:

- **At a glance**: what you will learn, what to do first, the level and the time it takes.
- **Follow along**: which model to open, and what to run and look at.
- **Experiments**: changes to try, each with the effect you should see.
- **Next**: the next tutorial on the same topic.

New to Nervus? Start with ***Your first model: a cruise control***: it builds a model from scratch in the editor, step by step, with a screenshot for each step. Then pick a topic.

## Getting started

Start here: the editor, and how to organise larger models.

| Tutorial | Level | Time | You will learn |
|---|---|---|---|
| *Your first model: a cruise control* | beginner | 30 min | the editor, blocks and wires, workspace variables, scopes, the Data Inspector, PI control and integrator windup |

## Control engineering

The experiments of a control-engineering lab course, each with a plant you can touch in the lab and the controller design that goes with it.

### Classic lab experiments

| Tutorial | Level | Time | You will learn |
|---|---|---|---|
| *Position control of a mass-spring-damper* | beginner | 30 min | what the P, I and D terms do, natural frequency and damping ratio, steady-state error, actuator limits and anti-windup |
| *DC motor speed and position control* | intermediate | 45 min | system identification from a step response, PI design by pole-zero cancellation, PD design from damping and natural frequency, a physical motor model and a 1 kHz controller |

## Powertrain and engine control

ECU functions of a petrol engine and its transmission, as they run in production cars.

### Engine management

| Tutorial | Level | Time | You will learn |
|---|---|---|---|
| *Idle speed control* | beginner | 45 min | how an ECU holds the idle speed: a mean-value engine model, a PI controller with feed-forward, requirements as test cases, C code |
| *Lambda control and fuel trims* | intermediate | 45 min | why petrol engines run at lambda = 1, closed-loop fuel control with a lambda sensor, short- and long-term fuel trims (as read over OBD-II), an ECU task in an atomic subsystem |
| *Ignition timing and knock control* | intermediate | 30 min | spark advance from a speed/load map (2-D lookup table), knock and the knock limit, a knock controller that retards and recovers, noisy sensors |
| *Wall wetting and learned fuel trims* | intermediate | 30 min | fuel film dynamics (x-tau) and transient compensation, a switching lambda sensor, long-term trims learned per load cell (Adaptive Map) |

### Transmission and driveline

| Tutorial | Level | Time | You will learn |
|---|---|---|---|
| *Gear-shift logic* | intermediate | 60 min | an automatic gearbox's shift schedule, hysteresis, a State Chart in its own ECU task, kickdown and hills, fuel consumption per gear |
| *A truck on a mountain road* | intermediate | 30 min | heavy-duty vehicles: a diesel's narrow torque band, a 12-speed automated gearbox (State Chart), cruise control, an exhaust brake on a descent |

## Vehicle dynamics and energy

How a vehicle moves, uses energy, and stays controllable.

### Longitudinal dynamics and energy

| Tutorial | Level | Time | You will learn |
|---|---|---|---|
| *A car on a drive cycle* | beginner | 40 min | vehicle longitudinal dynamics, a driver model, standard drive cycles (ECE-15, WLTC, FTP-75), where the energy goes, fuel consumption |

### Chassis control

| Tutorial | Level | Time | You will learn |
|---|---|---|---|
| *Tyre slip and traction control* | intermediate | 30 min | tyre slip and Pacejka's magic formula, wheel and vehicle dynamics, a traction control ECU on dry, wet and snowy roads |

## Electrics and electronics

Circuits from the textbook to the car's wiring harness and the ECU's circuit board, simulated like in LTspice.

### Circuit fundamentals

| Tutorial | Level | Time | You will learn |
|---|---|---|---|
| *Rectifier, relay driver, buck converter and active filter* | advanced | 45 min | circuit simulation like LTspice: a rectifier, a relay driver and its freewheeling diode, a buck converter, an active filter; SPICE netlists |

### Vehicle electrical system

| Tutorial | Level | Time | You will learn |
|---|---|---|---|
| *Starter motor and electronic throttle* | intermediate | 45 min | physical modelling (circuits, shafts, springs connected by links instead of signals): cranking an engine on a weak battery, a drive-by-wire throttle servo |

## ECU software, communication and diagnostics

What happens inside and between ECUs: networks, calibration, diagnostics and the C code itself.

### Vehicle networks

| Tutorial | Level | Time | You will learn |
|---|---|---|---|
| *A vehicle network (CAN)* | advanced | 40 min | ECUs on simulated CAN buses: DBC files, arbitration and bus load, a gateway, rest-bus simulation, E2E protection, fault injection and timeouts, the bus trace |

## Tips for every tutorial

- **Running the Python version**: each model is built by a script, e.g. `uv run python examples/truck.py`. It runs the model's tests and prints the key numbers quoted in the tutorial.
- **Getting lost**: **File ▸ Open** the example again to start over; your changes are only saved if you save.
- **Looking inside**: double-click a subsystem to open it, **Ctrl+↑** to go back up. Press **F1** on any block for its help page with the equations.
- **Comparing**: every run is kept in the **Data Inspector** (Ctrl+I). Tick two runs and a signal to overlay them.
- **Scripting**: the **Console** tab runs Python on the open model, e.g. `res["speed"].max()`.
