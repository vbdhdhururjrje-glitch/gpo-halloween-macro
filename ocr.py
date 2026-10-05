import re
import time

from PIL import Image, ImageOps
from PySide6.QtCore import QThread, Signal

from app.vision.screen_capture import ScreenCapture


COOLDOWN_PATTERN = re.compile(
    r"you\s+can\s+trick\s+or\s+treat\s+again\s+in\s+(\d+)",
    re.IGNORECASE,
)
VISITED_HOUSE_COOLDOWN_PATTERN = re.compile(
    r"you\s+al(?:ready|redy)\s+visited\s+"
    r"(?:(?:this|a)\s+|_+\s*)?house"
    r"(?P<house_mark>[!t]?)\s*,?\s*come\s+back\s+in\s+"
    r"(?P<cooldown>\d+)(?P<unit>[sS]?)",
    re.IGNORECASE,
)
VISITED_HOUSE_COOLDOWN_MAX_SECONDS = 175
CANDY_RECEIVED_PATTERN = re.compile(
    r"you\s+got\s*\+\s*(?P<amount>\d{1,2})\s+cand(?:y|ies)!?\s*"
    r"you\s+now\s+have\s*:\s*(?P<total>\d+)\s+cand(?:y|ies)",
    re.IGNORECASE,
)
CANDY_STOLEN_PATTERN = re.compile(
    r"(?P<amount>\d{1,2})\s+cand(?:y|ies)\s+were\s+stolen!?\s*"
    r"you\s+now\s+have\s*:\s*(?P<total>\d+)\s+cand(?:y|ies)",
    re.IGNORECASE,
)
BASKET_FULL_PATTERN = re.compile(
    r"your\s+candy\s+basket\s+is\s+full!?\s*"
    r"(?P<total>\d+)\s+cand(?:y|ies)\s+reached!?",
    re.IGNORECASE,
)
BASKET_CAPACITY_LIMITS = frozenset({100, 250, 500})
OCR_FRAME_COUNT = 3
OCR_REQUIRED_MATCHES = 2
OCR_CONFIDENCE_THRESHOLD = 50.0
OCR_ACTIONABLE_CONFIDENCE_THRESHOLD = 25.0
OCR_FAST_ACCEPT_CONFIDENCE = 85.0
OCR_FRAME_INTERVAL = 0.05


class OCRService:
    @staticmethod
    def extract_cooldown(text):
        text = text or ""
        matches = []
        for pattern in (COOLDOWN_PATTERN, VISITED_HOUSE_COOLDOWN_PATTERN):
            for match in pattern.finditer(text):
                if pattern is COOLDOWN_PATTERN:
                    cooldown = int(match.group(1))
                else:
                    digits = match.group("cooldown")
                    cooldown = next(
                        (
                            int(digits[:length])
                            for length in range(min(3, len(digits)), 0, -1)
                            if int(digits[:length])
                            <= VISITED_HOUSE_COOLDOWN_MAX_SECONDS
                        ),
                        None,
                    )
                    if cooldown is None:
                        continue
                matches.append((match.start(), cooldown))
        return max(matches, default=(0, None), key=lambda item: item[0])[1]

    @staticmethod
    def extract_candy_event(text):
        events = OCRService.extract_candy_events(text)
        return events[0] if events else None

    @staticmethod
    def _normalize_candy_event_text(text):
        text = (text or "").replace("\\", " ")
        text = re.sub(
            r"\byou[l|1!i]?\s*got\b",
            "You got",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(\bnow\s+have\s*:\s*)[«‹<](?=\d)",
            r"\g<1>4",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(?<![a-z0-9])C[)\]|]?(?=\s*cand(?:y|ies))",
            "1 ",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"(?<=were)[l|1](?=stolen)", " ", text, flags=re.IGNORECASE)
        text = re.sub(
            r"(?<=stolen)[t|1](?=\s*(?:ivoul|ivou|vou|you))",
            " ",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(?<![a-z])(?:ivoul|ivou|vou)(?=now)",
            "you ",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"(?<=now)[s5](?=have)", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"(?<=now)(?=have)", " ", text, flags=re.IGNORECASE)
        return text

    @staticmethod
    def extract_candy_events(text):
        text = OCRService._normalize_candy_event_text(text)
        matches = []
        for event_type, pattern in (
            ("received", CANDY_RECEIVED_PATTERN),
            ("stolen", CANDY_STOLEN_PATTERN),
        ):
            for match in pattern.finditer(text):
                amount = int(match.group("amount"))
                if 1 <= amount <= 15:
                    matches.append((match.start(), {
                        "type": event_type,
                        "amount": amount,
                        "total": int(match.group("total")),
                    }))
        matches.sort(key=lambda item: item[0])
        return [event for _, event in matches]

    @staticmethod
    def extract_basket_full(text):
        match = BASKET_FULL_PATTERN.search(text or "")
        if match is None:
            return None
        total = int(match.group("total"))
        return total if total in BASKET_CAPACITY_LIMITS else None

    @staticmethod
    def read_region(region, tesseract_cmd=None):
        return OCRService.read_region_with_confidence(region, tesseract_cmd)[0]

    @staticmethod
    def read_region_with_confidence(region, tesseract_cmd=None):
        return OCRService.read_region_frame(region, tesseract_cmd)

    @staticmethod
    def read_region_frame(region, tesseract_cmd=None):
        image = ScreenCapture.capture_region(region)
        try:
            import pytesseract
        except ImportError as exc:
            raise RuntimeError("Install the pytesseract package to enable OCR.") from exc

        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd or "tesseract"

        def recognize(source_image, config):
            try:
                result = pytesseract.image_to_data(
                    source_image,
                    config=config,
                    output_type=pytesseract.Output.DICT,
                )
            except pytesseract.TesseractNotFoundError as exc:
                raise RuntimeError(
                    "Tesseract OCR is not installed or is missing from PATH."
                ) from exc
            return OCRService._parse_tesseract_result(result)

        enhanced = ImageOps.autocontrast(image.convert("L")).resize(
            (image.width * 2, image.height * 2),
            Image.Resampling.LANCZOS,
        )
        primary = recognize(enhanced, "--oem 3 --psm 7")
        if primary[1] >= OCR_ACTIONABLE_CONFIDENCE_THRESHOLD and (
            OCRService.extract_cooldown(primary[0]) is not None
            or OCRService.extract_candy_events(primary[0])
            or OCRService.extract_basket_full(primary[0]) is not None
        ):
            return primary

        fallback = recognize(enhanced, "--oem 3 --psm 6")
        return max((primary, fallback), key=lambda sample: sample[1])

    @staticmethod
    def _parse_tesseract_result(result):
        lines = {}
        confidences = []
        recognized_words = result.get("text", [])
        recognized_confidences = result.get("conf", [])
        block_numbers = result.get("block_num", [])
        paragraph_numbers = result.get("par_num", [])
        line_numbers = result.get("line_num", [])
        for index, (word, confidence) in enumerate(
            zip(recognized_words, recognized_confidences)
        ):
            word = word.strip()
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                continue
            if word and confidence >= 0:
                line_key = (
                    block_numbers[index] if index < len(block_numbers) else 0,
                    paragraph_numbers[index] if index < len(paragraph_numbers) else 0,
                    line_numbers[index] if index < len(line_numbers) else 0,
                )
                lines.setdefault(line_key, []).append(word)
                confidences.append(confidence)
        text = "\n".join(" ".join(words) for words in lines.values())
        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return text, confidence

    @staticmethod
    def resolve_stable_samples(
        samples,
        required_matches=OCR_REQUIRED_MATCHES,
        confidence_threshold=OCR_CONFIDENCE_THRESHOLD,
    ):
        observations = {}
        diagnostic_samples = []
        for sample in samples:
            text, confidence = sample[:2]
            text = "\n".join(
                " ".join(line.split())
                for line in (text or "").splitlines()
                if line.strip()
            )
            if not text:
                continue
            diagnostic_samples.append((text, confidence))
            cooldown = OCRService.extract_cooldown(text)
            candy_events = OCRService.extract_candy_events(text)
            basket_total = OCRService.extract_basket_full(text)
            actionable = (
                cooldown is not None
                or bool(candy_events)
                or basket_total is not None
            )
            if not actionable:
                continue
            if confidence < confidence_threshold and not (
                actionable and confidence >= OCR_ACTIONABLE_CONFIDENCE_THRESHOLD
            ):
                continue
            if basket_total is not None:
                candy_event = {"type": "basket_full", "total": basket_total}
            else:
                candy_event = (
                    candy_events[0]
                    if len(candy_events) == 1
                    else candy_events or None
                )
            # Ignore text-color hints entirely and rely on the actual recognized text.
            # This avoids discarding valid door results when OCR colors differ across fonts,
            # themes, or game UI variations.
            if basket_total is not None:
                signature = ("basket_full", basket_total)
            elif cooldown is not None:
                matching_cooldowns = [
                    (key, value)
                    for key, value in observations.items()
                    if key[0] == "cooldown"
                    and abs(value["cooldown"] - cooldown) <= 1
                ]
                signature = (
                    max(matching_cooldowns, key=lambda item: item[1]["count"])[0]
                    if matching_cooldowns
                    else ("cooldown", cooldown)
                )
            elif candy_event is not None:
                event_signature = (
                    tuple(tuple(sorted(event.items())) for event in candy_events)
                    if candy_events
                    else None
                )
                signature = ("candy", event_signature)
            else:
                signature = (text.casefold(), None)
            observation = observations.setdefault(
                signature,
                {
                    "count": 0,
                    "text": text,
                    "cooldown": cooldown,
                    "candy_event": candy_event if cooldown is None else None,
                    "candy_event_counts": {},
                },
            )
            observation["count"] += 1
            if signature[0] == "cooldown":
                observation["cooldown"] = min(observation["cooldown"], cooldown)
                observation["text"] = text
                if candy_events:
                    event_signature = tuple(
                        tuple(sorted(event.items())) for event in candy_events
                    )
                    event_observation = observation["candy_event_counts"].setdefault(
                        event_signature,
                        {"count": 0, "event": candy_event},
                    )
                    event_observation["count"] += 1

        stable = max(observations.values(), key=lambda item: item["count"], default=None)
        if stable is None or stable["count"] < required_matches:
            text = "\n---\n".join(
                observation["text"]
                for observation in observations.values()
                if observation["text"]
            )
            if not text and diagnostic_samples:
                text = max(diagnostic_samples, key=lambda item: item[1])[0]
            return text, -1, None, False
        stable_candy_event = stable["candy_event"]
        if stable["cooldown"] is not None:
            matching_events = stable["candy_event_counts"].values()
            stable_event = max(
                matching_events,
                key=lambda item: item["count"],
                default=None,
            )
            stable_candy_event = (
                stable_event["event"]
                if stable_event is not None and stable_event["count"] >= required_matches
                else None
            )
        stable_text = stable["text"]
        if stable["cooldown"] is not None:
            messages = []
            for pattern, message_type in (
                (VISITED_HOUSE_COOLDOWN_PATTERN, "visited"),
                (COOLDOWN_PATTERN, "trick_or_treat"),
            ):
                messages.extend(
                    (match.start(), message_type)
                    for match in pattern.finditer(stable["text"])
                )
            latest_message = max(messages, default=(0, "visited"))[1]
            if latest_message == "trick_or_treat":
                stable_text = (
                    "You can Trick or Treat again in "
                    f"{stable['cooldown']} seconds"
                )
            else:
                stable_text = (
                    "You already visited this house! Come back in "
                    f"{stable['cooldown']}s"
                )
        elif (
            isinstance(stable_candy_event, dict)
            and stable_candy_event.get("type") == "basket_full"
        ):
            stable_text = (
                "Your candy basket is full! "
                f"{stable_candy_event['total']} Candies reached!"
            )
        elif stable_candy_event is not None:
            events = (
                stable_candy_event
                if isinstance(stable_candy_event, list)
                else [stable_candy_event]
            )
            if all(event.get("type") in {"received", "stolen"} for event in events):
                stable_text = "\n".join(
                    (
                        f"You got +{event['amount']} Candies! You now have: "
                        f"{event['total']} Candies!"
                        if event["type"] == "received"
                        else f"{event['amount']} Candies were stolen! You now have: "
                        f"{event['total']} Candies!"
                    )
                    for event in events
                )
        return (
            stable_text,
            stable["cooldown"] if stable["cooldown"] is not None else -1,
            stable_candy_event,
            True,
        )


class OCRWorker(QThread):
    recognized = Signal(str, int, object, bool)
    failed = Signal(str)

    def __init__(
        self,
        region,
        parent=None,
        tesseract_cmd=None,
        frame_interval=OCR_FRAME_INTERVAL,
    ):
        super().__init__(parent)
        self._region = dict(region)
        self._tesseract_cmd = tesseract_cmd
        self._frame_interval = max(0.0, float(frame_interval))

    def run(self):
        try:
            samples = []
            for frame in range(OCR_FRAME_COUNT):
                if self.isInterruptionRequested():
                    return
                sample = OCRService.read_region_frame(
                    self._region,
                    self._tesseract_cmd,
                )
                if self.isInterruptionRequested():
                    return
                samples.append(sample)
                if (
                    sample[1] >= OCR_CONFIDENCE_THRESHOLD
                    and OCRService.extract_candy_events(sample[0])
                ):
                    candy_result = OCRService.resolve_stable_samples(
                        [sample],
                        required_matches=1,
                        confidence_threshold=OCR_CONFIDENCE_THRESHOLD,
                    )
                    if candy_result[3] and candy_result[2] is not None:
                        self.recognized.emit(*candy_result)
                        return
                if (
                    frame == 0
                    and sample[1] >= OCR_ACTIONABLE_CONFIDENCE_THRESHOLD
                    and OCRService.extract_cooldown(sample[0]) is not None
                ):
                    cooldown_result = OCRService.resolve_stable_samples(
                        [sample],
                        required_matches=1,
                        confidence_threshold=OCR_ACTIONABLE_CONFIDENCE_THRESHOLD,
                    )
                    if cooldown_result[3] and cooldown_result[1] >= 0:
                        self.recognized.emit(*cooldown_result)
                        return
                if frame == 0 and sample[1] >= OCR_FAST_ACCEPT_CONFIDENCE:
                    fast_result = OCRService.resolve_stable_samples(
                        samples,
                        required_matches=1,
                        confidence_threshold=OCR_FAST_ACCEPT_CONFIDENCE,
                    )
                    if fast_result[3] and (
                        fast_result[1] >= 0 or fast_result[2] is not None
                    ):
                        self.recognized.emit(*fast_result)
                        return
                if frame < OCR_FRAME_COUNT - 1:
                    time.sleep(self._frame_interval)
            if self.isInterruptionRequested():
                return
            result = OCRService.resolve_stable_samples(samples)
            if not result[3]:
                visited_samples = [
                    sample
                    for sample in samples
                    if sample[1] >= OCR_ACTIONABLE_CONFIDENCE_THRESHOLD
                    and VISITED_HOUSE_COOLDOWN_PATTERN.search(sample[0] or "")
                ]
                if visited_samples:
                    result = OCRService.resolve_stable_samples(
                        [max(visited_samples, key=lambda sample: sample[1])],
                        required_matches=1,
                        confidence_threshold=OCR_ACTIONABLE_CONFIDENCE_THRESHOLD,
                    )
            self.recognized.emit(*result)
        except Exception as exc:
            self.failed.emit(str(exc))