#!/usr/bin/env python
from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from glaceon_companion.config import ConfigStore
from glaceon_companion.services import CompanionService
from glaceon_companion.ui import DesktopController


def main() -> int:
    with TemporaryDirectory(prefix="glaceon-smoke-") as temp:
        app = QApplication([])
        store = ConfigStore(Path(temp))
        config = store.load()
        service = CompanionService(store, config)
        controller = DesktopController(service, store.api_token())
        controller.show()
        controller.pet.play("Eat", direction=6)
        controller.pet.show_speech("¡Gla! Soy Arfoxia.")
        assert controller.pet.speech_bubble.isVisible()
        controller.pet.show_quick_chat()
        assert controller.pet.quick_chat.isVisible()
        service.interact("pet")
        QTimer.singleShot(950, app.quit)
        result = app.exec()
        service.close()
        return result


if __name__ == "__main__":
    raise SystemExit(main())
