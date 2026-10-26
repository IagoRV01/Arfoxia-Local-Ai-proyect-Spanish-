import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QLineEdit
from PySide6.QtCore import Qt
from glaceon_companion.sunshine_setup import SunshineSetupDialog


def test_native_setup_masks_password_and_does_not_read_saved_secrets():
    app=QApplication.instance() or QApplication([])
    dialog=SunshineSetupDialog(SimpleNamespace(configure=lambda *a:None))
    try:
        assert dialog.password.echoMode()==QLineEdit.EchoMode.Password
        assert dialog.password.text()=='' and dialog.username.text()==''
        assert dialog.note.textFormat()==Qt.TextFormat.PlainText
    finally: dialog.close()


def test_native_setup_clears_field_and_only_saves_after_explicit_click():
    app=QApplication.instance() or QApplication([])
    calls=[]
    dialog=SunshineSetupDialog(SimpleNamespace(configure=lambda u,p:calls.append((u,p))))
    try:
        dialog.username.setText('sunshine-owner')
        dialog.password.setText('private-password')
        assert calls==[]
        dialog.save.click()
        assert dialog.password.text()==''
        deadline=time.monotonic()+3
        while not dialog.save.isEnabled() and time.monotonic()<deadline:
            app.processEvents(); time.sleep(.01)
        assert calls==[('sunshine-owner','private-password')]
        assert 'verificada' in dialog.note.text()
        assert 'private-password' not in dialog.note.text()
    finally: dialog.close()
