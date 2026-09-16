from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .api import ApiServerThread, create_api
from .config import PROJECT_ROOT, ConfigStore
from .icons import snowflake_icon
from .mobile_runtime import MobileRuntimeManager
from .privileges import is_administrator, launch_as_administrator
from .services import CompanionService
from .ui import DesktopController


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Arfoxia Companion")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--api-host")
    parser.add_argument("--api-port", type=int)
    parser.add_argument("--no-api", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = ConfigStore(args.data_dir)
    config = store.load()
    if config.run_as_administrator is True and not is_administrator():
        if launch_as_administrator(PROJECT_ROOT, sys.argv[1:]):
            return 0
        # UAC cancellation does not silently start a supposedly elevated app.
        return 3
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Iago.GlaceonCompanion.0.1"
        )
    except (AttributeError, OSError):
        pass

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Arfoxia Companion")
    app.setWindowIcon(snowflake_icon())
    app.setQuitOnLastWindowClosed(False)
    if args.api_host:
        config.api_host = args.api_host
    if args.api_port:
        config.api_port = args.api_port

    lock = QLockFile(str(store.data_dir / "glaceon.lock"))
    lock.setStaleLockTime(10_000)
    if not lock.tryLock(100):
        QMessageBox.information(None, "Arfoxia Companion", "Arfoxia ya está ejecutándose.")
        return 0

    sprite_xml = (
        PROJECT_ROOT
        / "assets"
        / "external"
        / "pmd"
        / config.sprite_variant
        / "AnimData.xml"
    )
    if not sprite_xml.exists():
        QMessageBox.critical(
            None,
            "Faltan los sprites",
            "Ejecuta primero: python scripts/fetch_assets.py",
        )
        return 2

    service = CompanionService(store, config)
    service.ollama.recover_normal_profile_sync()
    token = store.api_token()
    server: ApiServerThread | None = None
    if not args.no_api:
        api = create_api(service, token, PROJECT_ROOT / "src" / "glaceon_companion" / "static")
        server = ApiServerThread(api, config.api_host, config.api_port)
        server.start()

    controller = DesktopController(service, token)
    controller.show()

    mobile_runtime = MobileRuntimeManager(
        PROJECT_ROOT / "mobile",
        store.data_dir,
        enabled=config.mobile_dev_server_enabled and not args.no_api,
        port=config.mobile_dev_server_port,
        preferred_host=config.mobile_dev_server_host,
    )
    mobile_timer = QTimer(app)
    mobile_timer.setInterval(10_000)
    mobile_timer.timeout.connect(mobile_runtime.ensure_started)
    mobile_timer.start()
    mobile_runtime.ensure_started()

    def shutdown() -> None:
        mobile_timer.stop()
        mobile_runtime.stop()
        if server:
            server.stop()
            server.join(timeout=5.0)
        service.close()
        lock.unlock()

    app.aboutToQuit.connect(shutdown)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
