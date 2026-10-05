import unittest
from unittest.mock import call, patch

import pytesseract
from PIL import Image
from app.vision.ocr import OCRService, OCRWorker


class OCRServiceTests(unittest.TestCase):
    def test_extracts_cooldown_from_game_message(self):
        text = "You can Trick or Treat again in 27 seconds"
        self.assertEqual(OCRService.extract_cooldown(text), 27)

    def test_extracts_cooldown_across_line_breaks_case_insensitively(self):
        text = "you can trick or treat\nagain in 8 seconds"
        self.assertEqual(OCRService.extract_cooldown(text), 8)

    def test_extracts_cooldown_from_already_visited_house_message(self):
        text = "You already visited this house! Come back in 175"
        self.assertEqual(OCRService.extract_cooldown(text), 175)

    def test_extracts_cooldown_from_alredy_visited_house_message(self):
        text = "You alredy visited this house! Come back in 60s"
        self.assertEqual(OCRService.extract_cooldown(text), 60)

        result = OCRService.resolve_stable_samples([(text, 90.0)] * 3)
        self.assertEqual(
            result,
            ("You already visited this house! Come back in 60s", 60, None, True),
        )

    def test_extracts_visited_house_cooldown_with_comma(self):
        text = "You already visited this house, Come back in 119"
        self.assertEqual(OCRService.extract_cooldown(text), 119)

    def test_extracts_visited_house_cooldown_across_ocr_line_breaks(self):
        text = "you already visited this house!\ncome back in 42"
        self.assertEqual(OCRService.extract_cooldown(text), 42)

    def test_uses_first_cooldown_digits_within_175_second_limit(self):
        variants = (
            ("You already visited this houset Come back in 993", 99),
            ("You already visited this house! Come back in 993s", 99),
            ("You already visited this house! Come back in 1588", 158),
            ("You already visited this house! Come back in 1753", 175),
            ("You already visited a houset Come back in 1693", 169),
            ("You already visited _ houset Come back in 1696", 169),
        )
        for text, expected in variants:
            with self.subTest(text=text):
                self.assertEqual(OCRService.extract_cooldown(text), expected)

    def test_returns_none_when_no_cooldown_message_exists(self):
        self.assertIsNone(OCRService.extract_cooldown("Door opened successfully"))

    def test_reports_repeated_unrelated_screen_text_without_confirmation(self):
        result = OCRService.resolve_stable_samples(
            [("SAFE ZONE PROTECTED", 95.0)] * 3
        )

        self.assertEqual(result, ("SAFE ZONE PROTECTED", -1, None, False))

    def test_unstable_resolution_exposes_best_raw_text_for_diagnostics(self):
        result = OCRService.resolve_stable_samples(
            [
                ("You already visited this house! Come back in", 68.0),
                ("SAFE ZONE PROTECTED", 94.0),
                ("", 0.0),
            ]
        )

        self.assertEqual(result, ("SAFE ZONE PROTECTED", -1, None, False))

    def test_cooldown_result_excludes_safe_zone_text(self):
        text = (
            "SAFE ZONE PROTECTED\n"
            "You already visited this house! Come back in 19s"
        )
        result = OCRService.resolve_stable_samples([(text, 92.0)] * 3)

        self.assertEqual(
            result,
            ("You already visited this house! Come back in 19s", 19, None, True),
        )

    def test_candy_event_result_excludes_safe_zone_text(self):
        text = (
            "SAFE ZONE PROTECTED\n"
            r"C)Candies\werelstolentivoulnowshave: 165 Candies!"
        )
        result = OCRService.resolve_stable_samples([(text, 86.0)] * 3)

        self.assertEqual(
            result,
            (
                "1 Candies were stolen! You now have: 165 Candies!",
                -1,
                {"type": "stolen", "amount": 1, "total": 165},
                True,
            ),
        )

    def test_extracts_stolen_candies_and_current_total(self):
        text = "1 Candies were stolen! You now have: 392 Candies!"
        self.assertEqual(
            OCRService.extract_candy_event(text),
            {"type": "stolen", "amount": 1, "total": 392},
        )

    def test_recovers_stolen_event_when_ocr_adds_t_before_you(self):
        samples = [
            (
                "SAFERZONE\nPROTECTED\n"
                "4 Candies were stolent You now have: 393 Candies!",
                72.0,
            ),
            (
                "SAFEIZONE\nPROTECTED\n"
                "4 Candies were stolent You now have: 393 Candies!",
                68.0,
            ),
            (
                "SAFERZONE PROTECTED "
                "4 Candies were stolent You now have: 393 Candies!",
                70.0,
            ),
        ]

        self.assertEqual(
            OCRService.extract_candy_events(samples[0][0]),
            [{"type": "stolen", "amount": 4, "total": 393}],
        )
        self.assertEqual(
            OCRService.resolve_stable_samples(samples),
            (
                "4 Candies were stolen! You now have: 393 Candies!",
                -1,
                {"type": "stolen", "amount": 4, "total": 393},
                True,
            ),
        )

    def test_extracts_stolen_event_from_glued_ocr_words_and_confused_digit(self):
        variants = (
            r"C)Candies\werelstolen\ivoulnowshave: 165 Candies!",
            r"CCandies\werelstolentivoulnowshave: 165 Candies!",
            r"C]Candies\werelstolentivoulnowshave: 165 Candies!",
        )
        expected = {"type": "stolen", "amount": 1, "total": 165}

        for text in variants:
            with self.subTest(text=text):
                self.assertEqual(OCRService.extract_candy_event(text), expected)

        result = OCRService.resolve_stable_samples(
            [(text, 72.0) for text in variants]
        )
        self.assertEqual(
            result,
            (
                "1 Candies were stolen! You now have: 165 Candies!",
                -1,
                expected,
                True,
            ),
        )

    def test_extracts_received_candies_and_current_total(self):
        text = "You got +3 Candies! You now have: 404 Candies!"
        self.assertEqual(
            OCRService.extract_candy_event(text),
            {"type": "received", "amount": 3, "total": 404},
        )

    def test_recovers_received_event_when_ocr_reads_four_as_quote(self):
        text = "SAFERZONE\nPROTECTED\nYou got +2 Candies! You now have: «10 Candies!"
        event = {"type": "received", "amount": 2, "total": 410}
        self.assertEqual(OCRService.extract_candy_events(text), [event])

        result = OCRService.resolve_stable_samples(
            [
                (text, 72.0),
                (
                    "SAFEIZONE\nPROTECTED\n"
                    "You got +2 Candies! You now have: «10 Candies!",
                    69.0,
                ),
                ("SAFERZONE PROTECTED", 94.0),
            ]
        )
        self.assertEqual(
            result,
            (
                "You got +2 Candies! You now have: 410 Candies!",
                -1,
                event,
                True,
            ),
        )

    def test_rejects_candy_amount_outside_event_range(self):
        text = "You got +16 Candies! You now have: 420 Candies!"
        self.assertIsNone(OCRService.extract_candy_event(text))

    def test_extracts_full_basket_total(self):
        for capacity in (100, 250, 500):
            with self.subTest(capacity=capacity):
                text = f"Your candy basket is full! {capacity} Candies reached!"
                self.assertEqual(OCRService.extract_basket_full(text), capacity)

    def test_rejects_unrecognized_full_basket_capacity(self):
        text = "Your candy basket is full! 350 Candies reached!"
        self.assertIsNone(OCRService.extract_basket_full(text))

    def test_extracts_candy_event_from_multiline_ocr_text(self):
        text = "You got +15 Candies!\nYou now have: 9999 Candies!"
        self.assertEqual(
            OCRService.extract_candy_event(text),
            {"type": "received", "amount": 15, "total": 9999},
        )

    def test_extracts_two_candy_events_in_display_order(self):
        text = (
            "You got +5 Candies! You now have: 457 Candies! "
            "You got +4 Candies! You now have: 461 Candies!"
        )
        self.assertEqual(
            OCRService.extract_candy_events(text),
            [
                {"type": "received", "amount": 5, "total": 457},
                {"type": "received", "amount": 4, "total": 461},
            ],
        )

    def test_extracts_stolen_then_received_messages_from_screen(self):
        text = (
            "4 Candies were stolen! You now have: 168 Candies!\n"
            "You got +1 Candies! You now have: 169 Candies!"
        )
        events = [
            {"type": "stolen", "amount": 4, "total": 168},
            {"type": "received", "amount": 1, "total": 169},
        ]

        self.assertEqual(OCRService.extract_candy_events(text), events)
        result = OCRService.resolve_stable_samples([(text, 90.0)] * 3)
        self.assertEqual(result[2:], (events, True))

    def test_stable_resolution_preserves_multiple_candy_events(self):
        text = (
            "You got +5 Candies! You now have: 457 Candies! "
            "You got +4 Candies! You now have: 461 Candies!"
        )
        events = [
            {"type": "received", "amount": 5, "total": 457},
            {"type": "received", "amount": 4, "total": 461},
        ]
        result = OCRService.resolve_stable_samples(
            [(text, 90, ["green", "orange", "green", "orange"])] * 3
        )

        self.assertEqual(result[2:], (events, True))

    def test_confirms_cooldown_when_two_confident_frames_agree(self):
        result = OCRService.resolve_stable_samples(
            [
                ("You can Trick or Treat again in 27 seconds", 90),
                ("You can Trick or Treat again in 27 seconds", 82),
                ("You can Trick or Treat again in 2T seconds", 74),
            ]
        )
        self.assertEqual(
            result,
            ("You can Trick or Treat again in 27 seconds", 27, None, True),
        )

    def test_marks_disagreeing_frames_unstable(self):
        result = OCRService.resolve_stable_samples(
            [
                ("You can Trick or Treat again in 27 seconds", 90),
                ("You can Trick or Treat again in 2 seconds", 82),
                ("Door opened", 74),
            ]
        )
        self.assertEqual(result[1:], (-1, None, False))

    def test_confirms_visible_visited_message_with_low_confidence(self):
        text = "You already visited this house! Come back in 19s"
        result = OCRService.resolve_stable_samples(
            [
                (text, 38),
                (text, 34),
                ("PROTECTED", 90),
            ]
        )

        self.assertEqual(result, (text, 19, None, True))

    def test_requires_two_low_confidence_actionable_frames_to_confirm(self):
        result = OCRService.resolve_stable_samples(
            [
                ("You can Trick or Treat again in 27 seconds", 30),
                ("You can Trick or Treat again in 2T seconds", 42),
                ("Door opened", 42),
            ]
        )
        self.assertEqual(result[1:], (-1, None, False))

    def test_confirms_received_event_with_green_amount_and_orange_total(self):
        text = "You got +3 Candies! You now have: 404 Candies!"
        result = OCRService.resolve_stable_samples(
            [(text, 90, ["green", "orange"])] * 3
        )

        self.assertEqual(
            result,
            (
                text,
                -1,
                {"type": "received", "amount": 3, "total": 404},
                True,
            ),
        )

    def test_confirms_stolen_event_with_red_amount_and_orange_total(self):
        text = "1 Candies were stolen! You now have: 392 Candies!"
        result = OCRService.resolve_stable_samples(
            [(text, 90, ["red", "orange"])] * 3
        )

        self.assertEqual(
            result[2:],
            ({"type": "stolen", "amount": 1, "total": 392}, True),
        )

    def test_ignores_digit_color_conflicts_and_uses_text_only(self):
        text = "You got +3 Candies! You now have: 404 Candies!"
        result = OCRService.resolve_stable_samples(
            [(text, 90, ["red", "orange"])] * 3
        )

        self.assertEqual(
            result,
            (
                text,
                -1,
                {"type": "received", "amount": 3, "total": 404},
                True,
            ),
        )

    def test_confirms_visited_house_cooldown_regardless_of_digit_color(self):
        text = "You already visited this house! Come back in 119"
        red = OCRService.resolve_stable_samples(
            [(text, 90, ["red"])] * 3
        )
        orange = OCRService.resolve_stable_samples(
            [(text, 90, ["orange"])] * 3
        )
        green = OCRService.resolve_stable_samples([(text, 90, ["green"])] * 3)

        self.assertEqual(red[1:], (119, None, True))
        self.assertEqual(orange[1:], (119, None, True))
        self.assertEqual(green[1:], (119, None, True))

    def test_confirms_cooldown_when_candy_notification_disappears_between_frames(self):
        combined = (
            "You got +10 Candies! You now have: 156 Candies! "
            "You already visited this house! Come back in 173s"
        )
        cooldown_only = "You already visited this house! Come back in 173s"
        result = OCRService.resolve_stable_samples(
            [
                (combined, 95, ["green", "orange", "orange"]),
                (cooldown_only, 92, ["orange"]),
                (combined, 94, ["green", "orange", "orange"]),
            ]
        )

        self.assertEqual(result[1], 173)
        self.assertTrue(result[3])

    def test_transient_candy_event_does_not_confirm_cooldown_gate(self):
        cooldown_only = "You already visited this house! Come back in 173s"
        combined = (
            "You got +10 Candies! You now have: 156 Candies! "
            "You already visited this house! Come back in 173s"
        )
        result = OCRService.resolve_stable_samples(
            [
                (combined, 92, ["green", "orange", "orange"]),
                (cooldown_only, 92, ["orange"]),
            ]
        )

        self.assertEqual(result[1], 173)
        self.assertIsNone(result[2])
        self.assertTrue(result[3])

    def test_confirms_decrementing_cooldown_across_one_second_boundary(self):
        result = OCRService.resolve_stable_samples(
            [
                ("You already visited this house! Come back in 173s", 90, ["orange"]),
                ("You already visited this house! Come back in 172s", 90, ["orange"]),
                ("You already visited this house! Come back in 172s", 90, ["orange"]),
            ]
        )

        self.assertEqual(result[1], 172)
        self.assertTrue(result[3])

    def test_prefers_latest_when_two_cooldown_messages_are_visible(self):
        texts = [
            "You already visited this house! Come back in 151s\n"
            "You already visited this house! Come back in 147s",
            "You already visited this house! Come back in 150s\n"
            "You already visited this house! Come back in 146s",
            "You already visited this house! Come back in 149s\n"
            "You already visited this house! Come back in 145s",
        ]
        result = OCRService.resolve_stable_samples(
            [(text, 92, ["orange", "orange"]) for text in texts]
        )

        self.assertEqual(OCRService.extract_cooldown(texts[0]), 147)
        self.assertEqual(result[1], 145)
        self.assertTrue(result[3])

    def test_stable_result_keeps_only_latest_cooldown_message(self):
        text = (
            "You already visited this house! Come back in 1008\n"
            "You already visited this house! Come back in 958"
        )
        result = OCRService.resolve_stable_samples([(text, 90)] * 3)

        self.assertEqual(
            result[0],
            "You already visited this house! Come back in 95s",
        )
        self.assertEqual(result[1:], (95, None, True))

    def test_trick_or_treat_cooldown_is_based_on_text_not_color(self):
        text = "You can Trick or Treat again in 27 seconds"
        red = OCRService.resolve_stable_samples([(text, 90, ["red"])] * 3)
        orange = OCRService.resolve_stable_samples([(text, 90, ["orange"])] * 3)

        self.assertEqual(red[1:], (27, None, True))
        self.assertEqual(orange[1:], (27, None, True))

    def test_stable_red_full_basket_message_becomes_terminal_event(self):
        text = "Your candy basket is full! 500 Candies reached!"
        result = OCRService.resolve_stable_samples(
            [(text, 90, ["red"])] * 3
        )

        self.assertEqual(result[2:], ({"type": "basket_full", "total": 500}, True))

    def test_full_basket_message_uses_text_not_color(self):
        text = "Your candy basket is full! 500 Candies reached!"
        result = OCRService.resolve_stable_samples(
            [(text, 90, ["orange"])] * 3
        )

        self.assertEqual(result[2:], ({"type": "basket_full", "total": 500}, True))

    def test_uses_configured_tesseract_executable(self):
        configured_path = r"C:\Tools\Tesseract\tesseract.exe"
        previous_path = pytesseract.pytesseract.tesseract_cmd
        try:
            with patch(
                "app.vision.ocr.ScreenCapture.capture_region",
                return_value=Image.new("RGB", (10, 10), "black"),
            ), patch(
                "pytesseract.image_to_data",
                return_value={"text": ["door"], "conf": ["90"]},
            ):
                self.assertEqual(
                    OCRService.read_region_with_confidence(
                        {"x": 0, "y": 0, "width": 10, "height": 10},
                        configured_path,
                    ),
                    ("door", 90.0),
                )
                self.assertEqual(
                    pytesseract.pytesseract.tesseract_cmd,
                    configured_path,
                )
        finally:
            pytesseract.pytesseract.tesseract_cmd = previous_path

    def test_parser_keeps_tesseract_lines_separate(self):
        first_line = "You already visited this house! Come back in 1008".split()
        second_line = "You already visited this house! Come back in 958".split()
        words = first_line + second_line
        result = OCRService._parse_tesseract_result(
            {
                "text": words,
                "conf": ["90"] * len(words),
                "block_num": [1] * len(first_line) + [1] * len(second_line),
                "par_num": [1] * len(first_line) + [1] * len(second_line),
                "line_num": [1] * len(first_line) + [2] * len(second_line),
            },
        )

        self.assertEqual(result[0], " ".join(first_line) + "\n" + " ".join(second_line))

    def test_parser_returns_empty_text_when_tesseract_recognizes_no_words(self):
        result = OCRService._parse_tesseract_result(
            {"text": [""], "conf": ["-1"]},
        )

        self.assertEqual(result, ("", 0.0))

    def test_tall_region_uses_block_mode_before_line_mode_fallback(self):
        primary = {"text": ["_", "Oe"], "conf": ["10", "12"]}
        fallback = {
            "text": ["You", "already", "visited", "this", "house", "Come", "back", "in", "147"],
            "conf": ["90"] * 9,
            "left": [0] * 9,
            "top": [0] * 9,
            "width": [20] * 9,
            "height": [20] * 9,
        }
        with patch(
            "app.vision.ocr.ScreenCapture.capture_region",
            return_value=Image.new("RGB", (200, 60), "black"),
        ), patch(
            "pytesseract.image_to_data",
            side_effect=[primary, fallback],
        ) as image_to_data:
            text, confidence = OCRService.read_region_frame(
                {"x": 0, "y": 0, "width": 200, "height": 60},
                r"C:\Tools\Tesseract\tesseract.exe",
            )

        self.assertIn("147", text)
        self.assertEqual(confidence, 90.0)
        self.assertEqual(
            [call.kwargs["config"] for call in image_to_data.call_args_list],
            ["--oem 3 --psm 6", "--oem 3 --psm 7"],
        )

    def test_accepts_actionable_primary_frame_at_actionable_confidence(self):
        words = "You already visited this house! Come back in 34s".split()
        primary = {
            "text": words,
            "conf": ["40"] * len(words),
            "block_num": [1] * len(words),
            "par_num": [1] * len(words),
            "line_num": [1] * len(words),
        }
        with patch(
            "app.vision.ocr.ScreenCapture.capture_region",
            return_value=Image.new("RGB", (500, 38), "black"),
        ), patch(
            "pytesseract.image_to_data",
            return_value=primary,
        ) as image_to_data:
            text, confidence = OCRService.read_region_frame(
                {"x": 440, "y": 192, "width": 500, "height": 38}
            )

        self.assertEqual(OCRService.extract_cooldown(text), 34)
        self.assertEqual(confidence, 40.0)
        image_to_data.assert_called_once()

    def test_upscaled_block_fallback_recovers_stolen_candy_message(self):
        fragments = {"text": ["Oe", "TZ"], "conf": ["18", "21"]}
        message_words = (
            "1 Candies were stolen! You now have: 392 Candies!".split()
        )
        recognized_message = {
            "text": message_words,
            "conf": ["72"] * len(message_words),
            "block_num": [1] * len(message_words),
            "par_num": [1] * len(message_words),
            "line_num": [1] * len(message_words),
        }
        with patch(
            "app.vision.ocr.ScreenCapture.capture_region",
            return_value=Image.new("RGB", (320, 50), "black"),
        ), patch(
            "pytesseract.image_to_data",
            side_effect=[fragments, recognized_message],
        ) as image_to_data:
            text, confidence = OCRService.read_region_frame(
                {"x": 0, "y": 0, "width": 320, "height": 50}
            )

        self.assertEqual(OCRService.extract_candy_event(text), {
            "type": "stolen",
            "amount": 1,
            "total": 392,
        })
        self.assertEqual(confidence, 72.0)
        self.assertEqual(
            [call.kwargs["config"] for call in image_to_data.call_args_list],
            ["--oem 3 --psm 7", "--oem 3 --psm 6"],
        )
        self.assertEqual(image_to_data.call_args.args[0].size, (640, 100))

    def test_tall_ocr_region_tries_block_segmentation_first(self):
        text = "You already visited this house! Come back in 158s"
        words = text.split()
        recognized_message = {
            "text": words,
            "conf": ["72"] * len(words),
            "block_num": [1] * len(words),
            "par_num": [1] * len(words),
            "line_num": [1] * len(words),
        }
        with patch(
            "app.vision.ocr.ScreenCapture.capture_region",
            return_value=Image.new("RGB", (517, 116), "black"),
        ), patch(
            "pytesseract.image_to_data",
            return_value=recognized_message,
        ) as image_to_data:
            text, confidence = OCRService.read_region_frame(
                {"x": 0, "y": 0, "width": 517, "height": 116}
            )

        self.assertEqual(OCRService.extract_cooldown(text), 158)
        self.assertEqual(confidence, 72.0)
        image_to_data.assert_called_once()
        self.assertEqual(
            image_to_data.call_args.kwargs["config"],
            "--oem 3 --psm 6",
        )

    def test_worker_fast_accepts_clear_door_message_from_first_frame(self):
        text = "You already visited this house! Come back in 119"
        worker = OCRWorker({"x": 0, "y": 0, "width": 592, "height": 63})
        results = []
        worker.recognized.connect(lambda *result: results.append(result))

        with patch.object(
            OCRService,
            "read_region_frame",
            return_value=(text, 92.0, ["orange"]),
        ) as read_frame, patch("app.vision.ocr.time.sleep") as sleep:
            worker.run()

        self.assertEqual(read_frame.call_count, 1)
        sleep.assert_not_called()
        self.assertEqual(results[0][1:], (119, None, True))

    def test_worker_fast_accepts_actionable_cooldown_at_moderate_confidence(self):
        text = "You already visited this house! Come back in 123s"
        worker = OCRWorker({"x": 0, "y": 0, "width": 430, "height": 88})
        results = []
        worker.recognized.connect(lambda *result: results.append(result))

        with patch.object(
            OCRService,
            "read_region_frame",
            return_value=(text, 54.0, ["orange"]),
        ) as read_frame, patch("app.vision.ocr.time.sleep") as sleep:
            worker.run()

        read_frame.assert_called_once()
        sleep.assert_not_called()
        self.assertEqual(results[0][1:], (123, None, True))

    def test_worker_confirms_message_when_two_of_three_frames_match(self):
        text = "You already visited this house! Come back in 119"
        worker = OCRWorker({"x": 0, "y": 0, "width": 592, "height": 63})
        results = []
        worker.recognized.connect(lambda *result: results.append(result))

        with patch.object(
            OCRService,
            "read_region_frame",
            side_effect=[
                ("Unrecognized text", 72.0, []),
                (text, 70.0, ["orange"]),
                (text, 72.0, ["orange"]),
            ],
        ) as read_frame, patch("app.vision.ocr.time.sleep"):
            worker.run()

        self.assertEqual(read_frame.call_count, 3)
        self.assertEqual(results[0][1:], (119, None, True))

    def test_worker_accepts_clear_cooldown_from_later_frame(self):
        text = "You can Trick or Treat again in 163 seconds"
        worker = OCRWorker({"x": 0, "y": 0, "width": 517, "height": 116})
        results = []
        worker.recognized.connect(lambda *result: results.append(result))

        with patch.object(
            OCRService,
            "read_region_frame",
            side_effect=[
                ("SAFE ZONE PROTECTED", 92.0, []),
                (text, 42.0, []),
                ("", 0.0, []),
            ],
        ) as read_frame, patch("app.vision.ocr.time.sleep"):
            worker.run()

        self.assertEqual(read_frame.call_count, 3)
        self.assertEqual(
            results,
            [("You can Trick or Treat again in 163 seconds", 163, None, True)],
        )

    def test_worker_accepts_brief_treat_or_trick_message_from_one_clear_frame(self):
        messages = (
            (
                "You got +8 Candies! You now have: 401 Candies!",
                {"type": "received", "amount": 8, "total": 401},
            ),
            (
                "SAFERZONE\nPROTECTED\n"
                "Youlgot +5 Candies! You now have: 452 Candies!",
                {"type": "received", "amount": 5, "total": 452},
            ),
            (
                "4 Candies were stolen! You now have: 393 Candies!",
                {"type": "stolen", "amount": 4, "total": 393},
            ),
        )
        for text, expected_event in messages:
            with self.subTest(event=expected_event["type"]):
                worker = OCRWorker({"x": 0, "y": 0, "width": 500, "height": 48})
                results = []
                worker.recognized.connect(lambda *result: results.append(result))

                with patch.object(
                    OCRService,
                    "read_region_frame",
                    side_effect=[
                        (text, 72.0),
                        ("SAFE ZONE PROTECTED", 92.0),
                        ("", 0.0),
                    ],
                ) as read_frame, patch("app.vision.ocr.time.sleep") as sleep:
                    worker.run()

                read_frame.assert_called_once()
                sleep.assert_not_called()
                self.assertEqual(
                    results,
                    [
                        (
                            (
                                f"You got +{expected_event['amount']} Candies! "
                                f"You now have: {expected_event['total']} Candies!"
                                if expected_event["type"] == "received"
                                else (
                                    f"{expected_event['amount']} Candies were stolen! "
                                    f"You now have: {expected_event['total']} Candies!"
                                )
                            ),
                            -1,
                            expected_event,
                            True,
                        )
                    ],
                )

    def test_worker_stops_without_emitting_when_monitoring_is_interrupted(self):
        worker = OCRWorker({"x": 0, "y": 0, "width": 500, "height": 48})
        results = []
        worker.recognized.connect(lambda *result: results.append(result))

        with patch.object(
            worker,
            "isInterruptionRequested",
            side_effect=[False, True],
        ), patch.object(OCRService, "read_region_frame") as read_frame:
            worker.run()

        read_frame.assert_called_once()
        self.assertEqual(results, [])

    def test_worker_accepts_one_confident_visited_message_amid_unstable_frames(self):
        text = "You already visited this house! Come back in 158"
        worker = OCRWorker({"x": 0, "y": 0, "width": 430, "height": 88})
        results = []
        worker.recognized.connect(lambda *result: results.append(result))

        with patch.object(
            OCRService,
            "read_region_frame",
            side_effect=[
                (text, 42.0, ["orange"]),
                ("SAFE ZONE PROTECTED", 90.0, []),
                ("", 0.0, []),
            ],
        ), patch("app.vision.ocr.time.sleep"):
            worker.run()

        self.assertEqual(
            results[0],
            ("You already visited this house! Come back in 158s", 158, None, True),
        )

    def test_worker_uses_configured_frame_interval(self):
        worker = OCRWorker(
            {"x": 0, "y": 0, "width": 100, "height": 48},
            frame_interval=0.3,
        )

        with patch.object(
            OCRService,
            "read_region_frame",
            return_value=("", 0.0, []),
        ), patch("app.vision.ocr.time.sleep") as sleep:
            worker.run()

        self.assertEqual(sleep.call_args_list, [call(0.3), call(0.3)])


if __name__ == "__main__":
    unittest.main()