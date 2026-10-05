from datetime import datetime

from PySide6.QtCore import QObject, Signal


class AppLogger(QObject):
    message = Signal(str)

    def log(self, text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.message.emit(f"[{timestamp}] {text}")