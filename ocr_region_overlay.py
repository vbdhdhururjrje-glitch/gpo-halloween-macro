from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.gui.translations import translate_text


class OCRRegionOverlay(QWidget):
    region_changed = Signal(dict)
    MIN_WIDTH = 80
    MIN_HEIGHT = 48
    HANDLE_SIZE = 20

    def __init__(self, region, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self._editing = False
        self._drag_mode = None
        self._press_global = QPoint()
        self._initial_geometry = QRect()
        self._language = "ENG"
        self.set_region(region)

    def set_language(self, language):
        self._language = "ENG" if language == "ENG" else "RU"
        self.update()

    @property
    def editing(self):
        return self._editing

    def region(self):
        geometry = self.geometry()
        return {
            "x": geometry.x(),
            "y": geometry.y(),
            "width": geometry.width(),
            "height": geometry.height(),
        }

    def set_region(self, region):
        self.setGeometry(
            int(region["x"]),
            int(region["y"]),
            max(self.MIN_WIDTH, int(region["width"])),
            max(self.MIN_HEIGHT, int(region["height"])),
        )
        self.update()

    def set_editing(self, editing):
        self._editing = bool(editing)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not self._editing)
        self.setCursor(Qt.SizeFDiagCursor if self._editing else Qt.ArrowCursor)
        self.update()
        if self._editing:
            self.raise_()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(
            self.rect(),
            QColor(255, 133, 46, 24 if self._editing else 9),
        )
        painter.setPen(QPen(QColor(255, 133, 46, 250), 3))
        painter.drawRect(self.rect().adjusted(2, 2, -3, -3))
        if self._editing:
            handle = QRect(
                self.width() - self.HANDLE_SIZE - 2,
                self.height() - self.HANDLE_SIZE - 2,
                self.HANDLE_SIZE,
                self.HANDLE_SIZE,
            )
            painter.fillRect(handle, QColor(255, 133, 46, 235))
            painter.setPen(QPen(QColor(255, 255, 255, 230), 1))
            painter.drawText(
                self.rect().adjusted(8, 4, -8, -4),
                Qt.AlignTop,
                translate_text("OCR REGION", self._language),
            )

    def mousePressEvent(self, event):
        if not self._editing or event.button() != Qt.LeftButton:
            event.ignore()
            return
        self._press_global = event.globalPosition().toPoint()
        self._initial_geometry = self.geometry()
        corner = self.rect().bottomRight() - event.position().toPoint()
        self._drag_mode = (
            "resize"
            if corner.x() < self.HANDLE_SIZE + 4 and corner.y() < self.HANDLE_SIZE + 4
            else "move"
        )
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._editing or self._drag_mode is None:
            event.ignore()
            return
        delta = event.globalPosition().toPoint() - self._press_global
        if self._drag_mode == "move":
            self.move(self._initial_geometry.topLeft() + delta)
        else:
            self.resize(
                max(self.MIN_WIDTH, self._initial_geometry.width() + delta.x()),
                max(self.MIN_HEIGHT, self._initial_geometry.height() + delta.y()),
            )
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._editing and event.button() == Qt.LeftButton and self._drag_mode:
            self._drag_mode = None
            self.region_changed.emit(self.region())
            event.accept()
            return
        event.ignore()