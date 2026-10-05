import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.route.route_manager import RouteManager


class RouteManagerTests(unittest.TestCase):
    def test_recording_and_json_round_trip(self):
        manager = RouteManager()
        manager.start_recording("Test Route")
        manager.add_action({"type": "KEY_DOWN", "key": "w"})
        point = manager.add_point("door")
        manager.stop_recording()

        self.assertEqual(point.action_index, 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.json"
            manager.save(path)
            loaded = RouteManager().load(path)

        self.assertEqual(loaded.name, "Test Route")
        self.assertEqual(loaded.start["type"], "START_POINT")
        self.assertEqual(loaded.points[0].type, "DOOR")
        self.assertEqual(loaded.actions[0]["key"], "w")

    def test_marker_requires_recording_and_supported_type(self):
        manager = RouteManager()
        with self.assertRaises(RuntimeError):
            manager.add_point("DOOR")

        manager.start_recording()
        with self.assertRaises(ValueError):
            manager.add_point("DEAD")

    def test_pause_does_not_advance_route_time(self):
        manager = RouteManager()
        with patch(
            "app.route.route_manager.time.monotonic",
            side_effect=[100.0, 102.0, 104.0, 110.0, 111.0],
        ):
            manager.start_recording()
            self.assertEqual(manager.elapsed(), 2.0)
            manager.pause_recording()
            self.assertEqual(manager.elapsed(), 4.0)
            manager.resume_recording()
            self.assertEqual(manager.elapsed(), 5.0)

    def test_elapsed_preserves_sub_millisecond_input_timing(self):
        manager = RouteManager()
        manager.recording_started_at = 10.0

        with patch("app.route.route_manager.time.monotonic", return_value=10.0004):
            self.assertEqual(manager.elapsed(), 0.0004)

    def test_invalid_route_shape_is_rejected(self):
        manager = RouteManager()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps({"points": {}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                manager.load(path)

    def test_route_with_non_object_start_metadata_is_rejected(self):
        manager = RouteManager()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(
                json.dumps({"start": [], "actions": []}),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                manager.load(path)

    def test_route_with_unsupported_action_type_is_rejected(self):
        manager = RouteManager()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(
                json.dumps({"actions": [{"type": "KEY_PRESS", "key": "w"}]}),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                manager.load(path)

    def test_delete_removes_route_from_memory_and_disk(self):
        manager = RouteManager()
        manager.start_recording()
        manager.add_action({"type": "KEY_DOWN", "key": "w"})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.json"
            manager.save(path)
            manager.delete()

            self.assertFalse(path.exists())

        self.assertEqual(manager.route.actions, [])
        self.assertEqual(manager.route.points, [])
        self.assertIsNone(manager.file_path)

    def test_legacy_markers_and_spawn_metadata_are_discarded_without_losing_route(self):
        manager = RouteManager()
        manager.start_recording()
        manager.add_action({"type": "KEY_DOWN", "key": "w"})
        manager.add_point("DOOR")
        manager.stop_recording()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.json"
            manager.save(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["points"].insert(
                0,
                {
                    "id": 99,
                    "type": "WAYPOINT",
                    "timestamp": 0.0,
                    "action_index": 0,
                    "snapshot_hash": "a" * 64,
                },
            )
            data["points"].append(
                {
                    "id": 100,
                    "type": "DEATH",
                    "timestamp": 0.0,
                    "action_index": 0,
                }
            )
            data["start"]["respawn_hash"] = "b" * 64
            data["start"]["respawn_hash_mode"] = "structural"
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = RouteManager().load(path)

        self.assertEqual([point.type for point in loaded.points], ["DOOR"])
        self.assertEqual(loaded.actions[0]["key"], "w")
        self.assertNotIn("respawn_hash", loaded.start)

    def test_start_cursor_position_survives_json_round_trip(self):
        manager = RouteManager()
        manager.start_recording(cursor_position={"x": 321, "y": 654})
        manager.stop_recording()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.json"
            manager.save(path)
            loaded = RouteManager().load(path)

        self.assertEqual(loaded.start["cursor_position"], {"x": 321, "y": 654})

    def test_recorded_screen_size_survives_json_round_trip(self):
        manager = RouteManager()
        manager.start_recording(screen_size={"width": 1920, "height": 1080})
        manager.stop_recording()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.json"
            manager.save(path)
            loaded = RouteManager().load(path)

        self.assertEqual(loaded.start["screen_size"], {"width": 1920, "height": 1080})

    def test_legacy_respawn_metadata_is_removed_when_route_is_loaded(self):
        manager = RouteManager()
        manager.start_recording()
        manager.route.start["respawn_hash"] = "b" * 64
        manager.route.start["respawn_hash_mode"] = "structural"
        manager.stop_recording()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.json"
            manager.save(path)
            loaded = RouteManager().load(path)

        self.assertNotIn("respawn_hash", loaded.start)
        self.assertNotIn("respawn_hash_mode", loaded.start)


if __name__ == "__main__":
    unittest.main()