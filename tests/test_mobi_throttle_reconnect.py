"""mobiThrottle only restarts pygame's joystick subsystem (~0.25s GUI freeze)
when it has a reason to: a user-requested rescan, a plug-in event, or the
60s safety net. A device list made moments ago is reused.

No Qt window, no real joystick:
    python tests/test_mobi_throttle_reconnect.py
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("mobi_throttle_module", ROOT / "modules" / "mobi_throttle" / "module.py")
mt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mt)


class _Clock:
    now = 1000.0

    def monotonic(self):
        return self.now


def _probe(plugged_in=False):
    """A module instance with just the state _try_connect() uses, and a log
    of find_joystick() calls as (guid, reinit)."""
    calls = []
    clock = _Clock()
    mt.time.monotonic = clock.monotonic
    mt.find_joystick = lambda guid, reinit=True: calls.append((guid, reinit)) or None
    mt.joystick_plugged_in = lambda: plugged_in
    m = object.__new__(mt.MobiThrottleModule)
    m.settings = {"device_guid": "abc"}
    m._device = None
    m._joysticks_scanned_at = float("-inf")
    m._rescan_requested = False
    return m, calls, clock


def test_first_connect_ever_rescans() -> int:
    m, calls, _ = _probe()
    m._try_connect()
    assert calls == [("abc", True)], calls
    return 1


def test_fresh_device_list_is_reused() -> int:
    m, calls, clock = _probe()
    m._joysticks_scanned_at = clock.now - 0.5
    m._try_connect()
    assert calls == [("abc", False)], calls
    return 1


def test_no_device_no_event_does_not_rescan() -> int:
    m, calls, clock = _probe()
    m._joysticks_scanned_at = clock.now - 10
    m._try_connect()
    assert calls == [], calls
    return 1


def test_plug_in_event_rescans() -> int:
    m, calls, clock = _probe(plugged_in=True)
    m._joysticks_scanned_at = clock.now - 10
    m._try_connect()
    assert calls == [("abc", True)], calls
    assert m._joysticks_scanned_at == clock.now
    return 2


def test_safety_net_rescan_after_a_minute() -> int:
    m, calls, clock = _probe()
    m._joysticks_scanned_at = clock.now - mt.JOYSTICK_RESCAN_SECONDS
    m._try_connect()
    assert calls == [("abc", True)], calls
    return 1


def test_apply_device_forces_rescan_even_when_fresh() -> int:
    m, calls, clock = _probe()
    m._joysticks_scanned_at = clock.now - 0.5
    m._rescan_requested = True
    m._try_connect()
    assert calls == [("abc", True)], calls
    assert m._rescan_requested is False
    return 2


def test_poll_error_requests_rescan() -> int:
    """Transient axis-read failure must not wait for the 60s safety net."""
    m, calls, clock = _probe()
    m._joysticks_scanned_at = clock.now - 10

    class _Boom:
        def get_axis(self, _i):
            raise RuntimeError("device gone")

    class _Label:
        def setText(self, _t):
            pass

    m._device = _Boom()
    m.status_label = _Label()
    m.settings["axis_index"] = 0
    m.settings["axis_reverse"] = False
    m._poll()
    assert m._device is None
    assert m._rescan_requested is True
    m._try_connect()
    assert calls == [("abc", True)], calls
    return 3


def run() -> int:
    checks = 0
    for t in (
        test_first_connect_ever_rescans,
        test_fresh_device_list_is_reused,
        test_no_device_no_event_does_not_rescan,
        test_plug_in_event_rescans,
        test_safety_net_rescan_after_a_minute,
        test_apply_device_forces_rescan_even_when_fresh,
        test_poll_error_requests_rescan,
    ):
        checks += t()
        print(f"[PASS] {t.__name__}")
    print(f"\n{checks}/{checks} mobiThrottle reconnect checks passed")
    return checks


if __name__ == "__main__":
    run()
