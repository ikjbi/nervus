# Block reference

This reference is generated from the block source code (`scripts/gen_block_reference.py`).

## [Continuous](continuous.md)

- **Integrator**: Integrates its input:
- **Derivative**: Approximate time derivative of the input.
- **Transfer Fcn**: Continuous SISO transfer function
- **State-Space**: Continuous linear state-space system

## [Control](control.md)

- **PID Controller**: Continuous PID controller (parallel form) with a filtered derivative:
- **Discrete PID Controller**: Discrete PID controller (parallel form), as it would run on an ECU every *sample_time* seconds.

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

## [Logic and Bit Operations](logic-and-bit-operations.md)

- **Relational Operator**: Compares input 0 with input 1: ``y = (u0 OP u1)``, giving 1 when true and 0 when false.
- **Compare To Constant**: Compares the input with a constant: ``y = (u OP constant)``, 1 when true, 0 when false.
- **Logical Operator**: Boolean logic. Inputs are true when non-zero. The output is 1 (true) or 0 (false).

## [Lookup Tables](lookup-tables.md)

- **1-D Lookup Table**: 1-D lookup table (a calibration *curve*): maps the input through a table of points.
- **2-D Lookup Table**: 2-D lookup table (a calibration *map*), e.g. ignition advance over engine speed and load.

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

## [User-Defined](user-defined.md)

- **Python Function**: Runs your own Python function, the equivalent of Simulink's MATLAB Function block.
