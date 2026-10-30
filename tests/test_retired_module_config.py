"""An old config.json still holding a modules.mobi_throttle section (from
before mobiThrottle became a standalone app) must load fine and be ignored."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from host.config import Config  # noqa: E402


def test_old_config_with_mobi_throttle_loads():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.json"
        p.write_text(json.dumps({
            "modules": {"mobi_throttle": {"device_name": "VKBsim", "axis": 0}},
            "cards": {"mobi_throttle": {"x": 10, "y": 10}},
        }), encoding="utf-8")
        cfg = Config(p)
        assert cfg.module_settings("crosshair") == {}
        assert "ui" in cfg.data
        assert not (Path(__file__).resolve().parent.parent / "modules" / "mobi_throttle").exists()
        cfg.save()
        assert json.loads(p.read_text(encoding="utf-8"))["modules"]["mobi_throttle"]["axis"] == 0


if __name__ == "__main__":
    test_old_config_with_mobi_throttle_loads()
    print("ok")
