import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget
from glaceon_companion import ui


@pytest.fixture
def dialog(tmp_path):
    app = QApplication.instance() or QApplication([])
    selected = []
    travel = SimpleNamespace(snapshot=lambda: {"active":"home", "pending":None, "error":"",
        "devices":[{"id":"linux", "label":"BC-250 · Bazzite", "online":False}]},
        select=lambda key: selected.append(key), home=lambda: None)
    service = SimpleNamespace(travel=travel, store=SimpleNamespace(data_dir=tmp_path))
    parent = QWidget()
    parent.chat_window = QWidget(parent)
    window = ui.TravelDialog(service, parent)
    yield window, selected, app
    window.timer.stop()
    window.close()
    parent.close()


def test_ps4_is_visible_without_falsely_registering_arrival(dialog):
    window, selected, app = dialog
    assert window.devices.count() == 2
    ps4 = window.devices.item(1)
    assert ps4.text() == "PS4 · GoldHEN · menú experimental"
    window.devices.setCurrentItem(ps4)
    assert window.travel_button.text() == "Abrir control experimental de PS4"
    window.go()
    assert selected == [] and "Este PC" in window.status.text()
    assert window.ps4_dialog is not None
    assert window.ps4_dialog.process is None  # Opening details never spawns/network-loads.
    assert not window.ps4_dialog.host.text()
    assert window.ps4_dialog.revision.currentData() == 11


def test_selection_survives_refresh_and_linux_keeps_existing_travel_action(dialog):
    window, selected, app = dialog
    window.devices.setCurrentRow(1)
    window.refresh()
    assert window.devices.currentItem().data(Qt.ItemDataRole.UserRole) == window.PS4_CONTROL_ID
    window.devices.setCurrentRow(0)
    assert window.travel_button.text() == "Enviar al dispositivo seleccionado"
    window.go()
    assert selected == ["linux"]


def test_explicit_launch_uses_saved_host_and_does_not_duplicate_panel(dialog, monkeypatch):
    window, selected, app = dialog
    window.devices.setCurrentRow(1)
    window.go()
    panel = window.ps4_dialog
    calls = []
    process = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(ui, "launch_ps4_controls", lambda *args: calls.append(args) or process)
    panel.host.setText("192.168.50.10")
    panel.open_controls()
    panel.open_controls()
    assert len(calls) == 1 and calls[0][1:] == ("192.168.50.10", 11)
    assert "ya está abierto" in panel.feedback.text()
    assert selected == []
