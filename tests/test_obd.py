import numpy as np
import pytest

from nervus.core import Signal
from nervus.obd import PIDS, Elm327, ObdError, _main, parse_response, record, supported_from_bitmask


class FakeCar:
    """Behaves like an ELM327 connected to a car: answers AT commands and mode 01 requests."""

    def __init__(self) -> None:
        self.buffer = b""
        self.t = 0.0

    def write(self, data: bytes) -> int:
        cmd = data.decode().strip().upper()
        if cmd.startswith("AT"):
            reply = "OK"
        elif cmd == "0100":
            reply = "SEARCHING...\r41 00 BE 3F A8 13"  # supports 0C, 0D, 05, 11, ... and 0x20 range
        elif cmd == "0120":
            reply = "41 20 80 00 00 00"
        elif cmd == "010C":
            rpm = 800 + 100 * self.t
            raw = int(rpm * 4)
            reply = f"41 0C {raw >> 8:02X} {raw & 0xFF:02X}"
        elif cmd == "010D":
            reply = "41 0D 32"
        elif cmd == "0105":
            reply = "41 05 7B"  # 123 - 40 = 83 degC
        elif cmd == "0111":
            reply = "NO DATA"
        else:
            reply = "NO DATA"
        self.buffer += (reply + "\r\r>").encode()
        return len(data)

    def read_until(self, expected: bytes) -> bytes:
        k = self.buffer.index(expected) + len(expected)
        out, self.buffer = self.buffer[:k], self.buffer[k:]
        return out


def test_decode_standard_pids() -> None:
    assert PIDS["rpm"].decode(bytes([0x1A, 0xF8])) == 1726.0
    assert PIDS["coolant_temp"].decode(bytes([0x7B])) == 83
    assert PIDS["throttle"].decode(bytes([0xFF])) == pytest.approx(100.0)
    assert PIDS["stft_b1"].decode(bytes([0x80])) == 0.0
    assert PIDS["maf"].decode(bytes([0x01, 0xF4])) == 5.0
    assert PIDS["lambda_cmd"].decode(bytes([0x80, 0x00])) == 1.0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("41 0C 1A F8", b"\x1a\xf8"),
        ("410C1AF8", b"\x1a\xf8"),
        ("010C\rSEARCHING...\r41 0C 1A F8\r", b"\x1a\xf8"),
        ("7E8 04 41 0C 1A F8", b"\x1a\xf8"),
        ("NO DATA", None),
        ("CAN ERROR", None),
    ],
)
def test_parse_response(text: str, expected: bytes | None) -> None:
    assert parse_response(text, 1, 0x0C) == expected


def test_supported_bitmask() -> None:
    found = supported_from_bitmask(0, bytes.fromhex("BE3FA813"))
    assert {0x01, 0x05, 0x0C, 0x0D, 0x20} <= found


def test_elm_session_and_recording(tmp_path) -> None:  # type: ignore[no-untyped-def]
    car = FakeCar()
    elm = Elm327(car)
    supported = elm.initialize()
    assert 0x0C in supported and 0x21 in supported
    clock = iter(np.arange(0, 10, 0.5))

    def fake_clock() -> float:
        car.t = next(clock)
        return car.t

    res = record(elm, ["rpm", "speed", "coolant_temp"], duration=3.0, clock=fake_clock, sleep=lambda s: None)
    assert res["speed"][0] == 50.0 and res["coolant_temp"][0] == 83.0
    assert res["rpm"][-1] > res["rpm"][0]
    path = res.save(tmp_path / "drive")
    replay = Signal(res.t, res["rpm"], "linear")  # recorded data as a test input
    assert replay(res.t[1])[0] == pytest.approx(res["rpm"][1])
    assert path.exists()


def test_unsupported_and_no_answer() -> None:
    elm = Elm327(FakeCar())
    elm.initialize()
    assert elm.read(PIDS["throttle"]) is None  # NO DATA
    with pytest.raises(ObdError, match="does not report"):
        record(elm, ["oil_temp"], 1.0)


def test_cli_lists_pids(capsys) -> None:  # type: ignore[no-untyped-def]
    assert _main(["pids"]) == 0
    assert "rpm" in capsys.readouterr().out
