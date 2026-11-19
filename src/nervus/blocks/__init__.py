"""The standard block library.

Importing this package registers every block, so they can be created by ``type_id`` from model files.
"""

from nervus.blocks.chart import StateChart
from nervus.blocks.continuous import Derivative, Integrator, StateSpace, TransferFunction
from nervus.blocks.control import PID, DiscretePID
from nervus.blocks.discontinuities import DeadZone, Quantizer, RateLimiter, Relay
from nervus.blocks.discrete import (
    Counter,
    Debounce,
    DiscreteFilter,
    DiscreteIntegrator,
    DiscreteTransferFunction,
    EdgeDetect,
    IntegerDelay,
    MovingAverage,
    UnitDelay,
    ZeroOrderHold,
)
from nervus.blocks.logic import CompareToConstant, LogicalOperator, RelationalOperator
from nervus.blocks.lookup import Lookup1D, Lookup2D
from nervus.blocks.math_ops import Abs, Bias, Gain, MathFunction, MinMax, Product, Saturation, Sum
from nervus.blocks.ports import Inport, Outport, Subsystem
from nervus.blocks.registry import block_types, categories, create_block, get_block_class, register
from nervus.blocks.routing import DataTypeConversion, Demux, Mux, Switch
from nervus.blocks.sinks import Assertion, Scope, StopSimulation, Terminator, ToWorkspace
from nervus.blocks.sources import Clock, Constant, FromWorkspace, Ground, Pulse, Ramp, Sine, Step
from nervus.blocks.user import PythonFunction

__all__ = [
    "PID",
    "Abs",
    "Assertion",
    "Bias",
    "Clock",
    "CompareToConstant",
    "Constant",
    "Counter",
    "DataTypeConversion",
    "DeadZone",
    "Debounce",
    "Demux",
    "Derivative",
    "DiscreteFilter",
    "DiscreteIntegrator",
    "DiscretePID",
    "DiscreteTransferFunction",
    "EdgeDetect",
    "FromWorkspace",
    "Gain",
    "Ground",
    "Inport",
    "IntegerDelay",
    "Integrator",
    "LogicalOperator",
    "Lookup1D",
    "Lookup2D",
    "MathFunction",
    "MinMax",
    "MovingAverage",
    "Mux",
    "Outport",
    "Product",
    "Pulse",
    "PythonFunction",
    "Quantizer",
    "Ramp",
    "RateLimiter",
    "RelationalOperator",
    "Relay",
    "Saturation",
    "Scope",
    "Sine",
    "StateChart",
    "StateSpace",
    "Step",
    "StopSimulation",
    "Subsystem",
    "Sum",
    "Switch",
    "Terminator",
    "ToWorkspace",
    "TransferFunction",
    "UnitDelay",
    "ZeroOrderHold",
    "block_types",
    "categories",
    "create_block",
    "get_block_class",
    "register",
]
