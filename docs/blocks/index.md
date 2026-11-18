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

- **Saturation**: Limits the input to the range [*lower*, *upper*]:

## [Discrete](discrete.md)

- **Unit Delay**: Delays its input by one sample period:
- **Zero-Order Hold**: Samples its input every *sample_time* seconds and holds the value until the next sample:
- **Discrete-Time Integrator**: Discrete-time integrator (accumulator).
- **Discrete Transfer Fcn**: Discrete SISO transfer function

## [Math Operations](math-operations.md)

- **Gain**: Multiplies the input by a constant.
- **Sum**: Adds and subtracts its inputs.
- **Product**: Multiplies and divides its inputs elementwise.
- **Abs**: Absolute value, ``|u|``.
- **Math Function**: Applies a mathematical function elementwise: exp, log, sqrt, square, sin, cos, tanh, sign, ...

## [Signal Routing](signal-routing.md)

- **Mux**: Combines its inputs into one vector signal, in port order.
- **Demux**: Splits a vector signal into *num_outputs* equally sized parts.
- **Switch**: Passes input 0 when the control input (input 1) satisfies *criterion*, otherwise input 2:

## [Sinks](sinks.md)

- **Scope**: Plots its input signals. In scripts, read the data with ``result.inputs("scope_name")``.
- **To Workspace**: Saves its input in the simulation result under *variable*, so ``result[variable]`` returns it.
- **Terminator**: Terminates an unused output, so the diagram has no unconnected-output warnings.

## [Sources](sources.md)

- **Constant**: Outputs a constant value (scalar or vector).
- **Step**: Steps from *initial* to *final* at *time*.
- **Ramp**: A ramp starting at *start_time*:
- **Sine Wave**: Sine wave:
- **Pulse Generator**: Square pulse train. High (*amplitude*) for *duty* percent of each *period*, otherwise 0.
- **Clock**: Outputs the simulation time *t*.
- **From Workspace**: Plays back recorded data.

## [User-Defined](user-defined.md)

- **Python Function**: Runs your own Python function, the equivalent of Simulink's MATLAB Function block.
