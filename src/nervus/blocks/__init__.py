"""The standard block library.

Importing this package registers every block, so they can be created by ``type_id`` from model files.
"""

from nervus.blocks.continuous import Derivative, Integrator, StateSpace, TransferFunction
from nervus.blocks.control import PID, DiscretePID
from nervus.blocks.discrete import (
    DiscreteIntegrator,
    DiscreteTransferFunction,
    UnitDelay,
    ZeroOrderHold,
)
from nervus.blocks.math_ops import Abs, Gain, MathFunction, Product, Saturation, Sum
from nervus.blocks.registry import block_types, categories, create_block, get_block_class, register
from nervus.blocks.routing import Demux, Mux, Switch
from nervus.blocks.sinks import Scope, Terminator, ToWorkspace
from nervus.blocks.sources import Clock, Constant, FromWorkspace, Pulse, Ramp, Sine, Step
from nervus.blocks.user import PythonFunction

__all__ = [
    "PID",
    "Abs",
    "Clock",
    "Constant",
    "Demux",
    "Derivative",
    "DiscreteIntegrator",
    "DiscretePID",
    "DiscreteTransferFunction",
    "FromWorkspace",
    "Gain",
    "Integrator",
    "MathFunction",
    "Mux",
    "Product",
    "Pulse",
    "PythonFunction",
    "Ramp",
    "Saturation",
    "Scope",
    "Sine",
    "StateSpace",
    "Step",
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
