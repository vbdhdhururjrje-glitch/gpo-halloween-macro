import unittest

from app.doors.door import DoorState
from app.doors.door_manager import DoorManager
from app.route.route_point import RoutePoint


class DoorManagerTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.wall_now = 1000.0
        self.manager = DoorManager(
            clock=lambda: self.now,
            wall_clock=lambda: self.wall_now,
        )
        self.points = [
            RoutePoint(id=2, type="DOOR", timestamp=4.0, action_index=8),
            RoutePoint(id=3, type="DOOR", timestamp=9.0, action_index=18),
        ]
        self.manager.sync_from_points(self.points)

    def test_sync_tracks_only_doors_in_route_order(self):
        self.assertEqual([door.id for door in self.manager.doors], [2, 3])
        self.assertEqual([door.route_order for door in self.manager.doors], [1, 2])

    def test_cooldowns_expire_independently(self):
        self.manager.record_ocr_result(2, cooldown=10)
        self.manager.record_ocr_result(3, cooldown=20)

        self.now = 111.0
        self.assertEqual(self.manager.get(2).state, DoorState.AVAILABLE)
        self.assertEqual(self.manager.get(3).state, DoorState.COOLDOWN)
        self.assertEqual([door.id for door in self.manager.available_doors()], [2])

    def test_unstable_ocr_marks_door_unknown_and_counts_failure(self):
        door = self.manager.record_ocr_result(2, stable=False)

        self.assertEqual(door.state, DoorState.UNKNOWN)
        self.assertEqual(door.failed_ocr_count, 1)
        self.assertEqual(door.last_result, "OCR_UNSTABLE")

    def test_candy_event_marks_success_and_records_amount(self):
        door = self.manager.record_ocr_result(
            3,
            candy_event={"type": "received", "amount": 4, "total": 80},
        )

        self.assertEqual(door.state, DoorState.SUCCESS)
        self.assertEqual(door.last_candy_amount, 4)
        self.assertEqual(door.last_result, "RECEIVED +4")

    def test_records_multiple_candy_events_from_one_ocr_result(self):
        door = self.manager.record_ocr_result(
            3,
            candy_events=[
                {"type": "received", "amount": 5, "total": 457},
                {"type": "received", "amount": 4, "total": 461},
            ],
        )

        self.assertEqual(door.state, DoorState.SUCCESS)
        self.assertEqual(door.last_candy_amount, 4)
        self.assertEqual(
            door.last_result,
            "RECEIVED +5 (total 457); RECEIVED +4 (total 461)",
        )

    def test_sync_preserves_state_for_existing_door_and_drops_removed_door(self):
        self.manager.record_ocr_result(3, cooldown=12)
        self.manager.sync_from_points([self.points[1]])

        self.assertEqual(self.manager.get(3).state, DoorState.COOLDOWN)
        self.assertIsNone(self.manager.get(2))

    def test_cooldowns_export_as_wall_clock_expirations_and_restore(self):
        self.manager.record_ocr_result(2, cooldown=30)
        saved = self.manager.export_cooldowns()
        restored_manager = DoorManager(
            clock=lambda: 500.0,
            wall_clock=lambda: 1005.0,
        )

        restored = restored_manager.restore_cooldowns(self.points, saved)

        self.assertEqual(restored, 1)
        self.assertEqual(restored_manager.cooldown_remaining(2), 25.0)
        self.assertEqual(restored_manager.get(3).state, DoorState.AVAILABLE)

    def test_expired_saved_cooldown_restores_as_available(self):
        restored = self.manager.restore_cooldowns(self.points, {"2": 999.0})

        self.assertEqual(restored, 0)
        self.assertEqual(self.manager.get(2).state, DoorState.AVAILABLE)

    def test_non_finite_saved_cooldowns_are_ignored(self):
        restored = self.manager.restore_cooldowns(
            self.points,
            {"2": float("nan"), "3": float("inf")},
        )

        self.assertEqual(restored, 0)
        self.assertEqual(self.manager.get(2).state, DoorState.AVAILABLE)
        self.assertEqual(self.manager.get(3).state, DoorState.AVAILABLE)


if __name__ == "__main__":
    unittest.main()