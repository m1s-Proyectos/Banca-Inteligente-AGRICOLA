import unittest
from asyncio import Event
from datetime import datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.main import app, lifespan
from app.worker.runner import (
    DEFAULT_CALL_WINDOW,
    inside_call_window,
    next_call_window_start,
    parse_call_window,
)


TZ = ZoneInfo("America/El_Salvador")


class ParseCallWindowTests(unittest.TestCase):
    def test_configured_window_is_parsed(self) -> None:
        self.assertEqual(parse_call_window("09:00-17:00"), (time(9, 0), time(17, 0)))
        self.assertEqual(parse_call_window("08:00-18:00"), (time(8, 0), time(18, 0)))

    def test_missing_window_falls_back_to_script_hard_rule(self) -> None:
        default = parse_call_window(None)
        self.assertEqual(default, (time(8, 0), time(18, 0)))
        self.assertEqual(parse_call_window(""), default)
        self.assertEqual(parse_call_window("garbage"), default)
        # Rango invertido o vacío: default, nunca una ventana imposible.
        self.assertEqual(parse_call_window("18:00-08:00"), default)
        self.assertEqual(parse_call_window("08:00-"), default)

    def test_default_window_matches_script(self) -> None:
        self.assertEqual(DEFAULT_CALL_WINDOW, "08:00-18:00")


class InsideCallWindowTests(unittest.TestCase):
    def test_weekday_inside_hours_is_allowed(self) -> None:
        # 2026-09-09 es miércoles.
        self.assertTrue(inside_call_window(datetime(2026, 9, 9, 10, 0, tzinfo=TZ), time(8, 0), time(18, 0)))

    def test_weekday_outside_hours_is_rejected(self) -> None:
        self.assertFalse(inside_call_window(datetime(2026, 9, 9, 7, 30, tzinfo=TZ), time(8, 0), time(18, 0)))
        self.assertFalse(inside_call_window(datetime(2026, 9, 9, 18, 0, tzinfo=TZ), time(8, 0), time(18, 0)))

    def test_weekend_is_rejected_even_inside_hours(self) -> None:
        # 2026-09-12 es sábado.
        self.assertFalse(inside_call_window(datetime(2026, 9, 12, 10, 0, tzinfo=TZ), time(8, 0), time(18, 0)))


class NextCallWindowStartTests(unittest.TestCase):
    def test_after_hours_on_weekday_moves_to_next_day(self) -> None:
        slot = next_call_window_start(datetime(2026, 9, 9, 19, 0, tzinfo=TZ), time(8, 0))
        self.assertEqual(slot, datetime(2026, 9, 10, 8, 0, tzinfo=TZ))

    def test_before_hours_same_day_moves_to_opening(self) -> None:
        slot = next_call_window_start(datetime(2026, 9, 9, 7, 0, tzinfo=TZ), time(8, 0))
        self.assertEqual(slot, datetime(2026, 9, 9, 8, 0, tzinfo=TZ))

    def test_friday_night_skips_to_monday(self) -> None:
        slot = next_call_window_start(datetime(2026, 9, 11, 19, 0, tzinfo=TZ), time(8, 0))
        self.assertEqual(slot, datetime(2026, 9, 14, 8, 0, tzinfo=TZ))

    def test_weekend_skips_to_monday(self) -> None:
        slot = next_call_window_start(datetime(2026, 9, 12, 12, 0, tzinfo=TZ), time(8, 0))
        self.assertEqual(slot, datetime(2026, 9, 14, 8, 0, tzinfo=TZ))


class WorkerLifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_can_share_the_web_process_for_the_mvp(self) -> None:
        original = settings.run_worker_in_web
        started = Event()

        async def fake_worker() -> None:
            started.set()
            await Event().wait()

        settings.run_worker_in_web = True
        try:
            with patch("app.worker.runner.main", fake_worker):
                async with lifespan(app):
                    await started.wait()
        finally:
            settings.run_worker_in_web = original

if __name__ == "__main__":
    unittest.main()
