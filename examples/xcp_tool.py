"""A small XCP calibration tool on the command line (the job INCA or CANape do with a GUI).

    uv run python examples/xcp_tool.py read speed time          # measure once
    uv run python examples/xcp_tool.py watch speed force         # measure every 0.5 s until Ctrl+C
    uv run python examples/xcp_tool.py write set_speed_cal 120   # calibrate

It connects over CAN (default: the udp_multicast bus of ``xcp_calibration.nervus``) with request id 0x7F0 and
response id 0x7F1, and finds the variables in an A2L file (default: ``examples/xcp_calibration.a2l``). For a real
ECU: ``--interface pcan --channel PCAN_USBBUS1 --bitrate 500000 --a2l ecu.a2l``.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

HERE = Path(__file__).parent


def main(argv: list[str] | None = None) -> int:
    import can

    from nervus.xcp import CanTransport, XcpError, XcpMaster

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("read", "watch", "write"))
    ap.add_argument("names", nargs="+", help="variables (read/watch), or NAME VALUE (write)")
    ap.add_argument("--interface", default="udp_multicast")
    ap.add_argument("--channel", default="239.74.163.2")
    ap.add_argument("--bitrate", type=int, default=None)
    ap.add_argument("--a2l", default=str(HERE / "xcp_calibration.a2l"))
    ap.add_argument("--request-id", type=lambda s: int(s, 0), default=0x7F0)
    ap.add_argument("--response-id", type=lambda s: int(s, 0), default=0x7F1)
    ap.add_argument("--interval", type=float, default=0.5)
    args = ap.parse_args(argv)
    kwargs = {"fd": False} if args.interface == "udp_multicast" else {}
    if args.bitrate:
        kwargs["bitrate"] = args.bitrate
    bus = can.Bus(interface=args.interface, channel=args.channel, **kwargs)
    try:
        tool = XcpMaster(CanTransport(bus, args.request_id, args.response_id), a2l=args.a2l, timeout=1.0)
        try:
            tool.connect()
        except XcpError as exc:
            print(f"no ECU answers ({exc}): is the model running?")
            return 1
        if args.command == "write":
            name, value = args.names[0], float(args.names[1])
            tool.write(name, value)
            print(f"{name} = {tool.read(name)}")
        else:
            while True:
                print("  ".join(f"{n} = {float(tool.read(n)):10.3f}" for n in args.names), flush=True)
                if args.command == "read":
                    break
                time.sleep(args.interval)
        tool.disconnect()
    except KeyboardInterrupt:
        pass
    finally:
        bus.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
