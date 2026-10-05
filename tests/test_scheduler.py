import unittest

from app.doors.door_manager import DoorManager
from app.doors.scheduler import DoorScheduler
from app.route.route import Route
from app.route.route_point import RoutePoint


class DoorSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.manager = DoorManager(clock=lambda: self.now)
        self.manager.sync_from_points(
            [
                RoutePoint(id=2, type="DOOR", timestamp=4.0, action_index=8),
                RoutePoint(id=3, type="DOOR", timestamp=9.0, action_index=18),
            ]
        )
        self.scheduler = DoorScheduler(self.manager)

    def test_chooses_first_available_in_route_order(self):
        self.manager.record_ocr_result(2, cooldown=10)

        self.assertEqual(self.scheduler.choose_next().id, 3)

    def test_explicit_distance_precedes_route_order(self):
        self.assertEqual(
            self.scheduler.choose_next({2: 12.0, 3: 4.0}).id,
            3,
        )

    def test_route_order_breaks_equal_distance(self):
        self.assertEqual(
            self.scheduler.choose_next({2: 4.0, 3: 4.0}).id,
            2,
        )

    def test_reports_soonest_cooldown_when_no_door_is_available(self):
        self.manager.record_ocr_result(2, cooldown=10)
        self.manager.record_ocr_result(3, cooldown=20)
        self.now = 103.5

        self.assertIsNone(self.scheduler.choose_next())
        self.assertEqual(self.scheduler.seconds_until_next_available(), 6.5)

    def test_returns_none_when_no_available_or_cooling_door_exists(self):
        self.manager.record_ocr_result(2, stable=False)
        self.manager.record_ocr_result(3, stable=False)

        self.assertIsNone(self.scheduler.choose_next())
        self.assertIsNone(self.scheduler.seconds_until_next_available())

    def test_cached_cooldown_does_not_skip_door_ocr_interaction(self):
        route = Route(
            points=[RoutePoint(id=2, type="DOOR", timestamp=1.0, action_index=0)],
            actions=[
                {"type": "KEY_DOWN", "key": "e"},
                {"type": "KEY_UP", "key": "e"},
            ],
        )
        self.manager.sync_from_points(route.points)
        self.manager.record_ocr_result(2, cooldown=20)

        self.assertEqual(
            self.scheduler.door_interaction_release_indices(route),
            {1: (2, "e")},
        )

    def test_door_marker_maps_to_release_of_following_e_pair(self):
        route = Route(
            points=[RoutePoint(id=2, type="DOOR", timestamp=1.0, action_index=1)],
            actions=[
                {"type": "KEY_DOWN", "key": "w"},
                {"type": "KEY_DOWN", "key": "vk:69"},
                {"type": "KEY_UP", "key": "vk:69"},
                {"type": "KEY_DOWN", "key": "w"},
            ],
        )

        self.assertEqual(
            self.scheduler.door_interaction_release_indices(route),
            {2: (2, "vk:69")},
        )

    def test_door_marker_maps_to_start_of_following_e_pair(self):
        route = Route(
            points=[RoutePoint(id=2, type="DOOR", timestamp=1.0, action_index=1)],
            actions=[
                {"type": "KEY_DOWN", "key": "w"},
                {"type": "KEY_DOWN", "key": "vk:69"},
                {"type": "KEY_UP", "key": "vk:69"},
                {"type": "KEY_DOWN", "key": "w"},
            ],
        )

        self.assertEqual(self.scheduler.door_interaction_start_indices(route), {1: 2})


if __name__ == "__main__":
    unittest.main()