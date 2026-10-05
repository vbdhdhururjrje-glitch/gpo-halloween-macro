import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QKeySequenceEdit,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QToolButton,
    QWidget,
)

from app.config.config_manager import ConfigManager, OCR_DEFAULT_REGION, ROUTE_FILE
from app.doors.door import DoorState
from app.doors.door_manager import DoorManager
from app.doors.scheduler import DoorScheduler
from app.gui.ocr_region_overlay import OCRRegionOverlay
from app.gui.translations import translate_text
from app.input.cursor import focus_game_window, get_cursor_position, get_screen_size
from app.input.hotkeys import HotkeyManager
from app.input.player import PlaybackWorker
from app.input.raw_mouse import WM_INPUT, get_raw_input_event, register_raw_input_devices
from app.input.recorder import InputRecorder
from app.input.relative_mouse import send_keyboard_key
from app.route.route_manager import RouteManager
from app.utils.logger import AppLogger
from app.vision.ocr import OCRWorker

DOOR_OCR_MAX_ATTEMPTS = 5
ROUTE_MUTATION_BLOCKED_STATES = frozenset({
    "RUNNING",
    "PAUSED",
    "RECORDING",
})


class HotkeyCaptureEdit(QKeySequenceEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumSequenceLength(1)
        self.setToolTip("Click, then press the key or shortcut to assign it")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GPO / HALLOWEEN — Macro")
        self.resize(600, 500)
        self.setMinimumSize(540, 450)
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #151311;
                color: #f2e9df;
                font-family: "Segoe UI";
                font-size: 10pt;
            }
            QTabWidget::pane {
                background: #1c1917;
                border: 1px solid #39312b;
                top: -1px;
            }
            QTabBar::tab {
                background: #211e1b;
                color: #b9aaa0;
                border: 1px solid #39312b;
                border-bottom: none;
                padding: 8px 12px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #30231b;
                color: #ff9a3d;
                border-top: 2px solid #f07824;
            }
            QGroupBox {
                background: #1c1917;
                border: 1px solid #39312b;
                border-radius: 4px;
                margin-top: 10px;
                padding: 8px 7px 7px 7px;
                color: #ffad64;
                font-weight: 700;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 9px;
                padding: 0 4px;
            }
            QPushButton {
                background: #292522;
                color: #f2e9df;
                border: 1px solid #494039;
                border-radius: 4px;
                padding: 8px 12px;
                min-height: 28px;
            }
            QPushButton:hover {
                border-color: #f07824;
                background: #33271f;
            }
            QPushButton:disabled {
                color: #756b63;
                background: #211e1b;
            }
            QPushButton#primaryButton {
                background: #e87522;
                border-color: #ff9a3d;
                color: #17110c;
                font-weight: 700;
            }
            QPushButton#primaryButton:hover { background: #ff9134; }
            QPushButton#dangerButton {
                color: #ffad86;
                border-color: #75412d;
            }
            QToolButton {
                background: #292522;
                color: #b9aaa0;
                border: 1px solid #494039;
                border-radius: 3px;
                padding: 3px 8px;
                font-weight: 700;
            }
            QToolButton:checked {
                background: #e87522;
                border-color: #ff9a3d;
                color: #17110c;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit,
            QTextEdit, QListWidget {
                background: #100f0e;
                color: #f2e9df;
                border: 1px solid #39312b;
                border-radius: 3px;
                padding: 6px;
                selection-background-color: #9f4f1f;
            }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
            QComboBox:focus, QKeySequenceEdit:focus, QTextEdit:focus,
            QListWidget:focus {
                border-color: #e87522;
            }
            QLabel#brandTitle {
                color: #ff9a3d;
                font-size: 12pt;
                font-weight: 700;
            }
            QLabel#sectionHeading {
                color: #ffad64;
                font-weight: 700;
            }
            QLabel#statusText {
                color: #f2e9df;
                font-size: 11pt;
                font-weight: 700;
            }
            QLabel#headerMeta { color: #a99b90; }
            QLabel#stateBadge {
                color: #ffad64;
                background: #30231b;
                border: 1px solid #69401f;
                border-radius: 3px;
                padding: 4px 8px;
                font-weight: 700;
            }
            QProgressBar {
                border: 1px solid #39312b;
                border-radius: 3px;
                background: #100f0e;
                max-height: 9px;
            }
            QProgressBar::chunk {
                background: #e87522;
                border-radius: 2px;
            }
            QTextEdit#eventLog {
                font-family: "Consolas";
                font-size: 9pt;
            }
            QTextEdit#ocrText {
                background: #0c0b0a;
                color: #fff4e8;
                font-family: "Segoe UI";
                font-size: 12pt;
                font-weight: 600;
                padding: 10px;
            }
            QScrollArea { border: none; }
        """)

        self.config_manager = ConfigManager()
        self.settings = self.config_manager.load()
        self.language = self.settings["language"]
        self.route_manager = RouteManager()
        self.door_manager = DoorManager()
        self.door_scheduler = DoorScheduler(self.door_manager)
        self.recorder = InputRecorder(self)
        self.hotkeys = HotkeyManager(self)
        self.logger = AppLogger(self)
        self.player = None
        self.ocr_worker = None
        self._ocr_worker_mode = None
        self._door_check_id = None
        self._door_scan_active = False
        self._door_approach_worker = None
        self._door_check_attempts = 0
        self._door_e_attempts = 0
        self._door_e_limit_reached = False
        self._door_e_retry_due = False
        self._door_check_scan_completed = False
        self._door_check_retry_pending = False
        self._discard_current_ocr_result = False
        self._door_check_last_text = ""
        self._logged_candy_event_keys = set()
        self._ocr_worker_generation = 0
        self._closing = False
        self._stop_requested = False
        self._paused_wait_state = None
        self._paused_wait_remaining_ms = None
        self.ocr_overlay = None
        self._raw_input_registered = False
        self.state = "STOPPED"
        self._last_progress = (0, 0, "START_POINT")

        self._build_ui()
        self._capture_translation_sources()
        self.door_refresh_timer = QTimer(self)
        self.door_refresh_timer.setInterval(1000)
        self.door_refresh_timer.timeout.connect(self._refresh_doors)
        self.door_refresh_timer.start()
        self.ocr_monitor_timer = QTimer(self)
        self.ocr_monitor_timer.setInterval(1000)
        self.ocr_monitor_timer.timeout.connect(self._poll_ocr_during_playback)
        self.door_retry_timer = QTimer(self)
        self.door_retry_timer.setSingleShot(True)
        self.door_retry_timer.timeout.connect(self._retry_door_interaction)
        self.route_restart_timer = QTimer(self)
        self.route_restart_timer.setSingleShot(True)
        self.route_restart_timer.timeout.connect(self._restart_route_after_delay)
        self._load_settings_into_ui()
        self.ocr_overlay = OCRRegionOverlay(self._ocr_region_from_ui())
        self.ocr_overlay.set_language(self.language)
        self.ocr_overlay.region_changed.connect(self._ocr_overlay_region_changed)
        for field in self.ocr_region_fields.values():
            field.valueChanged.connect(self._ocr_region_fields_changed)
        self._apply_language()
        self._connect_signals()
        self.recorder.set_ignored_hotkeys(self.settings["hotkeys"].values())
        configured_route = self.settings.get("route_path", "").strip()
        route_path = Path(configured_route).expanduser() if configured_route else ROUTE_FILE
        if route_path.exists():
            try:
                self.route_manager.load(route_path)
                self._save_active_route_path(route_path)
                self.state = "READY" if self.route_manager.route.actions else "STOPPED"
            except Exception as exc:
                self.logger.log(f"Saved route could not be loaded from {route_path}: {exc}")
        elif configured_route:
            self.logger.log(f"Saved route path not found: {route_path}")
        self._restore_route_cooldowns()
        self._refresh_route()
        self._set_status()
        self._start_hotkeys()
        self.logger.log("Application ready")

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(11, 9, 11, 9)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        brand = QLabel("GPO / HALLOWEEN")
        brand.setObjectName("brandTitle")
        self.language_ru_button = QToolButton()
        self.language_ru_button.setText("RU")
        self.language_ru_button.setCheckable(True)
        self.language_eng_button = QToolButton()
        self.language_eng_button.setText("ENG")
        self.language_eng_button.setCheckable(True)
        self.language_group = QButtonGroup(self)
        self.language_group.setExclusive(True)
        self.language_group.addButton(self.language_ru_button)
        self.language_group.addButton(self.language_eng_button)
        self.language_ru_button.clicked.connect(lambda: self.set_language("RU"))
        self.language_eng_button.clicked.connect(lambda: self.set_language("ENG"))
        self.header_route_summary = QLabel("0 actions / 0 markers")
        self.header_route_summary.setObjectName("headerMeta")
        self.header_state = QLabel("STOPPED")
        self.header_state.setObjectName("stateBadge")
        header.addWidget(brand)
        header.addWidget(self.language_ru_button)
        header.addWidget(self.language_eng_button)
        header.addStretch(1)
        header.addWidget(self.header_route_summary)
        header.addWidget(self.header_state)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        status_tab = QWidget()
        status_layout = QVBoxLayout(status_tab)
        status_layout.setContentsMargins(11, 10, 11, 10)
        status_layout.setSpacing(9)
        self.state_label = QLabel("Status: STOPPED")
        self.point_label = QLabel("Current point: —")
        self.action_label = QLabel("Current action: —")
        self.progress_label = QLabel("Route progress: 0 / 0")
        self.state_label.setObjectName("statusText")
        self.progress_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_summary = QGridLayout()
        status_summary.setHorizontalSpacing(12)
        status_summary.setVerticalSpacing(7)
        status_summary.addWidget(self.state_label, 0, 0)
        status_summary.addWidget(self.progress_label, 0, 1, alignment=Qt.AlignRight)
        status_summary.addWidget(self.point_label, 1, 0, 1, 2)
        status_summary.addWidget(self.action_label, 2, 0, 1, 2)
        status_layout.addLayout(status_summary)
        self.route_progress_bar = QProgressBar()
        self.route_progress_bar.setTextVisible(False)
        self.route_progress_bar.setRange(0, 1)
        self.route_progress_bar.setValue(0)
        status_layout.addWidget(self.route_progress_bar)
        for label in (self.state_label, self.point_label, self.action_label, self.progress_label):
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setWordWrap(True)
        event_log_heading = QLabel("EVENT LOG")
        event_log_heading.setObjectName("sectionHeading")
        status_layout.addWidget(event_log_heading)
        self.log_view = QTextEdit()
        self.log_view.setObjectName("eventLog")
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QTextEdit.WidgetWidth)
        status_layout.addWidget(self.log_view, 1)
        self.tabs.addTab(status_tab, "Status")

        route_tab = QWidget()
        route_layout = QVBoxLayout(route_tab)
        route_layout.setContentsMargins(11, 10, 11, 10)
        route_layout.setSpacing(8)
        route_heading = QLabel("ROUTE OVERVIEW")
        route_heading.setObjectName("sectionHeading")
        route_layout.addWidget(route_heading)
        self.route_summary = QLabel("Actions: 0 | Markers: 0")
        self.route_summary.setWordWrap(True)
        route_layout.addWidget(self.route_summary)

        recording_row = QHBoxLayout()
        self.record_button = QPushButton("Record route")
        self.record_button.setObjectName("primaryButton")
        self.record_button.clicked.connect(self.start_recording)
        self.finish_recording_button = QPushButton("Finish recording")
        self.finish_recording_button.clicked.connect(self.stop_recording)
        self.finish_recording_button.setEnabled(False)
        recording_row.addWidget(self.record_button)
        recording_row.addWidget(self.finish_recording_button)
        route_layout.addLayout(recording_row)

        marker_row = QHBoxLayout()
        self.marker_type = QComboBox()
        self.marker_type.addItem("DOOR", "DOOR")
        self.mark_button = QPushButton("Mark point")
        self.mark_button.setObjectName("secondaryButton")
        self.mark_button.clicked.connect(self.mark_point)
        marker_row.addWidget(self.marker_type)
        marker_row.addWidget(self.mark_button)
        route_layout.addLayout(marker_row)
        self.route_list = QListWidget()
        route_layout.addWidget(self.route_list, 1)

        route_file_row = QHBoxLayout()
        save_route_button = QPushButton("Save route")
        save_route_button.setObjectName("primaryButton")
        save_route_button.clicked.connect(self.save_route)
        load_route_button = QPushButton("Load route")
        load_route_button.clicked.connect(self.load_route)
        delete_route_button = QPushButton("Delete route")
        delete_route_button.setObjectName("dangerButton")
        delete_route_button.clicked.connect(self.delete_route)
        route_file_row.addWidget(save_route_button)
        route_file_row.addWidget(load_route_button)
        route_file_row.addWidget(delete_route_button)
        route_layout.addLayout(route_file_row)
        self.tabs.addTab(route_tab, "Route")

        doors_tab = QWidget()
        doors_layout = QVBoxLayout(doors_tab)
        doors_layout.setContentsMargins(11, 10, 11, 10)
        doors_layout.setSpacing(8)
        self.door_summary = QLabel("Recorded doors: 0")
        doors_layout.addWidget(self.door_summary)
        self.scheduler_preview_label = QLabel("Next candidate: —")
        doors_layout.addWidget(self.scheduler_preview_label)
        self.door_list = QListWidget()
        doors_layout.addWidget(self.door_list, 1)
        self.tabs.addTab(doors_tab, "Doors")

        ocr_tab = QWidget()
        ocr_layout = QVBoxLayout(ocr_tab)
        ocr_layout.setContentsMargins(11, 10, 11, 10)
        ocr_layout.setSpacing(8)
        ocr_heading = QLabel("CAPTURE REGION")
        ocr_heading.setObjectName("sectionHeading")
        ocr_layout.addWidget(ocr_heading)
        ocr_form = QGridLayout()
        ocr_form.setHorizontalSpacing(12)
        ocr_form.setVerticalSpacing(8)
        self.ocr_region_fields = {}
        for index, (key, caption, minimum, maximum) in enumerate((
            ("x", "Left", -10000, 10000),
            ("y", "Top", -10000, 10000),
            ("width", "Width", 1, 10000),
            ("height", "Height", 1, 10000),
        )):
            row = index // 2
            column = (index % 2) * 2
            field = QSpinBox()
            field.setRange(minimum, maximum)
            field.setMinimumHeight(30)
            self.ocr_region_fields[key] = field
            caption_label = QLabel(f"{caption}:")
            caption_label.setMinimumWidth(48)
            ocr_form.addWidget(caption_label, row, column)
            ocr_form.addWidget(field, row, column + 1)
        ocr_form.setColumnStretch(1, 1)
        ocr_form.setColumnStretch(3, 1)
        ocr_layout.addLayout(ocr_form)
        region_button_row = QHBoxLayout()
        self.ocr_region_button = QPushButton("Adjust region")
        self.ocr_region_button.clicked.connect(self.toggle_ocr_region_edit)
        self.ocr_reset_button = QPushButton("Reset region")
        self.ocr_reset_button.setToolTip(
            "Restore the narrow OCR region for door notifications"
        )
        self.ocr_reset_button.clicked.connect(self.reset_ocr_region)
        region_button_row.addWidget(self.ocr_region_button, 2)
        region_button_row.addWidget(self.ocr_reset_button, 1)
        ocr_layout.addLayout(region_button_row)
        tesseract_row = QHBoxLayout()
        self.tesseract_path_field = QLineEdit()
        self.tesseract_path_field.setPlaceholderText("Use PATH or select tesseract.exe")
        tesseract_row.addWidget(self.tesseract_path_field, 1)
        browse_tesseract_button = QPushButton("Browse…")
        browse_tesseract_button.clicked.connect(self._browse_tesseract)
        tesseract_row.addWidget(browse_tesseract_button)
        ocr_layout.addWidget(QLabel("Tesseract executable"))
        ocr_layout.addLayout(tesseract_row)
        self.ocr_run_button = QPushButton("Capture and recognize")
        self.ocr_run_button.setObjectName("primaryButton")
        self.ocr_run_button.clicked.connect(self.start_ocr)
        ocr_layout.addWidget(self.ocr_run_button)
        self.ocr_status_label = QLabel("Idle")
        self.ocr_cooldown_label = QLabel("Cooldown: —")
        self.ocr_candy_label = QLabel("Candy event: —")
        for label in (
            self.ocr_status_label,
            self.ocr_cooldown_label,
            self.ocr_candy_label,
        ):
            label.setWordWrap(True)
        ocr_layout.addWidget(self.ocr_status_label)
        ocr_layout.addWidget(self.ocr_cooldown_label)
        ocr_layout.addWidget(self.ocr_candy_label)
        self.ocr_result_view = QTextEdit()
        self.ocr_result_view.setObjectName("ocrText")
        self.ocr_result_view.setReadOnly(True)
        self.ocr_result_view.setLineWrapMode(QTextEdit.WidgetWidth)
        self.ocr_result_view.setMinimumHeight(110)
        ocr_layout.addWidget(self.ocr_result_view, 1)
        self.tabs.addTab(ocr_tab, "OCR")

        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        settings_layout.setContentsMargins(11, 10, 11, 10)
        settings_content = QWidget()
        settings_columns = QHBoxLayout(settings_content)
        settings_columns.setContentsMargins(2, 2, 8, 2)
        settings_columns.setSpacing(10)
        playback_group = QGroupBox("PLAYBACK")
        form = QFormLayout(playback_group)
        form.setContentsMargins(8, 12, 8, 8)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        hotkeys_group = QGroupBox("HOTKEYS")
        hotkey_form = QFormLayout(hotkeys_group)
        hotkey_form.setContentsMargins(8, 12, 8, 8)
        hotkey_form.setHorizontalSpacing(8)
        hotkey_form.setVerticalSpacing(8)
        self.slot_spin = QSpinBox()
        self.slot_spin.setRange(1, 9)
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 10.0)
        self.delay_spin.setSingleStep(0.1)
        self.delay_spin.setSuffix(" sec")
        self.playback_speed_spin = QDoubleSpinBox()
        self.playback_speed_spin.setRange(0.5, 2.0)
        self.playback_speed_spin.setSingleStep(0.05)
        self.playback_speed_spin.setDecimals(2)
        self.playback_speed_spin.setSuffix("x")
        self.repeat_delay_spin = QDoubleSpinBox()
        self.repeat_delay_spin.setRange(0.0, 600.0)
        self.repeat_delay_spin.setSingleStep(1.0)
        self.repeat_delay_spin.setSuffix(" sec")
        self.door_retry_interval_spin = QDoubleSpinBox()
        self.door_retry_interval_spin.setRange(5.0, 60.0)
        self.door_retry_interval_spin.setSingleStep(0.5)
        self.door_retry_interval_spin.setSuffix(" sec")
        self.door_e_press_limit_spin = QSpinBox()
        self.door_e_press_limit_spin.setRange(1, DOOR_OCR_MAX_ATTEMPTS)
        self.ocr_scan_interval_spin = QDoubleSpinBox()
        self.ocr_scan_interval_spin.setRange(0.1, 30.0)
        self.ocr_scan_interval_spin.setSingleStep(0.25)
        self.ocr_scan_interval_spin.setDecimals(2)
        self.ocr_scan_interval_spin.setSuffix(" sec")
        self.ocr_frame_interval_spin = QDoubleSpinBox()
        self.ocr_frame_interval_spin.setRange(0.0, 2.0)
        self.ocr_frame_interval_spin.setSingleStep(0.05)
        self.ocr_frame_interval_spin.setDecimals(2)
        self.ocr_frame_interval_spin.setSuffix(" sec")
        self.mouse_gain_spin = QDoubleSpinBox()
        self.mouse_gain_spin.setRange(0.05, 2.0)
        self.mouse_gain_spin.setSingleStep(0.05)
        self.mouse_gain_spin.setDecimals(2)
        self.mouse_gain_spin.setSuffix("x")
        form.addRow("Bag slot:", self.slot_spin)
        form.addRow("Startup delay:", self.delay_spin)
        form.addRow("Playback speed:", self.playback_speed_spin)
        form.addRow("Repeat delay:", self.repeat_delay_spin)
        form.addRow("Door E retry interval:", self.door_retry_interval_spin)
        form.addRow("Door E presses per door:", self.door_e_press_limit_spin)
        form.addRow("OCR scan interval:", self.ocr_scan_interval_spin)
        form.addRow("OCR frame interval:", self.ocr_frame_interval_spin)
        form.addRow("Mouse movement scale:", self.mouse_gain_spin)
        settings_columns.addWidget(playback_group, 1)
        settings_columns.addWidget(hotkeys_group, 1)
        self.hotkey_fields = {}
        for action, caption in (
            ("start", "Start / Resume"),
            ("record", "Record route"),
            ("pause", "Pause"),
            ("stop", "Stop"),
            ("mark", "Mark point"),
            ("emergency", "Emergency stop"),
        ):
            field = HotkeyCaptureEdit()
            self.hotkey_fields[action] = field
            hotkey_form.addRow(f"{caption}:", field)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(settings_content)
        settings_layout.addWidget(settings_scroll, 1)
        save_settings_button = QPushButton("Save settings")
        save_settings_button.setObjectName("primaryButton")
        save_settings_button.clicked.connect(self.save_settings)
        settings_layout.addWidget(save_settings_button)
        reset_settings_button = QPushButton("Restore default settings")
        reset_settings_button.clicked.connect(self.reset_settings)
        settings_layout.addWidget(reset_settings_button)
        self.tabs.addTab(settings_tab, "Settings")

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.start_button = QPushButton("START")
        self.pause_button = QPushButton("PAUSE")
        self.stop_button = QPushButton("STOP")
        self.emergency_button = QPushButton("EMERGENCY STOP")
        self.start_button.setObjectName("primaryButton")
        self.emergency_button.setObjectName("dangerButton")
        self.start_button.clicked.connect(self.start_macro)
        self.pause_button.clicked.connect(self.pause_macro)
        self.stop_button.clicked.connect(self.stop_macro)
        self.emergency_button.clicked.connect(self.emergency_stop)
        for button in (
            self.start_button, self.pause_button, self.stop_button, self.emergency_button
        ):
            button.setMinimumHeight(40)
        controls.addWidget(self.start_button, 1)
        controls.addWidget(self.pause_button, 1)
        controls.addWidget(self.stop_button, 1)
        controls.addWidget(self.emergency_button, 1.45)
        layout.addLayout(controls)

    def _connect_signals(self):
        self.recorder.action_recorded.connect(self._record_action)
        self.recorder.error.connect(self._show_runtime_error)
        self.hotkeys.pressed.connect(self._handle_hotkey)
        self.hotkeys.error.connect(self._show_runtime_error)
        self.logger.message.connect(self._append_log)

    def _capture_translation_sources(self):
        self._translation_sources = []
        for widget in self.findChildren(QWidget):
            if isinstance(widget, QLabel):
                self._translation_sources.append((widget, "text", widget.text()))
            elif isinstance(widget, QAbstractButton):
                self._translation_sources.append((widget, "text", widget.text()))
            elif isinstance(widget, QGroupBox):
                self._translation_sources.append((widget, "title", widget.title()))
            if isinstance(widget, QLineEdit):
                self._translation_sources.append(
                    (widget, "placeholder", widget.placeholderText())
                )
            elif isinstance(widget, QComboBox):
                for index in range(widget.count()):
                    if widget is not self.marker_type:
                        self._translation_sources.append(
                            (widget, f"item:{index}", widget.itemText(index))
                        )
            tooltip = widget.toolTip()
            if tooltip:
                self._translation_sources.append((widget, "tooltip", tooltip))
        self._tab_translation_sources = [
            self.tabs.tabText(index) for index in range(self.tabs.count())
        ]
        self._window_title_source = self.windowTitle()

    def _tr(self, text):
        return translate_text(text, self.language)

    def set_language(self, language):
        language = "ENG" if str(language).upper() == "ENG" else "RU"
        if language == self.language:
            self._apply_language()
            return
        updated_settings = {**self.settings, "language": language}
        try:
            self.config_manager.save(updated_settings)
        except Exception as exc:
            self.logger.log(f"Could not save language preference: {exc}")
            return
        self.settings = updated_settings
        self.language = language
        self._apply_language()
        self.logger.log(f"Language changed to {language}")

    def _apply_language(self):
        for widget, kind, source in self._translation_sources:
            translated = self._tr(source)
            if kind == "text":
                widget.setText(translated)
            elif kind == "title":
                widget.setTitle(translated)
            elif kind == "placeholder":
                widget.setPlaceholderText(translated)
            elif kind == "tooltip":
                widget.setToolTip(translated)
            elif kind.startswith("item:"):
                widget.setItemText(int(kind.split(":", 1)[1]), translated)
        for index, source in enumerate(self._tab_translation_sources):
            self.tabs.setTabText(index, self._tr(source))
        self.setWindowTitle(self._tr(self._window_title_source))
        self.language_ru_button.setChecked(self.language == "RU")
        self.language_eng_button.setChecked(self.language == "ENG")
        for label in (
            self.state_label,
            self.point_label,
            self.action_label,
            self.progress_label,
            self.header_route_summary,
            self.route_summary,
            self.door_summary,
            self.scheduler_preview_label,
            self.ocr_status_label,
            self.ocr_cooldown_label,
            self.ocr_candy_label,
        ):
            label.setText(self._tr(label.text()))
        for index in range(self.marker_type.count()):
            self.marker_type.setItemText(
                index,
                self._tr(self.marker_type.itemData(index, Qt.UserRole) or self.marker_type.itemText(index)),
            )
        for list_widget in (self.route_list, self.door_list):
            for index in range(list_widget.count()):
                item = list_widget.item(index)
                item.setText(self._tr(item.text()))
        self.log_view.setPlainText(
            "\n".join(
                self._translate_log_line(line)
                for line in self.log_view.toPlainText().splitlines()
            )
        )
        if self.ocr_overlay is not None:
            self.ocr_overlay.set_language(self.language)
        self._update_hotkey_labels()

    def _load_settings_into_ui(self):
        self.slot_spin.setValue(self.settings["bag_slot"])
        self.delay_spin.setValue(self.settings["startup_delay"])
        self.playback_speed_spin.setValue(self.settings["playback_speed"])
        self.repeat_delay_spin.setValue(self.settings["repeat_delay"])
        self.door_retry_interval_spin.setValue(self.settings["door_retry_interval"])
        self.door_e_press_limit_spin.setValue(self.settings["door_e_press_limit"])
        self.ocr_scan_interval_spin.setValue(self.settings["ocr_scan_interval"])
        self.ocr_frame_interval_spin.setValue(self.settings["ocr_frame_interval"])
        self.ocr_monitor_timer.setInterval(
            round(self.ocr_scan_interval_spin.value() * 1000)
        )
        self.mouse_gain_spin.setValue(self.settings["mouse_gain"])
        ocr_region = self.settings.get("ocr", {}).get("region", {})
        self.tesseract_path_field.setText(
            self.settings.get("ocr", {}).get("tesseract_cmd", "")
        )
        for key, default in OCR_DEFAULT_REGION.items():
            self.ocr_region_fields[key].setValue(int(ocr_region.get(key, default)))
        for action, field in self.hotkey_fields.items():
            field.setKeySequence(QKeySequence(self.settings["hotkeys"].get(action, "")))
        self._update_hotkey_labels()

    def _update_hotkey_labels(self):
        hotkeys = self.settings["hotkeys"]
        self.mark_button.setText(self._tr(f"Mark point ({hotkeys['mark']})"))
        self.record_button.setText(self._tr(f"Record route ({hotkeys['record']})"))
        self.start_button.setText(self._tr(f"START ({hotkeys['start']})"))
        self.pause_button.setText(self._tr(f"PAUSE ({hotkeys['pause']})"))
        self.stop_button.setText(self._tr(f"STOP ({hotkeys['stop']})"))
        self.emergency_button.setText(
            self._tr(f"EMERGENCY STOP ({hotkeys['emergency']})")
        )

    def _settings_from_ui(self):
        return {
            **self.settings,
            "bag_slot": self.slot_spin.value(),
            "startup_delay": self.delay_spin.value(),
            "playback_speed": self.playback_speed_spin.value(),
            "repeat_delay": self.repeat_delay_spin.value(),
            "door_retry_interval": self.door_retry_interval_spin.value(),
            "door_e_press_limit": self.door_e_press_limit_spin.value(),
            "ocr_scan_interval": self.ocr_scan_interval_spin.value(),
            "ocr_frame_interval": self.ocr_frame_interval_spin.value(),
            "mouse_gain": self.mouse_gain_spin.value(),
            "ocr": {
                **self.settings.get("ocr", {}),
                "tesseract_cmd": self.tesseract_path_field.text().strip(),
                "region": {
                    key: field.value()
                    for key, field in self.ocr_region_fields.items()
                },
            },
            "hotkeys": {
                action: field.keySequence().toString(
                    QKeySequence.SequenceFormat.PortableText
                )
                for action, field in self.hotkey_fields.items()
            },
        }

    def _start_hotkeys(self):
        shortcuts = self.settings["hotkeys"]
        self.hotkeys.start(shortcuts)

    def save_settings(self):
        data = ConfigManager._merge_defaults(self._settings_from_ui())
        shortcuts = [value.lower() for value in data["hotkeys"].values()]
        if any(not shortcut for shortcut in shortcuts):
            QMessageBox.warning(
                self, self._tr("Invalid hotkey"),
                self._tr("Hotkey fields cannot be empty."),
            )
            return
        if len(set(shortcuts)) != len(shortcuts):
            QMessageBox.warning(
                self, self._tr("Invalid hotkey"),
                self._tr("Each action needs a different hotkey."),
            )
            return
        self.hotkeys.stop()
        try:
            self.config_manager.save(data)
            self._activate_settings(data)
            self.logger.log("Settings saved; global hotkeys updated")
        except Exception as exc:
            QMessageBox.critical(self, self._tr("Settings error"), self._tr(str(exc)))
            self._start_hotkeys()

    def reset_settings(self):
        if self.state in ROUTE_MUTATION_BLOCKED_STATES:
            QMessageBox.warning(
                self,
                self._tr("Busy"),
                self._tr("Stop recording or playback before changing settings."),
            )
            return
        answer = QMessageBox.question(
            self,
            self._tr("Restore default settings"),
            self._tr("Restore default settings? The current route will be kept."),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        data = self.config_manager.default_settings()
        data["route_path"] = self.settings.get("route_path", "")
        data["door_cooldowns"] = dict(self.settings.get("door_cooldowns", {}))
        self.hotkeys.stop()
        try:
            self.config_manager.save(data)
            self._activate_settings(data)
            self.logger.log("Default settings restored; current route was kept")
        except Exception as exc:
            QMessageBox.critical(self, self._tr("Settings error"), self._tr(str(exc)))
            self._start_hotkeys()

    def _activate_settings(self, data):
        self.settings = data
        self.language = data["language"]
        self._load_settings_into_ui()
        self.ocr_overlay.set_region(data["ocr"]["region"])
        self.ocr_overlay.set_language(self.language)
        self.ocr_monitor_timer.setInterval(round(data["ocr_scan_interval"] * 1000))
        self.recorder.set_ignored_hotkeys(data["hotkeys"].values())
        self._apply_language()
        self._start_hotkeys()

    def start_ocr(self):
        self._start_ocr_worker()

    def _start_ocr_worker(self, monitoring=False):
        if self.ocr_worker is not None and self.ocr_worker.isRunning():
            return
        region = {
            key: field.value()
            for key, field in self.ocr_region_fields.items()
        }
        worker = OCRWorker(
            region,
            self,
            tesseract_cmd=self.tesseract_path_field.text().strip() or None,
            frame_interval=self.ocr_frame_interval_spin.value(),
        )
        self._ocr_worker_generation += 1
        generation = self._ocr_worker_generation
        self.ocr_worker = worker
        self._ocr_worker_mode = "monitoring" if monitoring else "manual"
        worker.recognized.connect(
            lambda text, cooldown, candy_event, stable,
            current=worker, worker_generation=generation:
                self._ocr_worker_recognized(
                    current,
                    worker_generation,
                    text,
                    cooldown,
                    candy_event,
                    stable,
                )
        )
        worker.failed.connect(self._ocr_failed)
        worker.finished.connect(lambda current=worker: self._ocr_finished(current))
        self.ocr_run_button.setEnabled(False)
        self.ocr_status_label.setText(
            self._tr(
                "Monitoring game text…"
                if monitoring else "Capturing and recognizing…"
            )
        )
        worker.start()

    def _ocr_worker_recognized(
        self,
        worker,
        generation,
        text,
        cooldown,
        candy_event,
        stable,
    ):
        if worker is not self.ocr_worker or generation != self._ocr_worker_generation:
            return
        if self._ocr_worker_mode == "monitoring" and (
            self.state != "RUNNING" or not self._door_scan_active
        ):
            return
        self._ocr_recognized(text, cooldown, candy_event, stable)

    def _poll_ocr_during_playback(self):
        if self.state != "RUNNING" or not self._door_scan_active:
            self.ocr_monitor_timer.stop()
            return
        if self._door_check_id is not None and self._door_check_retry_pending:
            self._start_door_check_ocr()
        elif self._door_check_id is None and (
            self.ocr_worker is None or not self.ocr_worker.isRunning()
        ):
            self._start_ocr_worker(monitoring=True)

    def _door_approached(self, door_id):
        if self.state not in {"RUNNING", "PAUSED"}:
            return
        self._door_scan_active = True
        if self.state == "RUNNING":
            self.ocr_monitor_timer.setInterval(
                round(self.ocr_scan_interval_spin.value() * 1000)
            )
            self.ocr_monitor_timer.start()
            self.action_label.setText(
                self._tr(f"Current action: OCR SCANNING DOOR #{door_id}")
            )
            if self.ocr_worker is None or not self.ocr_worker.isRunning():
                self._start_ocr_worker(monitoring=True)
            self._door_approach_worker = self.ocr_worker
        if self.player is not None and self.player.isRunning():
            self.player.resolve_door_approach()

    def _browse_tesseract(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._tr("Select Tesseract executable"),
            self.tesseract_path_field.text().strip(),
            "Tesseract executable (tesseract.exe);;All files (*)",
        )
        if path:
            self.tesseract_path_field.setText(path)

    def _ocr_region_from_ui(self):
        return {
            key: field.value()
            for key, field in self.ocr_region_fields.items()
        }

    def _ocr_region_fields_changed(self, value):
        if self.ocr_overlay is not None:
            self.ocr_overlay.set_region(self._ocr_region_from_ui())

    def toggle_ocr_region_edit(self):
        editing = not self.ocr_overlay.editing
        self.ocr_overlay.set_editing(editing)
        self.ocr_region_button.setText(
            self._tr("Finish region setup" if editing else "Adjust region")
        )
        if editing:
            self.ocr_overlay.show()
            self.ocr_overlay.raise_()
            self.ocr_status_label.setText(
                self._tr("Drag to move; drag the green corner to resize")
            )
        else:
            self.ocr_status_label.setText(self._tr("OCR region saved"))
            if not self._macro_input_active():
                self.ocr_overlay.hide()

    def reset_ocr_region(self):
        if self.state in ROUTE_MUTATION_BLOCKED_STATES:
            self.logger.log("OCR region reset ignored while macro is active")
            return
        region = dict(OCR_DEFAULT_REGION)
        for key, field in self.ocr_region_fields.items():
            blocker = QSignalBlocker(field)
            field.setValue(region[key])
            del blocker
        self.ocr_overlay.set_region(region)
        self._ocr_overlay_region_changed(region)

    def _macro_input_active(self):
        return self.route_manager.recording or (
            self.player is not None and self.player.isRunning()
        )

    def _show_ocr_overlay(self):
        self.ocr_overlay.set_editing(False)
        self.ocr_region_button.setText(self._tr("Adjust region"))
        self.ocr_overlay.show()
        self.ocr_overlay.raise_()

    def _hide_ocr_overlay(self):
        self.ocr_overlay.set_editing(False)
        self.ocr_region_button.setText(self._tr("Adjust region"))
        self.ocr_overlay.hide()

    def _ocr_overlay_region_changed(self, region):
        for key, field in self.ocr_region_fields.items():
            blocker = QSignalBlocker(field)
            field.setValue(region[key])
            del blocker
        updated_settings = {
            **self.settings,
            "ocr": {
                **self.settings.get("ocr", {}),
                "region": dict(region),
            },
        }
        try:
            self.config_manager.save(updated_settings)
            self.settings = updated_settings
            self.ocr_status_label.setText(self._tr("OCR region saved"))
            self.logger.log("OCR region saved")
        except Exception as exc:
            self.ocr_status_label.setText(
                self._tr(f"Could not save OCR region: {exc}")
            )
            self.logger.log(f"OCR region save failed: {exc}")

    def _ocr_recognized(self, text, cooldown, candy_event, stable):
        if self._discard_current_ocr_result:
            self._discard_current_ocr_result = False
            if self._door_check_id is not None:
                self._door_check_retry_pending = True
            return
        if self._door_check_id is not None:
            self._door_check_scan_completed = True
        self.ocr_result_view.setPlainText(text or self._tr("No text recognized."))
        self.ocr_cooldown_label.setText(
            self._tr(
                f"Cooldown: {cooldown} sec"
                if cooldown >= 0 else "Cooldown: not detected"
            )
        )
        basket_full = (
            candy_event
            if isinstance(candy_event, dict) and candy_event.get("type") == "basket_full"
            else None
        )
        candy_events = [] if basket_full else (
            candy_event if isinstance(candy_event, list)
            else [candy_event] if candy_event is not None
            else []
        )
        if basket_full is not None and stable:
            self.ocr_candy_label.setText(
                self._tr(f"Candy basket full: {basket_full['total']} Candies")
            )
            self.logger.log(
                f"Candy basket full ({basket_full['total']}); stopping macro"
            )
        elif not candy_events:
            self.ocr_candy_label.setText(self._tr("Candy event: not detected"))
        else:
            event_summaries = []
            for event in candy_events:
                event_label = "Received" if event["type"] == "received" else "Stolen"
                event_summaries.append(
                    self._tr(
                        f"{event_label}: {event['amount']} | Total: {event['total']}"
                    )
                )
                event_key = (
                    event["type"],
                    int(event["amount"]),
                    int(event["total"]),
                )
                if event_key not in self._logged_candy_event_keys:
                    self._logged_candy_event_keys.add(event_key)
                    self.logger.log(
                        f"Candies {event_label.lower()}: {event['amount']}; "
                        f"total {event['total']}"
                    )
            if len(self._logged_candy_event_keys) > 512:
                self._logged_candy_event_keys.clear()
            self.ocr_candy_label.setText("; ".join(event_summaries))
        if stable:
            self.ocr_status_label.setText(self._tr("Recognition complete"))
        else:
            self.ocr_status_label.setText(
                self._tr("Unstable OCR: no result confirmed")
            )
            if self._door_check_id is None and self._ocr_worker_mode != "monitoring":
                self.logger.log("OCR result was unstable across captured frames")
        if basket_full is not None and stable:
            self.stop_macro()
            return
        if self._door_check_id is not None:
            self._handle_door_check_result(text, cooldown, candy_events, stable)
            return
        if self._ocr_worker_mode == "monitoring":
            return
        selected_door = self.door_list.currentItem()
        if selected_door is not None:
            door_id = selected_door.data(Qt.UserRole)
            door = self.door_manager.record_ocr_result(
                door_id,
                cooldown=cooldown if cooldown >= 0 else None,
                candy_events=candy_events,
                stable=stable,
            )
            if door is not None:
                self._persist_route_cooldowns()
                self._refresh_doors(door.id)
                self.logger.log(f"Door #{door.id} -> {door.last_result}")

    def _request_door_ocr(self, door_id):
        self._door_scan_active = True
        if (
            self._door_approach_worker is not None
            and self.ocr_worker is self._door_approach_worker
        ):
            self._discard_current_ocr_result = True
        self._door_approach_worker = None
        self.door_retry_timer.stop()
        if self._door_check_id != int(door_id):
            self._door_check_attempts = 0
            self._door_e_attempts = 1
            self._door_e_limit_reached = False
            self._door_check_last_text = ""
        elif self._door_e_attempts == 0:
            self._door_e_attempts = 1
        self._door_e_retry_due = False
        self._door_check_id = int(door_id)
        self._door_check_scan_completed = False
        self._door_check_retry_pending = True
        self.ocr_monitor_timer.setInterval(
            round(self.ocr_scan_interval_spin.value() * 1000)
        )
        self.ocr_monitor_timer.start()
        self.door_retry_timer.start(
            round(self.door_retry_interval_spin.value() * 1000)
        )
        self.action_label.setText(
            self._tr(f"Current action: CHECKING DOOR #{door_id}")
        )
        if self.ocr_worker is not None and self.ocr_worker.isRunning():
            self._discard_current_ocr_result = True
            self.ocr_status_label.setText(
                self._tr(f"Waiting to check DOOR #{door_id} after E…")
            )
            return
        QTimer.singleShot(0, self._start_door_check_ocr)

    def _door_retry_limit(self):
        return self.door_e_press_limit_spin.value()

    def _start_door_check_ocr(self):
        if self._door_check_id is None:
            self._door_check_retry_pending = False
            return
        if self.ocr_worker is not None and self.ocr_worker.isRunning():
            self._door_check_retry_pending = True
            return
        self._door_check_retry_pending = False
        self._door_check_attempts += 1
        self._door_check_scan_completed = False
        self.ocr_status_label.setText(
            self._tr(
                f"Checking DOOR #{self._door_check_id} "
                f"(attempt {self._door_check_attempts})…"
            )
        )
        self._start_ocr_worker(monitoring=True)

    def _handle_door_check_result(self, text, cooldown, candy_events, stable):
        door_id = self._door_check_id
        self._door_check_last_text = text or ""
        candy_confirmed = stable and bool(candy_events)
        if candy_confirmed:
            self.door_retry_timer.stop()
            self._door_e_retry_due = False
            door = self.door_manager.record_ocr_result(
                door_id,
            cooldown=None,
                candy_events=candy_events,
                stable=True,
            )
            if door is not None:
                self._persist_route_cooldowns()
                self._refresh_doors(door.id)
                self.logger.log(
                    f"DOOR #{door.id} confirmed by OCR: {door.last_result}; continuing route"
                )
            self._door_check_id = None
            self._door_check_scan_completed = False
            self._door_check_retry_pending = False
            self._door_e_limit_reached = False
            self._door_scan_active = False
            self.ocr_monitor_timer.stop()
            if cooldown >= 0:
                self.action_label.setText(
                    self._tr(
                        f"Current action: DOOR #{door_id} on cooldown; "
                        "continuing to next route door"
                    )
                )
            else:
                self.action_label.setText(
                    self._tr(
                        f"Current action: DOOR #{door_id} confirmed; continuing route"
                    )
                )
            if self.player is not None and self.player.isRunning():
                self.player.resolve_door_check(True)
            return

        cooldown_detected = stable and cooldown >= 0
        if cooldown_detected:
            self.door_retry_timer.stop()
            self._door_e_retry_due = False
            door = self.door_manager.record_ocr_result(
                door_id,
                cooldown=cooldown,
                stable=True,
            )
            if door is not None:
                self._persist_route_cooldowns()
                self._refresh_doors(door.id)
            self._door_check_id = None
            self._door_check_scan_completed = False
            self._door_check_retry_pending = False
            self._door_e_limit_reached = False
            self._door_scan_active = False
            self.ocr_monitor_timer.stop()
            self.action_label.setText(
                self._tr(
                    f"Current action: DOOR #{door_id} cooldown {cooldown}s; continuing route"
                )
            )
            self.logger.log(
                f"DOOR #{door_id} cooldown {cooldown}s; continuing route"
            )
            if self.player is not None and self.player.isRunning():
                self.player.resolve_door_check(True)
            return

        self._door_check_retry_pending = True
        self._show_ocr_overlay()
        if self._door_e_limit_reached:
            self.ocr_status_label.setText(
                self._tr("E limit reached; continuing OCR until a door message appears")
            )
            self.action_label.setText(
                self._tr(
                    f"Current action: WAITING FOR DOOR #{door_id} OCR "
                    f"({self._door_e_attempts}/{self._door_retry_limit()} E presses)"
                )
            )
            return
        self.ocr_status_label.setText(
            self._tr("No target text yet; continuing OCR scans")
        )
        self.action_label.setText(
            self._tr(
                f"Current action: WATCHING DOOR #{door_id} "
                f"({self._door_e_attempts}/{self._door_retry_limit()} E presses)"
            )
        )

    def _retry_door_interaction(self):
        door_id = self._door_check_id
        if door_id is None or self.player is None or not self.player.isRunning():
            self.door_retry_timer.stop()
            self._door_e_retry_due = False
            return
        if self.state == "PAUSED":
            self.door_retry_timer.stop()
            self._door_e_retry_due = True
            return
        if (
            self.ocr_worker is not None and self.ocr_worker.isRunning()
        ) or not self._door_check_scan_completed:
            self.door_retry_timer.stop()
            self._door_e_retry_due = True
            return
        retry_limit = self._door_retry_limit()
        if self._door_e_attempts >= retry_limit:
            self.door_retry_timer.stop()
            self._door_e_retry_due = False
            self._door_e_limit_reached = True
            self._door_check_retry_pending = True
            self.logger.log(
                f"DOOR #{door_id} reached {retry_limit} E presses "
                "without OCR confirmation; continuing OCR without more E presses"
            )
            self.ocr_status_label.setText(
                self._tr("E retries exhausted; continuing OCR until a door message appears")
            )
            self.action_label.setText(
                self._tr(f"Current action: WAITING FOR DOOR #{door_id} OCR")
            )
            return

        self._door_e_attempts += 1
        self._door_e_retry_due = False
        self._door_check_scan_completed = False
        self._door_check_retry_pending = False
        self.logger.log(
            f"DOOR #{door_id} OCR window elapsed without a valid message; "
            f"retrying E {self._door_e_attempts}/{retry_limit}"
        )
        self.player.resolve_door_check("retry")

    def _clear_door_check(self):
        self.door_retry_timer.stop()
        if self._door_check_id is not None and self.player is not None:
            if self.player.isRunning():
                self.player.stop()
        self._door_check_id = None
        self._door_scan_active = False
        self._door_approach_worker = None
        self._door_e_attempts = 0
        self._door_e_limit_reached = False
        self._door_e_retry_due = False
        self._door_check_scan_completed = False
        self._door_check_retry_pending = False
        self._discard_current_ocr_result = False

    def _route_storage_key(self):
        route_data = self.route_manager.route.to_dict()
        identity = {
            "path": (
                str(self.route_manager.file_path.resolve())
                if self.route_manager.file_path is not None
                else None
            ),
            "route": route_data,
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _restore_route_cooldowns(self):
        saved_states = self.settings.get("door_cooldowns", {})
        states = saved_states.get(self._route_storage_key(), {})
        restored = self.door_manager.restore_cooldowns(
            self.route_manager.route.points,
            states if isinstance(states, dict) else {},
        )
        if restored:
            self.logger.log(f"Restored cooldowns for {restored} door(s)")

    def _persist_route_cooldowns(self):
        saved_states = dict(self.settings.get("door_cooldowns", {}))
        saved_states[self._route_storage_key()] = self.door_manager.export_cooldowns()
        updated_settings = {**self.settings, "door_cooldowns": saved_states}
        try:
            self.config_manager.save(updated_settings)
            self.settings = updated_settings
        except Exception as exc:
            self.logger.log(f"Could not save door cooldowns: {exc}")

    def _save_active_route_path(self, path):
        route_path = str(Path(path).expanduser().resolve()) if path else ""
        updated_settings = {**self.settings, "route_path": route_path}
        try:
            self.config_manager.save(updated_settings)
            self.settings = updated_settings
        except Exception as exc:
            self.logger.log(f"Could not remember route path: {exc}")

    def _ocr_failed(self, message):
        self.ocr_status_label.setText(self._tr(f"OCR error: {message}"))
        self.logger.log(f"OCR error: {message}")
        if self._door_check_id is not None:
            door_id = self._door_check_id
            self.door_retry_timer.stop()
            self._door_e_retry_due = False
            self._door_check_id = None
            self._door_e_attempts = 0
            self._door_e_limit_reached = False
            self._door_check_retry_pending = False
            self._discard_current_ocr_result = False
            self._door_check_last_text = ""
            door = self.door_manager.record_ocr_result(door_id, stable=False)
            if door is not None:
                self._persist_route_cooldowns()
                self._refresh_doors(door.id)
            if self.player is not None and self.player.isRunning():
                self.player.resolve_door_check(False)
            return
        if self.ocr_monitor_timer.isActive():
            self.ocr_monitor_timer.stop()
            self.logger.log("Automatic OCR monitoring stopped after an error")
            self.stop_macro()

    def _playback_failed(self, message):
        self.logger.log(f"Playback error: {message}")

    def _ocr_finished(self, worker):
        if self.ocr_worker is worker:
            self.ocr_worker = None
            self._ocr_worker_mode = None
            self.ocr_run_button.setEnabled(True)
            if self._door_check_retry_pending:
                if self._door_e_retry_due and self._door_check_scan_completed:
                    self._door_check_retry_pending = False
                    QTimer.singleShot(0, self._retry_door_interaction)

    def start_recording(self):
        if self.route_manager.recording:
            self.logger.log("Recording is already active or paused")
            return
        if self.state == "WAITING_TO_RESTART":
            QMessageBox.warning(
                self,
                self._tr("Busy"),
                self._tr("Wait for the current operation to finish first."),
            )
            return
        if self.player is not None and self.player.isRunning():
            QMessageBox.warning(
                self,
                self._tr("Playback active"),
                self._tr("Stop playback before recording."),
            )
            return
        if self.route_manager.route.actions and QMessageBox.question(
            self,
            self._tr("Replace route?"),
            self._tr("Starting a recording replaces the route currently in memory. Continue?"),
        ) != QMessageBox.Yes:
            return
        if not focus_game_window():
            self.logger.log("Recording not started: could not activate Roblox to select the bag slot")
            return
        bag_slot = str(self.settings["bag_slot"])
        if not send_keyboard_key(bag_slot, True):
            self.logger.log(f"Recording not started: could not select bag slot {bag_slot}")
            return
        if not send_keyboard_key(bag_slot, False):
            send_keyboard_key(bag_slot, False)
            self.logger.log(f"Recording not started: could not release bag slot {bag_slot}")
            return
        cursor_position = get_cursor_position()
        self.route_manager.start_recording(
            cursor_position=cursor_position,
            screen_size=get_screen_size(),
        )
        self.door_manager.clear()
        self.recorder.start()
        if not self.recorder.recording:
            self.route_manager.stop_recording()
            return
        self._show_ocr_overlay()
        self.state = "RECORDING"
        self._last_progress = (0, 0, "START_POINT")
        self._set_status()
        self._refresh_route()
        self.finish_recording_button.setEnabled(True)
        self.record_button.setEnabled(False)
        self.logger.log("Recording started; START_POINT created")

    def stop_recording(self):
        if not self.route_manager.recording:
            return
        self.recorder.stop()
        self.route_manager.stop_recording()
        self._hide_ocr_overlay()
        self.state = "READY" if self.route_manager.route.actions else "STOPPED"
        self.finish_recording_button.setEnabled(False)
        self.record_button.setEnabled(True)
        self._refresh_route()
        self._set_status()
        self.logger.log(
            f"Recording stopped: {len(self.route_manager.route.actions)} actions, "
            f"{len(self.route_manager.route.points)} markers"
        )

    def _record_action(self, action):
        self.route_manager.add_action(action)
        self._update_route_summary()

    def mark_point(self):
        if self.state not in {"RECORDING", "PAUSED"} or not self.route_manager.recording:
            self.logger.log("Mark ignored: recording is not active")
            return
        try:
            point = self.route_manager.add_point(
                self.marker_type.currentData(Qt.UserRole)
                or self.marker_type.currentText()
            )
        except RuntimeError:
            self.logger.log("Mark ignored: recording is not active")
            return
        self._refresh_route()
        self.logger.log(f"Marked {point.type} #{point.id}")

    def save_route(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self._tr("Save route"), str(ROUTE_FILE), self._tr("Route JSON (*.json)")
        )
        if not path:
            return
        try:
            self.route_manager.save(path)
            self._save_active_route_path(path)
            self._persist_route_cooldowns()
            self.logger.log(f"Route saved: {path}")
        except Exception as exc:
            QMessageBox.critical(self, self._tr("Route error"), self._tr(str(exc)))

    def load_route(self):
        if self.state in ROUTE_MUTATION_BLOCKED_STATES:
            QMessageBox.warning(
                self,
                self._tr("Busy"),
                self._tr("Stop the current operation before loading a route."),
            )
            return
        path, _ = QFileDialog.getOpenFileName(
            self, self._tr("Load route"), str(ROUTE_FILE), self._tr("Route JSON (*.json)")
        )
        if not path:
            return
        try:
            self.route_manager.load(path)
            self._save_active_route_path(path)
            self.door_manager.clear()
            self._restore_route_cooldowns()
            self._last_progress = (0, len(self.route_manager.route.points), "START_POINT")
            self.state = "READY" if self.route_manager.route.actions else "STOPPED"
            self._refresh_route()
            self._set_status()
            self.logger.log(f"Route loaded: {self.route_manager.route.name}")
        except Exception as exc:
            QMessageBox.critical(self, self._tr("Route error"), self._tr(str(exc)))

    def delete_route(self):
        if self.state in ROUTE_MUTATION_BLOCKED_STATES:
            QMessageBox.warning(
                self,
                self._tr("Busy"),
                self._tr("Stop recording or playback before deleting a route."),
            )
            return
        route = self.route_manager.route
        path = self.route_manager.file_path
        if not route.actions and not route.points and path is None:
            self.logger.log("Delete ignored: there is no route")
            return

        if path is None:
            message = self._tr("Delete the current unsaved route from the application?")
        else:
            message = self._tr(
                "Permanently delete the current route and its file?"
            ) + f"\n\n{path}"
        answer = QMessageBox.question(
            self,
            self._tr("Delete route"),
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            self.route_manager.delete()
        except OSError as exc:
            QMessageBox.critical(self, self._tr("Delete error"), self._tr(str(exc)))
            return
        self._save_active_route_path(None)
        self.door_manager.clear()
        self.state = "STOPPED"
        self._last_progress = (0, 0, "START_POINT")
        self.record_button.setEnabled(True)
        self.finish_recording_button.setEnabled(False)
        self._refresh_route()
        self._set_status()
        self.logger.log("Route deleted from memory and disk")

    def start_macro(self):
        if self._closing:
            return
        if self._paused_wait_state is not None:
            self._paused_wait_state = None
            self.state = "WAITING_TO_RESTART"
            self._set_status()
            self.route_restart_timer.start(
                max(0, self._paused_wait_remaining_ms or 0)
            )
            self._paused_wait_remaining_ms = None
            self.logger.log("Wait resumed")
            return
        if self.state == "WAITING_TO_RESTART":
            self.route_restart_timer.stop()
            self.logger.log("Route restart wait cancelled; starting route manually")
        if self.route_manager.recording:
            if self.state == "PAUSED":
                self.recorder.resume()
                self.route_manager.resume_recording()
                self.state = "RECORDING"
                self._set_status()
                self.logger.log("Recording resumed")
            return
        if self.state == "RECORDING":
            return
        if self.player is not None and self.player.isRunning():
            if self.state == "PAUSED":
                self.player.resume()
                self.state = "RUNNING"
                if self._door_scan_active:
                    self.ocr_monitor_timer.start()
                if self._door_check_id is not None and not self._door_e_limit_reached:
                    self.door_retry_timer.start(
                        round(self.door_retry_interval_spin.value() * 1000)
                    )
                self._set_status()
                self.logger.log("Playback resumed")
            return
        route = self.route_manager.route
        if not route.actions:
            QMessageBox.warning(
                self,
                self._tr("No route"),
                self._tr("Record or load a route with input actions first."),
            )
            return
        self._stop_requested = False
        door_check_release_indices = self.door_scheduler.door_interaction_release_indices(route)
        door_interaction_start_indices = self.door_scheduler.door_interaction_start_indices(route)
        self.player = PlaybackWorker(
            route,
            self.settings["bag_slot"],
            self.settings["startup_delay"],
            self,
            playback_speed=self.playback_speed_spin.value(),
            mouse_gain=self.settings["mouse_gain"],
            door_check_release_indices=door_check_release_indices,
            door_interaction_start_indices=door_interaction_start_indices,
        )
        self.player.progress.connect(self._playback_progress)
        self.player.door_approached.connect(self._door_approached)
        self.player.action_changed.connect(
            lambda action: self.action_label.setText(
                self._tr(f"Current action: {action}")
            )
        )
        self.player.door_check_requested.connect(self._request_door_ocr)
        self.player.failed.connect(self._playback_failed)
        self.player.ended.connect(
            lambda completed, worker=self.player:
                self._playback_ended(completed, worker)
        )
        self._last_progress = (0, len(route.points), "START_POINT")
        self._show_ocr_overlay()
        self.state = "RUNNING"
        self._set_status()
        self.player.start()
        self.logger.log(f"Playback started; selecting bag slot {self.settings['bag_slot']}")

    def pause_macro(self):
        if self.state == "WAITING_TO_RESTART":
            self._paused_wait_state = "WAITING_TO_RESTART"
            self._paused_wait_remaining_ms = max(
                0, self.route_restart_timer.remainingTime()
            )
            self.route_restart_timer.stop()
            self.state = "PAUSED"
            self._set_status()
            self.logger.log("Route restart wait paused")
            return
        if self.route_manager.recording and self.state == "RECORDING":
            self.recorder.pause()
            self.route_manager.pause_recording()
            self.state = "PAUSED"
            self._set_status()
            self.logger.log("Recording paused")
            return
        if self.player is not None and self.player.isRunning() and self.state == "RUNNING":
            self.player.pause()
            self.ocr_monitor_timer.stop()
            self.door_retry_timer.stop()
            self.state = "PAUSED"
            self._set_status()
            self.logger.log("Playback paused")

    def _stop_workers(self):
        self.recorder.stop()
        self.route_manager.stop_recording()
        if (
            self.ocr_worker is not None
            and self._ocr_worker_mode == "monitoring"
            and self.ocr_worker.isRunning()
        ):
            self._ocr_worker_generation += 1
            self.ocr_worker.requestInterruption()
        if self.player is not None and self.player.isRunning():
            self.player.stop()
            self.player.wait(1500)

    def stop_macro(self):
        if self.route_manager.recording:
            self.stop_recording()
            return
        if self._stop_requested or self.state == "STOPPING":
            return
        self._stop_requested = True
        self._paused_wait_state = None
        self._paused_wait_remaining_ms = None
        self.state = "STOPPING"
        self.ocr_monitor_timer.stop()
        self.route_restart_timer.stop()
        self._clear_door_check()
        was_recording = self.route_manager.recording
        self._stop_workers()
        self._hide_ocr_overlay()
        self.state = "READY" if self.route_manager.route.actions else "STOPPED"
        self.record_button.setEnabled(True)
        self.finish_recording_button.setEnabled(False)
        self._set_status()
        if was_recording or self.player is not None:
            self.logger.log("Stopped; all held input released")

    def emergency_stop(self):
        self._stop_requested = True
        self._paused_wait_state = None
        self._paused_wait_remaining_ms = None
        self.state = "EMERGENCY_STOP"
        self.ocr_monitor_timer.stop()
        self.route_restart_timer.stop()
        self._clear_door_check()
        self._stop_workers()
        self._hide_ocr_overlay()
        if self.player is not None:
            self.player.release_all()
        self.record_button.setEnabled(True)
        self.finish_recording_button.setEnabled(False)
        self.action_label.setText(self._tr("Current action: —"))
        self.point_label.setText(self._tr("Current point: —"))
        self._set_status()
        self.logger.log("EMERGENCY STOP; playback cancelled and inputs released")

    def _handle_hotkey(self, action):
        if action == "start":
            self.start_macro()
        elif action == "pause":
            self.pause_macro()
        elif action == "stop":
            if self.route_manager.recording:
                self.stop_recording()
            else:
                self.stop_macro()
        elif action == "mark":
            self.mark_point()
        elif action == "record":
            self.start_recording()
        elif action == "emergency":
            self.emergency_stop()

    def _playback_progress(self, current, total, point_name):
        self._last_progress = (current, total, point_name)
        if point_name.startswith("DOOR #"):
            try:
                door_id = int(point_name.removeprefix("DOOR #"))
            except ValueError:
                door_id = None
            if door_id is not None:
                for index in range(self.door_list.count()):
                    item = self.door_list.item(index)
                    if item.data(Qt.UserRole) == door_id:
                        self.door_list.setCurrentItem(item)
                        break
        self._set_status()

    def _playback_ended(self, completed, worker=None):
        if self._closing or self._stop_requested:
            return
        if worker is not None and worker is not self.player:
            return
        self.ocr_monitor_timer.stop()
        if self.state == "STOPPING":
            return
        if self.state == "EMERGENCY_STOP":
            self._show_ocr_overlay()
            return
        if completed:
            self._schedule_route_restart()
            return
        self._show_ocr_overlay()
        self.state = "READY" if self.route_manager.route.actions else "STOPPED"
        self.action_label.setText(self._tr("Current action: —"))
        self._set_status()

    def _schedule_route_restart(self):
        self.route_restart_timer.stop()
        self._show_ocr_overlay()
        self.state = "WAITING_TO_RESTART"
        self._set_status()
        delay = self.repeat_delay_spin.value()
        self.action_label.setText(self._tr(f"Route complete; restarting in {delay:g}s"))
        self.logger.log(f"Route complete; restarting in {delay:g}s")
        self.ocr_monitor_timer.stop()
        if delay <= 0:
            self._restart_route_after_delay()
        else:
            self.route_restart_timer.start(round(delay * 1000))

    def _restart_route_after_delay(self):
        if self._closing or self.state != "WAITING_TO_RESTART":
            return
        self.state = "READY"
        self._set_status()
        self.start_macro()

    def _set_status(self):
        state_text = self.state.replace("_", " ")
        self.header_state.setText(self._tr(state_text))
        self.state_label.setText(self._tr(f"Status: {state_text}"))
        current, total, point_name = self._last_progress
        self.point_label.setText(
            self._tr(
                f"Current point: {point_name if self.state != 'STOPPED' else '—'}"
            )
        )
        self.progress_label.setText(self._tr(f"Route progress: {current} / {total}"))
        progress_max = max(1, total)
        self.route_progress_bar.setRange(0, progress_max)
        self.route_progress_bar.setValue(min(max(0, current), progress_max))
        if self.state not in {"RUNNING", "PAUSED"}:
            self.action_label.setText(self._tr("Current action: —"))

    def _refresh_route(self):
        self.route_list.clear()
        route = self.route_manager.route
        self.door_manager.sync_from_points(route.points)
        self._refresh_doors()
        self.route_list.addItem(self._tr("START_POINT"))
        for point in route.points:
            self.route_list.addItem(
                self._tr(
                    f"{point.timestamp:7.2f}s  {point.type} #{point.id}  "
                    f"(action {point.action_index})"
                )
            )
        self._update_route_summary()
        self.progress_label.setText(
            self._tr(f"Route progress: 0 / {len(route.points)}")
        )
        self.route_progress_bar.setRange(0, max(1, len(route.points)))
        self.route_progress_bar.setValue(0)

    def _refresh_doors(self, selected_door_id=None):
        if not hasattr(self, "door_list"):
            return
        if selected_door_id is None:
            selected_item = self.door_list.currentItem()
            if selected_item is not None:
                selected_door_id = selected_item.data(Qt.UserRole)
        doors = self.door_manager.doors
        self.door_list.clear()
        self.door_summary.setText(self._tr(f"Recorded doors: {len(doors)}"))
        candidate = self.door_scheduler.choose_next()
        if candidate is not None:
            self.scheduler_preview_label.setText(
                self._tr(f"Next candidate: DOOR #{candidate.id}")
            )
        else:
            wait = self.door_scheduler.seconds_until_next_available()
            next_text = f"in {wait:.1f}s" if wait is not None else "none available"
            self.scheduler_preview_label.setText(
                self._tr(f"Next candidate: {next_text}")
            )
        for door in doors:
            if door.state == DoorState.COOLDOWN:
                state_text = f"COOLDOWN {self.door_manager.cooldown_remaining(door.id):.1f}s"
            else:
                state_text = door.state.value
            item = QListWidgetItem(
                self._tr(
                    f"DOOR #{door.id}  |  Route order {door.route_order}  |  {state_text}"
                )
            )
            item.setData(Qt.UserRole, door.id)
            self.door_list.addItem(item)
            if door.id == selected_door_id:
                self.door_list.setCurrentItem(item)

    def _update_route_summary(self):
        actions = self.route_manager.route.actions
        mouse_moves = [action for action in actions if action.get("type") == "MOUSE_MOVE"]
        total_dx = sum(int(action.get("dx", 0)) for action in mouse_moves)
        total_dy = sum(int(action.get("dy", 0)) for action in mouse_moves)
        left_clicks = sum(
            action.get("type") == "MOUSE_BUTTON_DOWN" and action.get("button") == "left"
            for action in actions
        )
        right_clicks = sum(
            action.get("type") == "MOUSE_BUTTON_DOWN" and action.get("button") == "right"
            for action in actions
        )
        self.route_summary.setText(
            self._tr(
                f"Actions: {len(actions)} | Mouse moves: {len(mouse_moves)} "
                f"(dx {total_dx}, dy {total_dy}) | "
                f"LMB: {left_clicks} | RMB: {right_clicks} | "
                f"Markers: {len(self.route_manager.route.points)}"
            )
        )
        self.header_route_summary.setText(
            self._tr(
                f"{len(actions)} actions / {len(self.route_manager.route.points)} markers"
            )
        )

    def _append_log(self, message):
        self.log_view.append(self._translate_log_line(message))
        document = self.log_view.document()
        if document.blockCount() > 300:
            cursor = self.log_view.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    def _translate_log_line(self, message):
        if "; text=" in message:
            prefix, raw_text = message.rsplit("; text=", 1)
            return f"{self._tr(prefix)}; text={raw_text}"
        return self._tr(message)

    def _show_runtime_error(self, message):
        self.logger.log(f"Error: {message}")

    def closeEvent(self, event):
        route = self.route_manager.route
        has_unsaved_route = (
            self.route_manager.file_path is None
            and bool(route.actions or route.points)
        )
        if has_unsaved_route:
            if self.route_manager.recording:
                self.stop_recording()
            answer = QMessageBox.question(
                self,
                self._tr("Unsaved route"),
                self._tr("Save this route before closing?"),
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if answer == QMessageBox.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.Save:
                route_path, _ = QFileDialog.getSaveFileName(
                    self,
                    self._tr("Save route"),
                    str(ROUTE_FILE),
                    self._tr("Route JSON (*.json)"),
                )
                if not route_path:
                    event.ignore()
                    return
                try:
                    self.route_manager.save(route_path)
                    self._save_active_route_path(route_path)
                    self._persist_route_cooldowns()
                except Exception as exc:
                    QMessageBox.critical(
                        self, self._tr("Route error"), self._tr(str(exc))
                    )
                    event.ignore()
                    return
        self._closing = True
        self.state = "CLOSING"
        self.door_refresh_timer.stop()
        self.ocr_monitor_timer.stop()
        self.route_restart_timer.stop()
        self._clear_door_check()
        self.hotkeys.stop()
        self._stop_workers()
        if self.ocr_worker is not None:
            self.ocr_worker.wait(1000)
        if self.ocr_overlay is not None:
            self.ocr_overlay.close()
        if self.player is not None:
            self.player.release_all()
        event.accept()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_dark_title_bar()
        if self._raw_input_registered:
            return
        try:
            self._raw_input_registered = register_raw_input_devices(int(self.winId()))
        except Exception as exc:
            self.logger.log(f"Raw input unavailable: {exc}")
            return
        self.recorder.set_raw_mouse_enabled(self._raw_input_registered)
        self.recorder.set_raw_keyboard_enabled(self._raw_input_registered)
        self.logger.log(
            "Raw mouse and keyboard input enabled" if self._raw_input_registered
            else "Using standard mouse and keyboard hooks"
        )

    def _apply_dark_title_bar(self):
        try:
            set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
            set_attribute.argtypes = [
                wintypes.HWND,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            set_attribute.restype = ctypes.c_long
            enabled = ctypes.c_int(1)
            value_pointer = ctypes.cast(ctypes.byref(enabled), ctypes.c_void_p)
            for attribute in (20, 19):
                result = set_attribute(
                    wintypes.HWND(int(self.winId())),
                    attribute,
                    value_pointer,
                    ctypes.sizeof(enabled),
                )
                if result == 0:
                    return
        except (AttributeError, OSError):
            return

    def nativeEvent(self, event_type, message):
        try:
            native_message = wintypes.MSG.from_address(int(message))
            if native_message.message == WM_INPUT:
                raw_event = get_raw_input_event(native_message.lParam)
                if raw_event is not None:
                    device_type, event_data = raw_event
                    if device_type == "mouse" and event_data is not None:
                        self.recorder.add_raw_mouse_delta(*event_data)
                    elif device_type == "keyboard" and event_data is not None:
                        self.recorder.add_raw_keyboard_event(*event_data)
        except (TypeError, ValueError, OSError):
            pass
        return False, 0