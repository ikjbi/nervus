# Block reference

This reference is generated from the block source code (`scripts/gen_block_reference.py`).

## [CAN](can.md)

- **CAN Unpack**: Decodes a CAN frame: the input is the 8 data bytes (a vector of width 8), and there is one output per
- **CAN Pack**: Encodes a CAN frame: one input per signal (physical units), output = the 8 data bytes (``uint8``).

## [Continuous](continuous.md)

- **Integrator**: Integrates its input:
- **Derivative**: Approximate time derivative of the input.
- **Transfer Fcn**: Continuous SISO transfer function
- **State-Space**: Continuous linear state-space system

## [Control](control.md)

- **PID Controller**: Continuous PID controller (parallel form) with a filtered derivative:
- **Discrete PID Controller**: Discrete PID controller (parallel form), as it would run on an ECU every *sample_time* seconds.

## [Diagnostics](diagnostics.md)

- **Diagnostic Monitor**: A diagnostic monitor with a trouble code (DTC), like the diagnostic event manager of an engine ECU.
- **OBD Responder**: Makes the model answer OBD-II requests like a car's engine ECU, while the simulation runs.

## [Discontinuities](discontinuities.md)

- **Dead Zone**: Zero output inside the dead zone [*start*, *end*]; outside, the input shifted by the zone edge.
- **Quantizer**: Rounds the input to a multiple of *interval*, like an ADC or a fixed-resolution sensor.
- **Relay**: Switch with hysteresis: turns **on** when the input rises to *on_point* and **off** when it falls to
- **Rate Limiter**: Limits how fast the signal may change, e.g. torque or throttle ramps for drivability.
- **Saturation**: Limits the input to the range [*lower*, *upper*]:

## [Discrete](discrete.md)

- **Unit Delay**: Delays its input by one sample period:
- **Zero-Order Hold**: Samples its input every *sample_time* seconds and holds the value until the next sample:
- **Discrete-Time Integrator**: Discrete-time integrator (accumulator).
- **Discrete Transfer Fcn**: Discrete SISO transfer function
- **Integer Delay**: Delays its input by *delay* samples: ``y[k] = u[k - N]``. The first N outputs are *initial*.
- **Counter**: Counts samples while the input is non-zero (true).
- **Edge Detect**: Outputs 1 for one sample when the (boolean) input changes, otherwise 0.
- **Debounce**: Debounces a boolean input: the output turns on only after the input has been true for *on_samples*
- **Discrete Filter (PT1)**: First-order low-pass filter, the workhorse for smoothing sensor signals in ECU software.
- **Moving Average**: Average of the last *length* samples (including the current one).

## [Electrical](electrical.md)

- **Electrical Reference**: Ground: the node it is linked to is at 0 V. Every circuit needs one.
- **Resistor**: An ideal resistor (Ohm's law):
- **Capacitor**: An ideal capacitor; its voltage is a state:
- **Inductor**: An ideal inductor; its current is a state:
- **Voltage Source**: An ideal voltage source: $v_p - v_n = V$. With *controlled* on, the voltage is the input signal (e.g. from
- **Current Source**: An ideal current source: the current *I* flows out of its ``p`` port into the circuit (and back in at
- **Voltage Sensor**: Measures the voltage $v_p - v_n$ as a signal (ideal: no current flows into it).
- **Current Sensor**: Measures the current flowing through it from ``p`` to ``n`` as a signal. Put it in series, like an
- **Switch**: A switch controlled by a signal: closed (resistance *R_on*) while the input is ≥ 0.5, open (conductance
- **Diode**: A piecewise-linear diode: conducts from ``p`` (anode) to ``n`` (cathode) when the voltage exceeds the
- **Battery**: A battery: open-circuit voltage from its state of charge, and an internal resistance:
- **H-Bridge (PWM)**: An H-bridge driving a motor with PWM, as an average model: the output voltage is the duty cycle times
- **DC Motor**: A permanent-magnet DC motor: electrical port ``p``/``n``, mechanical port ``shaft``:

## [Logic and Bit Operations](logic-and-bit-operations.md)

- **Relational Operator**: Compares input 0 with input 1: ``y = (u0 OP u1)``, giving 1 when true and 0 when false.
- **Compare To Constant**: Compares the input with a constant: ``y = (u OP constant)``, 1 when true, 0 when false.
- **Logical Operator**: Boolean logic. Inputs are true when non-zero. The output is 1 (true) or 0 (false).

## [Lookup Tables](lookup-tables.md)

- **1-D Lookup Table**: 1-D lookup table (a calibration *curve*): maps the input through a table of points.
- **2-D Lookup Table**: 2-D lookup table (a calibration *map*), e.g. ignition advance over engine speed and load.
- **Prelookup**: Breakpoint search on its own: finds the interval index *k* and the fraction *f* of the input.
- **Interpolation using Prelookup**: Interpolates an n-D *table* (1 to 4 dimensions) at the index and fraction from Prelookup blocks.

## [Math Operations](math-operations.md)

- **Gain**: Multiplies the input by a constant.
- **Sum**: Adds and subtracts its inputs.
- **Product**: Multiplies and divides its inputs elementwise.
- **Abs**: Absolute value, ``|u|``.
- **Math Function**: Applies a mathematical function elementwise: exp, log, sqrt, square, sin, cos, tanh, sign, ...
- **MinMax**: Smallest or largest value.
- **Bias**: Adds a constant: ``y = u + bias``.

## [Ports & Subsystems](ports-subsystems.md)

- **In**: An input port.
- **Out**: An output port. Inside a subsystem it is the subsystem's output number *port*; at the top level it is an
- **Subsystem**: A block that contains its own diagram. Double-click it in the editor to open it.

## [Rotational](rotational.md)

- **Rotational Reference**: A fixed point: the port linked to it does not rotate (ω = 0), e.g. a housing.
- **Inertia**: A rotating mass; its speed is a state:
- **Rotational Spring**: A torsion spring between two flanges; its torque is a state:
- **Rotational Damper**: Viscous friction between two flanges: $\tau = d\,(\omega_a - \omega_b)$. Link ``b`` to a Rotational
- **Torque Source**: A torque on a flange, against the reference: the parameter *tau*, or the input signal when
- **Speed Source**: Drives a flange at a given speed, whatever the torque: the parameter *w* or the input signal.
- **Ideal Gear**: A gear without losses or backlash, ratio *n* = ω_a / ω_b:
- **Speed Sensor**: Measures the angular velocity of a flange (against the reference) as a signal, in rad/s.
- **Angle Sensor**: Measures the angle of a flange (the integral of its speed) as a signal, in rad. *phi0*: the angle at
- **Torque Sensor**: Measures the torque transmitted through it from ``a`` to ``b`` (a stiff shaft between the two).

## [Signal Attributes](signal-attributes.md)

- **Rate Transition**: Passes a signal between two rates (two ECU tasks) in a way that is deterministic on an RTOS.
- **Data Type Conversion**: Converts the input to another data type, e.g. a sensor value to ``int16`` or a controller output to
- **Initial Condition**: Outputs *value* at the start of the simulation, then passes its input through:

## [Signal Routing](signal-routing.md)

- **Mux**: Combines its inputs into one vector signal, in port order.
- **Demux**: Splits a vector signal into *num_outputs* equally sized parts.
- **Switch**: Passes input 0 when the control input (input 1) satisfies *criterion*, otherwise input 2:

## [Sinks](sinks.md)

- **Scope**: Plots its input signals. In scripts, read the data with ``result.inputs("scope_name")``.
- **To Workspace**: Saves its input in the simulation result under *variable*, so ``result[variable]`` returns it.
- **Terminator**: Terminates an unused output, so the diagram has no unconnected-output warnings.
- **Stop Simulation**: Stops the simulation at the first major time step where the input is non-zero (true).
- **Assertion**: Fails the simulation with an error if the input is zero (false) at a major time step.

## [Sources](sources.md)

- **Constant**: Outputs a constant value (scalar or vector).
- **Step**: Steps from *initial* to *final* at *time*.
- **Ramp**: A ramp starting at *start_time*:
- **Sine Wave**: Sine wave:
- **Pulse Generator**: Square pulse train. High (*amplitude*) for *duty* percent of each *period*, otherwise 0.
- **Clock**: Outputs the simulation time *t*.
- **From Workspace**: Plays back recorded data.
- **Ground**: Outputs zero. Use it to connect an input you do not need, instead of leaving it unconnected.

## [State Machines](state-machines.md)

- **State Chart**: A state machine (chart) for operating modes, sequences and fault handling, like Simulink's Stateflow.

## [Thermal](thermal.md)

- **Thermal Mass**: A body that stores heat; its temperature is a state:
- **Thermal Resistance**: Heat conduction or convection between two ports: $Q = (T_a - T_b) / R$, with $R = 1/(h A)$ for convection
- **Heat Source**: Heat flowing into a port: the parameter *Q* or the input signal (e.g. a heater, or the losses of a
- **Temperature Source**: Holds a port at a temperature, whatever the heat flow: the ambient air, a coolant at a fixed
- **Temperature Sensor**: Measures the temperature of a port as a signal, in °C.
- **Heat Flow Sensor**: Measures the heat flowing through it from ``a`` to ``b`` as a signal, in W.

## [User-Defined](user-defined.md)

- **Python Function**: Runs your own Python function, the equivalent of Simulink's MATLAB Function block.
