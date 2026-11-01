"""v2.15.0: the yellow banner in each state, in the real main window against the
fake shopapi of the tests (the live server has every condition met, so there it
is hidden). Usage: python scripts/banner_states.py <output_dir>"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import render_screens as rs  # noqa: E402
from app.api_client import SystemInfo  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

STATES = {
    "status_code_missing": dict(accounting_write_enabled=True, status_code_configured=False),
    "write_off": dict(accounting_write_enabled=False, reason="write_off"),
    "not_allowed_and_code": dict(accounting_write_enabled=False, reason="not_allowed",
                                 status_code_configured=False),
    "all_met": dict(accounting_write_enabled=True),
}


def main() -> int:
    out = Path(sys.argv[1])
    app = QApplication(sys.argv[:1])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    from app.main import prefer_fusion_style

    prefer_fusion_style(app)
    theme.apply_theme(app)
    opened: list = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, state in STATES.items():
            (Path(tmp) / name).mkdir()
            context, _store, _fake = rs.build_context(Path(tmp) / name, write_enabled=True,
                                                      opened=opened)
            state = dict(state)
            reason = state.pop("reason", None)
            info = SystemInfo(reachable=True, accounting_database="hesab5 t", **state)
            if reason:
                info.extra["write_block_reason"] = reason
            window = MainWindow(context)
            window.resize(1360, 760)
            window.show()
            context.apply_system_info(info)
            window.navigate("dashboard")
            rs.settle(app)
            context.apply_system_info(info)        # the dashboard's own read came back
            rs.settle(app, 5)
            rs.grab(window, out / f"banner_{name}.png")
            window.allow_close = True
            window.close()
        for store in opened:
            store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
