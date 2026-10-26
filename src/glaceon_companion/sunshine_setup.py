"""Owner-only native credential entry; passwords never pass through chat or API."""
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout

from .config import ConfigStore
from .sunshine_ssh import SunshineSSHBridge, SunshineSSHError


class SunshineSetupDialog(QDialog):
    completed = Signal(object)

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="arfoxia-sunshine-setup")
        self.setWindowTitle("Arfoxia · Sunshine de la BC-250")
        self.resize(440, 280)
        layout = QVBoxLayout(self)
        self.note = QLabel("Introduce la cuenta que ya usas en Sunshine de la BC-250.\n"
            "Se comprobará por SSH y se guardará protegida en este Windows.\n"
            "No se cambia la contraseña de Sunshine ni se envía al móvil o al chat.")
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.note)
        self.username = QLineEdit()
        self.username.setPlaceholderText("Usuario de Sunshine de la BC-250")
        self.username.setAccessibleName("Usuario de Sunshine")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Contraseña de Sunshine")
        self.password.setAccessibleName("Contraseña de Sunshine")
        layout.addWidget(self.username)
        layout.addWidget(self.password)
        self.save = QPushButton("Comprobar y guardar")
        self.save.clicked.connect(self.configure)
        layout.addWidget(self.save)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        layout.addWidget(close)
        self.completed.connect(self.finished_configuration)

    def configure(self):
        username, password = self.username.text(), self.password.text()
        if not username.strip() or not password:
            self.note.setText("Introduce el usuario y la contraseña de Sunshine de la BC-250.")
            return
        self.password.clear()
        self.save.setEnabled(False)
        self.note.setText("Comprobando Sunshine por SSH…")

        def worker():
            try:
                self.bridge.configure(username, password)
                message = "Cuenta verificada y guardada. Ya puedes enviar el PIN desde Arfoxia, eligiendo BC-250."
            except SunshineSSHError as exc:
                message = str(exc)
            except Exception:
                message = "No se pudieron guardar las credenciales de forma segura."
            self.completed.emit(message)
        self.pool.submit(worker)

    def finished_configuration(self, message):
        self.note.setText(str(message))
        self.save.setEnabled(True)

    def closeEvent(self, event):
        self.password.clear()
        self.pool.shutdown(wait=False)
        super().closeEvent(event)


def main():
    store = ConfigStore()
    # Read only the registered identity; do not adopt or stop travel tunnels.
    rows = json.loads((store.data_dir / "travel-devices.json").read_text(encoding="utf-8"))
    travel = SimpleNamespace(devices={row["id"]: {"ssh_alias": row["ssh_alias"]} for row in rows})
    app = QApplication.instance() or QApplication([])
    dialog = SunshineSetupDialog(SunshineSSHBridge(store, travel))
    dialog.show()
    app.exec()


if __name__ == "__main__":
    main()
