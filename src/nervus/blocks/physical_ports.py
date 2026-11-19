"""Connection Port: a physical port on the boundary of a subsystem."""

from __future__ import annotations

from nervus.blocks.registry import register
from nervus.core.params import Param, ParamKind
from nervus.physical.network import DOMAINS, PhysicalBlock


@register
class ConnectionPort(PhysicalBlock):
    """A physical port of the subsystem it is in: what is linked to it inside is linked to whatever is linked
    to the subsystem's port of the same name outside. Use it to put a motor, a battery or a heat path into a
    subsystem. The ports appear on the subsystem in the order of *port*; *domain* must match the links."""

    type_id = "ports.connection_port"
    label = "Connection Port"
    category = "Ports & Subsystems"
    PARAMS = (
        Param("port", 1, ParamKind.INT, "Position among the subsystem's physical ports", min=1),
        Param("domain", "electrical", ParamKind.CHOICE, "Physical domain", choices=tuple(DOMAINS)),
    )

    def physical_ports(self) -> list[tuple[str, str]]:
        return [("a", str(self.params["domain"]))]
