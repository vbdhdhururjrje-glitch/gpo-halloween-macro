import json
import time
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCloseEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from app.config.config_manager import OCR_DEFAULT_REGION
from app.gui.main_window import DOOR_OCR_MAX_ATTEMPTS, MainWindow
from app.gui.ocr_region_overlay import OCRRegionOverlay
from app.gui.translations import RU_TRANSLATIONS
from app.route.route import Route
from app.route.route_point import RoutePoint


class FakePlaybackWorker(QObject):
    progress = Signal(int, int, str)
    action_changed = Signal(str)
    door_approached = Signal(int)
    failed = Signal(str)
    ended = Signal(bool)
    door_check_requested = Signal(int)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.running = False

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def stop(self):
        self.running = False

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def wait(self, timeout):
        return True

    def release_all(self):
        pass

    def resolve_door_check(self, continue_route):
        self.door_check_result = continue_route

    def resolve_door_approach(self):
        self.door_approach_ready = True


class OCRRegionOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.overlay = OCRRegionOverlay({"x": 100, "y": 100, "width": 300, "height": 160})
        self.overlay.set_editing(True)
        self.overlay.show()
        self.app.processEvents()

    def tearDown(self):
        self.overlay.close()
        self.app.processEvents()

    def test_drag_moves_region_and_emits_updated_coordinates(self):
        changed = []
        self.overlay.region_changed.connect(changed.append)
        start = QPoint(80, 70)
        finish = QPoint(110, 90)

        QTest.mousePress(self.overlay, Qt.LeftButton, pos=start)
        QTest.mouseMove(self.overlay, finish, 10)
        QTest.mouseRelease(self.overlay, Qt.LeftButton, pos=finish)

        self.assertEqual(self.overlay.region(), {"x": 130, "y": 120, "width": 300, "height": 160})
        self.assertEqual(changed[-1], self.overlay.region())

    def test_dragging_corner_resizes_region(self):
        corner = QPoint(self.overlay.width() - 4, self.overlay.height() - 4)
        finish = corner + QPoint(40, 25)

        QTest.mousePress(self.overlay, Qt.LeftButton, pos=corner)
        QTest.mouseMove(self.overlay, finish, 10)
        QTest.mouseRelease(self.overlay, Qt.LeftButton, pos=finish)

        self.assertEqual(self.overlay.width(), 340)
        self.assertEqual(self.overlay.height(), 185)

    def test_overlay_is_hidden_and_click_through_by_default(self):
        overlay = OCRRegionOverlay({"x": 0, "y": 0, "width": 300, "height": 160})
        try:
            self.assertTrue(overlay.isHidden())
            self.assertTrue(overlay.testAttribute(Qt.WA_TransparentForMouseEvents))
        finally:
            overlay.close()


class MainWindowOCRLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch("app.gui.main_window.HotkeyManager.start"):
            self.window = MainWindow()
        self.window.language = "ENG"
        self.window._apply_language()
        self.window.route_manager.route = Route()
        self.window.route_manager.file_path = None
        self.window.door_manager.clear()
        self.window.settings["door_cooldowns"] = {}
        self.window._refresh_route()
        self.window.state = "STOPPED"
        self.window._set_status()

    def tearDown(self):
        if self.window.route_manager.recording:
            self.window.recorder.stop()
            self.window.route_manager.stop_recording()
        self.window.hotkeys.stop()
        with patch(
            "app.gui.main_window.QMessageBox.question",
            return_value=QMessageBox.Discard,
        ):
            self.window.close()

    def test_recording_selects_configured_slot_before_capture_and_shows_overlay(self):
        events = []

        def send_key(key, pressed):
            events.append(("key", key, pressed, self.window.recorder.recording))
            return True

        def start_recorder():
            events.append(("recorder", self.window.recorder.recording))
            self.window.recorder._started_at = time.monotonic()

        with patch("app.gui.main_window.focus_game_window", return_value=True), patch(
            "app.gui.main_window.send_keyboard_key", side_effect=send_key
        ), patch(
            "app.gui.main_window.get_cursor_position", return_value={"x": 50, "y": 60}
        ), patch(
            "app.gui.main_window.get_screen_size", return_value={"width": 1920, "height": 1080}
        ), patch.object(self.window.recorder, "start", side_effect=start_recorder):
            self.window.start_recording()

        configured_slot = str(self.window.settings["bag_slot"])
        self.assertEqual(
            events,
            [
                ("key", configured_slot, True, False),
                ("key", configured_slot, False, False),
                ("recorder", False),
            ],
        )
        self.assertFalse(self.window.ocr_overlay.isHidden())

        self.window.stop_recording()
        self.assertTrue(self.window.ocr_overlay.isHidden())

    def test_stop_hotkey_finishes_recording_without_clearing_route(self):
        self.window.route_manager.start_recording()
        self.window.route_manager.add_action(
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.0}
        )
        self.window.state = "RECORDING"
        route = self.window.route_manager.route

        with patch.object(self.window.recorder, "stop"):
            self.window._handle_hotkey("stop")

        self.assertFalse(self.window.route_manager.recording)
        self.assertIs(self.window.route_manager.route, route)
        self.assertEqual(len(route.actions), 1)
        self.assertEqual(self.window.state, "READY")

    def test_configured_mark_hotkey_places_marker_while_recording(self):
        self.window.settings["hotkeys"]["mark"] = "F2"
        self.window.hotkey_fields["mark"].setKeySequence(QKeySequence("F2"))
        self.window._update_hotkey_labels()
        self.window.route_manager.start_recording()
        self.window.state = "RECORDING"
        self.window.marker_type.setCurrentIndex(
            self.window.marker_type.findData("DOOR", Qt.UserRole)
        )

        self.window._handle_hotkey("mark")

        self.assertEqual(self.window.mark_button.text(), "Mark point (F2)")

    def test_mark_hotkey_places_marker_while_recording_is_paused(self):
        self.window.route_manager.start_recording()
        self.window.route_manager.add_action({"type": "KEY_DOWN", "key": "w"})
        self.window.route_manager.pause_recording()
        self.window.state = "PAUSED"
        self.window.marker_type.setCurrentIndex(
            self.window.marker_type.findData("DOOR", Qt.UserRole)
        )

        self.window._handle_hotkey("mark")

        point = self.window.route_manager.route.points[0]
        self.assertEqual((point.type, point.action_index), ("DOOR", 1))
        self.assertEqual(self.window.state, "PAUSED")
        self.assertEqual(
            [(point.type, point.id) for point in self.window.route_manager.route.points],
            [("DOOR", 1)],
        )

    def test_ocr_overlay_stays_top_level_when_main_window_is_minimized(self):
        self.assertIsNone(self.window.ocr_overlay.parent())

    def test_playback_shows_overlay_until_stopped(self):
        self.window.route_manager.route.actions.append(
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.0}
        )

        with patch("app.gui.main_window.PlaybackWorker", FakePlaybackWorker):
            self.window.start_macro()
            self.assertFalse(self.window.ocr_overlay.isHidden())
            self.window.stop_macro()

        self.assertTrue(self.window.ocr_overlay.isHidden())

    def test_one_stop_hotkey_stops_playback_and_ignores_late_end_signal(self):
        self.window.route_manager.route.actions.append(
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.0}
        )

        with patch("app.gui.main_window.PlaybackWorker", FakePlaybackWorker):
            self.window.start_macro()
            self.window._handle_hotkey("stop")
            self.assertEqual(self.window.state, "READY")
            self.assertFalse(self.window.ocr_monitor_timer.isActive())
            self.assertTrue(self.window.ocr_overlay.isHidden())

            self.window._playback_ended(False)

        self.assertEqual(self.window.state, "READY")
        self.assertTrue(self.window.ocr_overlay.isHidden())

    def test_manual_ocr_result_updates_selected_door(self):
        self.window.route_manager.route.points.append(
            RoutePoint(id=1, type="DOOR", timestamp=12.0, action_index=20)
        )
        self.window._refresh_route()
        self.window.door_list.setCurrentRow(0)

        self.window._ocr_recognized(
            "You can Trick or Treat again in 27 seconds", 27, None, True
        )

        door = self.window.door_manager.get(1)
        self.assertEqual(door.state.value, "COOLDOWN")
        self.assertAlmostEqual(self.window.door_manager.cooldown_remaining(1), 27, places=1)
        self.assertEqual(self.window.scheduler_preview_label.text(), "Next candidate: in 27.0s")

    def test_periodic_ocr_does_not_assign_stale_message_to_selected_door(self):
        self.window.route_manager.route.points.append(
            RoutePoint(id=1, type="DOOR", timestamp=12.0, action_index=20)
        )
        self.window._refresh_route()
        self.window.door_list.setCurrentRow(0)
        self.window._ocr_worker_mode = "monitoring"

        self.window._ocr_recognized(
            "You already visited this house! Come back in 1195",
            1195,
            None,
            True,
        )

        self.assertEqual(self.window.door_manager.get(1).state.value, "AVAILABLE")

    def test_post_e_candy_message_resolves_gate_and_continues_route(self):
        self.window.route_manager.route.points.append(
            RoutePoint(id=1, type="DOOR", timestamp=12.0, action_index=20)
        )
        self.window._refresh_route()
        player = FakePlaybackWorker()
        player.start()
        self.window.player = player
        self.window.state = "RUNNING"
        self.window._door_check_id = 1
        self.window._door_check_attempts = 1
        self.window._door_scan_active = True
        self.window.ocr_monitor_timer.start()

        with patch.object(self.window.config_manager, "save"):
            self.window._ocr_recognized(
                "You got +3 Candies! You now have: 404 Candies!",
                -1,
                {"type": "received", "amount": 3, "total": 404},
                True,
            )

        self.assertTrue(player.door_check_result)
        self.assertEqual(self.window.door_manager.get(1).last_candy_amount, 3)
        self.assertIsNone(self.window._door_check_id)
        self.assertFalse(self.window.ocr_monitor_timer.isActive())
        self.assertIn("continuing route", self.window.action_label.text())

    def test_post_e_cooldown_records_door_and_continues_route(self):
        self.window.route_manager.route.points.extend(
            [
                RoutePoint(id=1, type="DOOR", timestamp=12.0, action_index=20),
                RoutePoint(id=2, type="DOOR", timestamp=24.0, action_index=40),
            ]
        )
        self.window._refresh_route()
        player = FakePlaybackWorker()
        player.start()
        self.window.player = player
        self.window.state = "RUNNING"
        self.window._door_check_id = 1
        self.window._door_check_attempts = 1
        self.window._door_scan_active = True
        self.window.ocr_monitor_timer.start()

        with patch.object(self.window.config_manager, "save"):
            self.window._ocr_recognized(
                "You already visited this house! Come back in 27",
                27,
                None,
                True,
            )

        self.assertTrue(player.door_check_result)
        self.assertEqual(self.window.door_manager.get(1).state.value, "COOLDOWN")
        self.assertEqual(self.window.door_list.currentItem().data(Qt.UserRole), 1)
        self.assertFalse(self.window.ocr_monitor_timer.isActive())
        self.assertIn("continuing route", self.window.action_label.text())

    def test_candy_message_after_cooldown_releases_gate_and_continues(self):
        self.window.route_manager.route.points.append(
            RoutePoint(id=1, type="DOOR", timestamp=12.0, action_index=20)
        )
        self.window._refresh_route()
        player = FakePlaybackWorker()
        player.start()
        self.window.player = player
        self.window.state = "RUNNING"
        self.window._door_check_id = 1
        self.window._door_check_attempts = 2

        with patch.object(self.window.config_manager, "save"):
            self.window._ocr_recognized(
                "You got +3 Candies! You now have: 404 Candies!",
                -1,
                {"type": "received", "amount": 3, "total": 404},
                True,
            )

        self.assertTrue(player.door_check_result)
        self.assertEqual(self.window.door_manager.get(1).state.value, "SUCCESS")

    def test_unstable_door_ocr_retries_without_releasing_playback_gate(self):
        self.window.route_manager.route.points.append(
            RoutePoint(id=1, type="DOOR", timestamp=12.0, action_index=20)
        )
        self.window._refresh_route()
        player = FakePlaybackWorker()
        player.start()
        self.window.player = player
        self.window.state = "RUNNING"
        self.window._door_check_id = 1
        self.window._door_check_attempts = 1
        self.window._door_e_attempts = 1

        with patch("app.gui.main_window.QTimer.singleShot"):
            self.window._request_door_ocr(1)
        self.window._ocr_recognized("ay.\n—— |\n—", -1, None, False)

        self.assertTrue(self.window._door_check_retry_pending)
        self.assertEqual(self.window._door_check_id, 1)
        self.assertFalse(hasattr(player, "door_check_result"))
        self.assertIn("continuing OCR scans", self.window.ocr_status_label.text())
        self.assertTrue(self.window.door_retry_timer.isActive())
        self.assertFalse(self.window.ocr_overlay.isHidden())

        self.window._door_check_attempts = 2
        self.window._ocr_recognized(
            "1 Candies were stolen! You now have: 392 Candies!",
            -1,
            {"type": "stolen", "amount": 1, "total": 392},
            True,
        )

        self.assertTrue(player.door_check_result)
        self.assertIsNone(self.window._door_check_id)
        self.assertFalse(self.window.door_retry_timer.isActive())

    def test_automatic_door_scans_do_not_spam_unstable_ocr_logs(self):
        self.window.state = "RUNNING"
        self.window._door_scan_active = True
        self.window._ocr_worker_mode = "monitoring"

        for _ in range(5):
            self.window._ocr_recognized("SAFERZONE\nPROTECTED", -1, None, False)

        self.assertNotIn("OCR result was unstable", self.window.log_view.toPlainText())

    def test_unconfirmed_door_scans_do_not_log_every_ocr_attempt(self):
        self.window.state = "RUNNING"
        self.window._door_check_id = 1
        self.window._door_e_attempts = 3
        self.window._door_e_limit_reached = True

        for _ in range(5):
            self.window._ocr_recognized("SAFERZONE\nPROTECTED", -1, None, False)

        log = self.window.log_view.toPlainText()
        self.assertNotIn("OCR attempt", log)
        self.assertNotIn("OCR did not confirm a result", log)
        self.assertIn("E limit reached", self.window.ocr_status_label.text())

    def test_door_check_uses_configured_e_retry_window(self):
        self.window.door_retry_interval_spin.setValue(5.5)
        self.window.ocr_scan_interval_spin.setValue(3.0)
        self.window.state = "RUNNING"
        with patch("app.gui.main_window.QTimer.singleShot"):
            self.window._request_door_ocr(1)

        self.assertEqual(self.window._door_e_attempts, 1)
        self.assertTrue(self.window.door_retry_timer.isActive())
        self.assertTrue(self.window.ocr_monitor_timer.isActive())
        self.assertEqual(self.window.ocr_monitor_timer.interval(), 3000)

        self.window._ocr_recognized("", -1, None, False)

        self.assertTrue(self.window.door_retry_timer.isActive())
        self.assertEqual(self.window.door_retry_timer.interval(), 5500)

    def test_door_ocr_keeps_waiting_without_more_e_after_configured_limit(self):
        self.window.route_manager.route.points.append(
            RoutePoint(id=1, type="DOOR", timestamp=12.0, action_index=20)
        )
        self.window._refresh_route()
        player = FakePlaybackWorker()
        player.start()
        self.window.player = player
        self.window.state = "RUNNING"
        self.window._door_check_id = 1
        self.window.door_e_press_limit_spin.setValue(2)
        self.window._door_e_attempts = 2

        self.window._ocr_recognized("Still unrelated", -1, None, False)
        self.assertTrue(self.window._door_check_retry_pending)
        self.assertFalse(hasattr(player, "door_check_result"))

        self.window._door_check_retry_pending = False
        self.window._door_check_scan_completed = True
        self.window.ocr_monitor_timer.start()
        self.window._retry_door_interaction()

        self.assertEqual(self.window._door_e_attempts, 2)
        self.assertEqual(self.window._door_check_id, 1)
        self.assertEqual(self.window.state, "RUNNING")
        self.assertTrue(self.window.ocr_monitor_timer.isActive())
        self.assertFalse(self.window.door_retry_timer.isActive())
        self.assertTrue(self.window._door_e_limit_reached)
        self.assertFalse(hasattr(player, "door_check_result"))

    def test_door_retry_waits_for_failed_ocr_before_sending_e(self):
        player = FakePlaybackWorker()
        player.start()
        self.window.player = player
        self.window.state = "RUNNING"
        self.window._door_check_id = 1
        self.window._door_e_attempts = 1

        worker = FakePlaybackWorker()
        worker.start()
        self.window.ocr_worker = worker
        self.window._retry_door_interaction()

        self.assertFalse(hasattr(player, "door_check_result"))
        self.assertTrue(self.window._door_e_retry_due)

        worker.stop()
        self.window._door_check_scan_completed = True
        self.window._door_check_retry_pending = True
        self.window._retry_door_interaction()

        self.assertEqual(player.door_check_result, "retry")
        self.assertEqual(self.window._door_e_attempts, 2)
        self.assertFalse(worker.isRunning())

    def test_pause_suspends_door_retry_timer_until_playback_resumes(self):
        player = FakePlaybackWorker()
        player.start()
        self.window.player = player
        self.window.state = "RUNNING"
        self.window._door_check_id = 1
        self.window._door_e_attempts = 1
        self.window.door_retry_timer.start(5000)

        self.window.pause_macro()

        self.assertEqual(self.window.state, "PAUSED")
        self.assertFalse(self.window.door_retry_timer.isActive())

        self.window.start_macro()

        self.assertEqual(self.window.state, "RUNNING")
        self.assertTrue(self.window.door_retry_timer.isActive())

    def test_door_ocr_waits_for_scan_interval_after_worker_finishes(self):
        worker = FakePlaybackWorker()
        self.window.ocr_worker = worker
        self.window._door_check_id = 1
        self.window._door_check_retry_pending = True
        self.window.ocr_monitor_timer.start()

        with patch("app.gui.main_window.QTimer.singleShot") as single_shot:
            self.window._ocr_finished(worker)

        single_shot.assert_not_called()
        self.assertTrue(self.window._door_check_retry_pending)

    def test_due_e_waits_for_fresh_scan_after_stale_worker(self):
        player = FakePlaybackWorker()
        player.start()
        self.window.player = player
        self.window._door_check_id = 1
        self.window._door_e_attempts = 1
        self.window._door_e_retry_due = True
        self.window._door_check_retry_pending = True
        self.window._door_check_scan_completed = False
        worker = FakePlaybackWorker()
        self.window.ocr_worker = worker

        with patch("app.gui.main_window.QTimer.singleShot") as single_shot:
            self.window._ocr_finished(worker)

        self.assertFalse(hasattr(player, "door_check_result"))
        single_shot.assert_not_called()
        self.assertTrue(self.window._door_check_retry_pending)

    def test_due_e_is_sent_after_fresh_scan_finishes(self):
        player = FakePlaybackWorker()
        player.start()
        self.window.player = player
        self.window._door_check_id = 1
        self.window._door_e_attempts = 1
        self.window._door_e_retry_due = True
        self.window._door_check_retry_pending = True
        self.window._door_check_scan_completed = True
        worker = FakePlaybackWorker()
        self.window.ocr_worker = worker

        with patch("app.gui.main_window.QTimer.singleShot") as single_shot:
            self.window._ocr_finished(worker)

        single_shot.assert_called_once_with(0, self.window._retry_door_interaction)
        self.assertFalse(self.window._door_check_retry_pending)

    def test_door_check_discards_ocr_frame_started_before_e(self):
        stale_worker = FakePlaybackWorker()
        stale_worker.start()
        self.window.ocr_worker = stale_worker

        self.window._request_door_ocr(4)

        self.assertEqual(self.window._door_check_id, 4)
        self.assertTrue(self.window._discard_current_ocr_result)
        self.assertEqual(self.window._door_check_attempts, 0)

    def test_stale_pre_e_result_cannot_confirm_door(self):
        stale_worker = FakePlaybackWorker()
        stale_worker.start()
        player = FakePlaybackWorker()
        player.start()
        self.window.ocr_worker = stale_worker
        self.window.player = player
        self.window.state = "RUNNING"

        self.window._request_door_ocr(4)
        self.window._ocr_recognized(
            "You already visited this house! Come back in 60s",
            60,
            None,
            True,
        )

        self.assertEqual(self.window._door_check_id, 4)
        self.assertFalse(self.window._door_check_scan_completed)
        self.assertTrue(self.window._door_check_retry_pending)
        self.assertFalse(hasattr(player, "door_check_result"))

    def test_door_check_starts_ocr_without_an_extra_settle_delay(self):
        with patch("app.gui.main_window.QTimer.singleShot") as single_shot:
            self.window._request_door_ocr(4)

        single_shot.assert_called_once_with(0, self.window._start_door_check_ocr)

    def test_playback_progress_selects_current_door_for_ocr(self):
        self.window.route_manager.route.points.extend(
            [
                RoutePoint(id=1, type="DOOR", timestamp=12.0, action_index=20),
                RoutePoint(id=2, type="DOOR", timestamp=24.0, action_index=40),
            ]
        )
        self.window._refresh_route()

        self.window._playback_progress(2, 2, "DOOR #2")

        self.assertEqual(self.window.door_list.currentItem().data(Qt.UserRole), 2)

    def test_door_cooldown_is_saved_and_restored_for_matching_route(self):
        route = self.window.route_manager.route
        route.points.append(
            RoutePoint(id=1, type="DOOR", timestamp=12.0, action_index=20)
        )
        self.window._refresh_route()
        route_key = self.window._route_storage_key()
        self.window.door_manager.record_ocr_result(1, cooldown=30)

        with patch.object(self.window.config_manager, "save") as save_settings:
            self.window._persist_route_cooldowns()

        saved = save_settings.call_args.args[0]["door_cooldowns"][route_key]
        self.assertGreater(saved["1"], time.time())
        self.window.door_manager.clear()
        self.window.settings["door_cooldowns"] = {route_key: saved}
        self.window._restore_route_cooldowns()

        self.assertEqual(self.window.door_manager.get(1).state.value, "COOLDOWN")

    def test_manual_ocr_displays_two_candy_events(self):
        self.window.route_manager.route.points.append(
            RoutePoint(id=1, type="DOOR", timestamp=12.0, action_index=20)
        )
        self.window._refresh_route()
        self.window.door_list.setCurrentRow(0)
        text = (
            "You got +5 Candies! You now have: 457 Candies! "
            "You got +4 Candies! You now have: 461 Candies!"
        )
        events = [
            {"type": "received", "amount": 5, "total": 457},
            {"type": "received", "amount": 4, "total": 461},
        ]

        self.window._ocr_recognized(text, -1, events, True)

        self.assertEqual(
            self.window.ocr_candy_label.text(),
            "Received: 5 | Total: 457; Received: 4 | Total: 461",
        )
        self.assertEqual(
            self.window.door_manager.get(1).last_result,
            "RECEIVED +5 (total 457); RECEIVED +4 (total 461)",
        )

    def test_full_basket_stops_macro(self):
        text = "Your candy basket is full! 500 Candies reached!"
        event = {"type": "basket_full", "total": 500}
        self.window.route_manager.route.actions.append(
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.0}
        )

        with patch("app.gui.main_window.PlaybackWorker", FakePlaybackWorker):
            self.window.start_macro()
            self.assertFalse(self.window.ocr_monitor_timer.isActive())
            with patch("app.gui.main_window.QTimer.singleShot"):
                self.window._request_door_ocr(1)
            self.assertTrue(self.window.ocr_monitor_timer.isActive())
            self.window._ocr_recognized(text, -1, event, True)

        self.assertEqual(
            self.window.ocr_candy_label.text(),
            "Candy basket full: 500 Candies",
        )
        self.assertFalse(self.window.ocr_monitor_timer.isActive())
        self.assertEqual(self.window.state, "READY")

    def test_playback_ocr_timer_stays_off_until_door_marker(self):
        with patch.object(self.window, "_start_ocr_worker") as start_worker:
            self.window.state = "RUNNING"
            self.window._poll_ocr_during_playback()
            start_worker.assert_not_called()

            self.window.state = "WAITING_TO_RESTART"
            self.window._poll_ocr_during_playback()
            start_worker.assert_not_called()

            start_worker.reset_mock()
            self.window.state = "PAUSED"
            self.window._poll_ocr_during_playback()
            start_worker.assert_not_called()
            self.assertFalse(self.window.ocr_monitor_timer.isActive())

    def test_playback_ocr_timer_restarts_a_pending_door_scan(self):
        self.window.state = "RUNNING"
        self.window._door_scan_active = True
        self.window._door_check_id = 2
        self.window._door_check_retry_pending = True

        with patch.object(self.window, "_start_door_check_ocr") as start_door_ocr, patch.object(
            self.window, "_start_ocr_worker"
        ) as start_general_ocr:
            self.window._poll_ocr_during_playback()

        start_door_ocr.assert_called_once_with()
        start_general_ocr.assert_not_called()

    def test_pre_e_ocr_frame_cannot_confirm_the_door_after_e(self):
        stale_worker = FakePlaybackWorker()
        stale_worker.start()
        player = FakePlaybackWorker()
        player.start()
        self.window.ocr_worker = stale_worker
        self.window.player = player
        self.window.state = "RUNNING"

        self.window._door_approached(2)
        with patch("app.gui.main_window.QTimer.singleShot"):
            self.window._request_door_ocr(2)
        self.window._ocr_recognized(
            "You already visited this house! Come back in 123s",
            123,
            None,
            True,
        )

        self.assertEqual(self.window._door_check_id, 2)
        self.assertFalse(self.window._door_check_scan_completed)
        self.assertTrue(self.window._door_check_retry_pending)
        self.assertFalse(hasattr(player, "door_check_result"))

    def test_door_approach_starts_ocr_before_the_recorded_e_action(self):
        event = {"type": "received", "amount": 3, "total": 269}
        self.window.route_manager.route.actions.append(
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.0}
        )

        with patch("app.gui.main_window.PlaybackWorker", FakePlaybackWorker), patch.object(
            self.window, "_start_ocr_worker"
        ) as start_ocr:
            self.window.start_macro()
            self.assertFalse(self.window.ocr_monitor_timer.isActive())
            self.window._door_approached(3)
            self.assertTrue(self.window.ocr_monitor_timer.isActive())
            start_ocr.assert_called_once_with(monitoring=True)
            self.window._ocr_worker_mode = "monitoring"
            self.window._ocr_recognized(
                "You got +3 Candies! You now have: 269 Candies!",
                -1,
                event,
                True,
            )

        self.assertEqual(
            self.window.ocr_candy_label.text(), "Received: 3 | Total: 269"
        )
        self.assertIsNone(self.window._door_check_id)
        self.assertTrue(self.window.ocr_monitor_timer.isActive())

    def test_ocr_success_does_not_add_generic_log_noise(self):
        self.window._ocr_recognized(
            "You already visited this house! Come back in 27s",
            27,
            None,
            True,
        )

        self.assertNotIn("OCR region recognized", self.window.log_view.toPlainText())

    def test_repeated_candy_frames_are_logged_once(self):
        event = {"type": "received", "amount": 2, "total": 86}
        self.window._ocr_worker_mode = "monitoring"
        for _ in range(5):
            self.window._ocr_recognized(
                "You got +2 Candies! You now have: 86 Candies!",
                -1,
                event,
                True,
            )

        self.assertEqual(
            self.window.log_view.toPlainText().count("Candies received: 2; total 86"),
            1,
        )

    def test_stale_monitoring_ocr_result_is_ignored(self):
        worker = Mock()
        self.window.ocr_worker = worker
        self.window._ocr_worker_mode = "monitoring"
        self.window._door_scan_active = True
        self.window.state = "RUNNING"
        old_generation = self.window._ocr_worker_generation
        original_status = self.window.ocr_status_label.text()

        self.window._ocr_worker_recognized(
            worker,
            old_generation - 1,
            "SAFE ZONE PROTECTED",
            -1,
            None,
            False,
        )

        self.assertEqual(self.window.ocr_status_label.text(), original_status)
        self.assertNotIn(
            "OCR result was unstable",
            self.window.log_view.toPlainText(),
        )

    def test_stopping_macro_interrupts_monitoring_ocr_worker(self):
        worker = Mock()
        worker.isRunning.return_value = True
        self.window.ocr_worker = worker
        self.window._ocr_worker_mode = "monitoring"

        self.window._stop_workers()

        worker.requestInterruption.assert_called_once_with()
        self.assertEqual(self.window._ocr_worker_generation, 1)

    def test_completed_route_restarts_after_configured_delay(self):
        route = self.window.route_manager.route
        route.actions.append({"type": "KEY_DOWN", "key": "w", "timestamp": 0.0})
        self.window.repeat_delay_spin.setValue(7.0)

        with patch("app.gui.main_window.PlaybackWorker", FakePlaybackWorker):
            self.window._playback_ended(True)

            self.assertEqual(self.window.state, "WAITING_TO_RESTART")
            self.assertTrue(self.window.route_restart_timer.isActive())
            self.assertEqual(self.window.route_restart_timer.interval(), 7000)
            self.assertFalse(self.window.ocr_monitor_timer.isActive())
            self.assertTrue(self.window.ocr_overlay.isVisible())
            self.window._restart_route_after_delay()

        self.assertEqual(self.window.state, "RUNNING")

    def test_stop_cancels_delayed_route_restart(self):
        self.window.route_manager.route.actions.append(
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.0}
        )
        self.window.state = "WAITING_TO_RESTART"
        self.window.route_restart_timer.start(60000)

        self.window.stop_macro()

        self.assertFalse(self.window.route_restart_timer.isActive())
        self.assertEqual(self.window.state, "READY")

    def test_pause_and_resume_freezes_route_repeat_delay(self):
        self.window.state = "WAITING_TO_RESTART"
        self.window.route_restart_timer.start(5000)

        self.window.pause_macro()

        self.assertEqual(self.window.state, "PAUSED")
        self.assertFalse(self.window.route_restart_timer.isActive())

        self.window.start_macro()

        self.assertEqual(self.window.state, "WAITING_TO_RESTART")
        self.assertTrue(self.window.route_restart_timer.isActive())

    def test_close_ignores_queued_route_restart(self):
        self.window.state = "WAITING_TO_RESTART"
        self.window._closing = True

        with patch.object(self.window, "start_macro") as start_macro:
            self.window._restart_route_after_delay()

        start_macro.assert_not_called()

    def test_ocr_monitor_error_stops_macro(self):
        route = self.window.route_manager.route
        route.actions.append(
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.0}
        )

        with patch("app.gui.main_window.PlaybackWorker", FakePlaybackWorker):
            self.window.start_macro()
            self.window.ocr_monitor_timer.start()
            self.window._ocr_failed("screen capture unavailable")

        self.assertFalse(self.window.ocr_monitor_timer.isActive())
        self.assertEqual(self.window.state, "READY")
        self.assertIn("OCR error:", self.window.ocr_status_label.text())

    def test_playback_failure_stops_macro(self):
        route = self.window.route_manager.route
        route.actions.append({"type": "KEY_DOWN", "key": "w", "timestamp": 0.0})

        self.window._playback_failed("input failed")
        self.window._playback_ended(False)

        self.assertEqual(self.window.state, "READY")

    def test_route_completion_schedules_restart(self):
        route = self.window.route_manager.route
        route.actions.append({"type": "KEY_DOWN", "key": "w", "timestamp": 0.0})
        self.window._playback_ended(True)

        self.assertEqual(self.window.state, "WAITING_TO_RESTART")
        self.assertTrue(self.window.route_restart_timer.isActive())

    def test_route_repeats_after_configured_delay(self):
        route = self.window.route_manager.route
        route.actions.append({"type": "KEY_DOWN", "key": "w", "timestamp": 0.0})

        with patch("app.gui.main_window.PlaybackWorker", FakePlaybackWorker):
            self.window._playback_ended(True)
            self.assertEqual(self.window.state, "WAITING_TO_RESTART")
            self.assertTrue(self.window.route_restart_timer.isActive())
            self.window._restart_route_after_delay()

        self.assertEqual(self.window.state, "RUNNING")

    def test_close_saves_unsaved_route_when_requested(self):
        self.window.route_manager.route.actions.append(
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.0}
        )

        with tempfile.TemporaryDirectory() as directory:
            route_path = Path(directory) / "route.json"
            with patch(
                "app.gui.main_window.QMessageBox.question",
                return_value=QMessageBox.Save,
            ), patch(
                "app.gui.main_window.QFileDialog.getSaveFileName",
                return_value=(str(route_path), "Route JSON (*.json)"),
            ), patch.object(self.window, "_save_active_route_path"), patch.object(
                self.window, "_persist_route_cooldowns"
            ):
                self.window.close()

            self.assertTrue(route_path.exists())
            loaded_route = Route.from_dict(
                json.loads(route_path.read_text(encoding="utf-8"))
            )
            self.assertEqual(loaded_route.actions[0]["key"], "w")

    def test_cancel_close_preserves_unsaved_route(self):
        self.window.route_manager.route.actions.append(
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.0}
        )
        close_event = QCloseEvent()

        with patch(
            "app.gui.main_window.QMessageBox.question",
            return_value=QMessageBox.Cancel,
        ):
            self.window.closeEvent(close_event)

        self.assertFalse(close_event.isAccepted())
        self.assertFalse(self.window._closing)
        self.assertEqual(len(self.window.route_manager.route.actions), 1)

    def test_tesseract_path_is_included_in_settings(self):
        configured_path = r"C:\Tools\Tesseract\tesseract.exe"
        self.window.tesseract_path_field.setText(configured_path)

        self.assertEqual(
            self.window._settings_from_ui()["ocr"]["tesseract_cmd"],
            configured_path,
        )

    def test_reset_ocr_region_restores_recommended_region(self):
        for field in self.window.ocr_region_fields.values():
            field.setValue(10)
        tesseract_path = self.window.tesseract_path_field.text()

        with patch.object(self.window.config_manager, "save") as save_settings:
            self.window.reset_ocr_region()

        self.assertEqual(
            {key: field.value() for key, field in self.window.ocr_region_fields.items()},
            OCR_DEFAULT_REGION,
        )
        self.assertEqual(self.window.ocr_overlay.region(), OCR_DEFAULT_REGION)
        self.assertEqual(
            self.window.settings["ocr"]["tesseract_cmd"],
            tesseract_path,
        )
        self.assertEqual(
            save_settings.call_args.args[0]["ocr"]["region"],
            OCR_DEFAULT_REGION,
        )

    def test_last_selected_route_path_is_persisted(self):
        route_path = r"D:\GPO\halloween-loop.json"

        with patch.object(self.window.config_manager, "save") as save_settings:
            self.window._save_active_route_path(route_path)

        self.assertEqual(
            save_settings.call_args.args[0]["route_path"],
            str(Path(route_path).resolve()),
        )
        self.assertEqual(
            self.window.settings["route_path"],
            str(Path(route_path).resolve()),
        )

    def test_repeat_delay_is_included_in_settings(self):
        self.window.repeat_delay_spin.setValue(12.0)

        self.assertEqual(self.window._settings_from_ui()["repeat_delay"], 12.0)

    def test_door_retry_interval_is_included_in_settings(self):
        self.window.door_retry_interval_spin.setValue(6.0)

        self.assertEqual(self.window._settings_from_ui()["door_retry_interval"], 6.0)

    def test_ocr_scan_interval_is_included_in_settings(self):
        self.window.ocr_scan_interval_spin.setValue(2.5)

        self.assertEqual(self.window._settings_from_ui()["ocr_scan_interval"], 2.5)

    def test_language_switch_updates_interface_and_persists_selection(self):
        self.window.logger.log("Application ready")
        with patch.object(self.window.config_manager, "save") as save_settings:
            self.window.set_language("RU")

        self.assertEqual(self.window.language, "RU")
        self.assertEqual(self.window.tabs.tabText(0), RU_TRANSLATIONS["Status"])
        self.assertEqual(
            self.window.start_button.text(),
            f"{RU_TRANSLATIONS['START']} (F6)",
        )
        self.assertEqual(self.window.findChild(QLabel, "brandTitle").text(), "GPO / HALLOWEEN")
        self.assertIn(
            RU_TRANSLATIONS["Application ready"],
            self.window.log_view.toPlainText(),
        )
        self.assertTrue(
            self.window.state_label.text().startswith(RU_TRANSLATIONS["Status:"])
        )
        self.assertEqual(save_settings.call_args.args[0]["language"], "RU")

        with patch.object(self.window.config_manager, "save") as save_settings:
            self.window.set_language("ENG")

        self.assertEqual(self.window.language, "ENG")
        self.assertEqual(self.window.tabs.tabText(0), "Status")
        self.assertEqual(self.window.start_button.text(), "START (F6)")
        self.assertIn("Application ready", self.window.log_view.toPlainText())
        self.assertEqual(self.window.state_label.text(), "Status: STOPPED")
        self.assertEqual(save_settings.call_args.args[0]["language"], "ENG")

    def test_all_door_ocr_timing_and_retry_controls_are_in_settings(self):
        self.window.door_e_press_limit_spin.setValue(8)
        self.window.ocr_frame_interval_spin.setValue(0.3)
        self.window.playback_speed_spin.setValue(1.5)
        settings = self.window._settings_from_ui()

        self.assertEqual(settings["door_e_press_limit"], 5)
        self.assertEqual(settings["ocr_frame_interval"], 0.3)
        self.assertEqual(settings["playback_speed"], 1.5)
        self.assertNotIn("recovery_key_interval", settings)
        self.assertNotIn("respawn_delay", settings)

    def test_reset_settings_keeps_route_and_route_cooldowns(self):
        route = self.window.route_manager.route
        route.actions.append({"type": "KEY_DOWN", "key": "w", "timestamp": 0.0})
        route_path = r"C:\routes\saved-route.json"
        cooldowns = {"route-key": {"1": {"state": "COOLDOWN"}}}
        self.window.settings["route_path"] = route_path
        self.window.settings["door_cooldowns"] = cooldowns
        self.window.slot_spin.setValue(8)

        with patch(
            "app.gui.main_window.QMessageBox.question",
            return_value=QMessageBox.Yes,
        ), patch.object(self.window.config_manager, "save") as save_settings, patch.object(
            self.window.hotkeys, "start"
        ):
            self.window.reset_settings()

        self.assertIs(self.window.route_manager.route, route)
        self.assertEqual(route.actions[0]["key"], "w")
        self.assertEqual(self.window.settings["route_path"], route_path)
        self.assertEqual(self.window.settings["door_cooldowns"], cooldowns)
        self.assertEqual(self.window.slot_spin.value(), 4)
        saved = save_settings.call_args.args[0]
        self.assertEqual(saved["route_path"], route_path)
        self.assertEqual(saved["door_cooldowns"], cooldowns)


if __name__ == "__main__":
    unittest.main()