import unittest
from datetime import datetime
from unittest.mock import patch

import health_reminder
from health_reminder import ConfigError, ReminderEngine, parse_config


def make_config(work_periods=None, reminders=None):
    return parse_config(
        {
            "work_periods": work_periods
            or [
                {"start": "09:00", "end": "12:00"},
                {"start": "13:30", "end": "18:30"},
            ],
            "reminders": reminders
            or [
                {
                    "id": "sit",
                    "title": "久坐提醒",
                    "message": "起来走走",
                    "interval_minutes": 60,
                },
                {
                    "id": "water",
                    "title": "喝水提醒",
                    "message": "喝点水",
                    "interval_minutes": 60,
                },
            ],
        }
    )


class ConfigTests(unittest.TestCase):
    def test_sorts_periods_and_accepts_adjacent_periods(self):
        config = make_config(
            work_periods=[
                {"start": "10:00", "end": "12:00"},
                {"start": "09:00", "end": "10:00"},
            ]
        )

        self.assertEqual(config.work_periods[0].start.hour, 9)
        self.assertEqual(config.work_periods[1].start.hour, 10)

    def test_rejects_overlapping_periods(self):
        with self.assertRaisesRegex(ConfigError, "不能重叠"):
            make_config(
                work_periods=[
                    {"start": "09:00", "end": "11:00"},
                    {"start": "10:30", "end": "12:00"},
                ]
            )

    def test_rejects_invalid_interval(self):
        with self.assertRaisesRegex(ConfigError, "正整数"):
            make_config(
                reminders=[
                    {
                        "id": "sit",
                        "title": "久坐提醒",
                        "message": "起来走走",
                        "interval_minutes": 0,
                    }
                ]
            )


class ReminderEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = ReminderEngine(make_config())

    def test_deadline_is_anchored_to_period_start(self):
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 9, 59, 59)),
            (True, []),
        )
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 10, 0)),
            (False, ["sit", "water"]),
        )

    def test_starting_late_skips_expired_reminders_but_keeps_next_cycle(self):
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 10, 30)),
            (True, []),
        )
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 10, 59, 59)),
            (False, []),
        )
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 11, 0)),
            (False, ["sit", "water"]),
        )

    def test_simultaneous_reminders_are_reported_once_until_acknowledged(self):
        self.engine.poll(datetime(2026, 10, 15, 9, 0))
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 10, 0))[1],
            ["sit", "water"],
        )
        self.assertEqual(self.engine.poll(datetime(2026, 10, 15, 10, 1))[1], [])

    def test_acknowledging_one_reminder_does_not_reset_the_other(self):
        self.engine.poll(datetime(2026, 10, 15, 9, 0))
        self.engine.poll(datetime(2026, 10, 15, 10, 0))
        self.assertTrue(self.engine.acknowledge("sit", datetime(2026, 10, 15, 10, 0)))

        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 11, 0))[1],
            ["sit"],
        )
        self.assertEqual(self.engine.poll(datetime(2026, 10, 15, 11, 1))[1], [])

    def test_leaving_period_clears_timers_and_next_period_restarts_them(self):
        self.engine.poll(datetime(2026, 10, 15, 9, 0))
        self.assertEqual(self.engine.poll(datetime(2026, 10, 15, 12, 0)), (True, []))
        self.assertEqual(self.engine.poll(datetime(2026, 10, 15, 13, 30)), (True, []))
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 14, 30))[1],
            ["sit", "water"],
        )

    def test_deadlines_do_not_fire_at_period_end(self):
        short_period_config = make_config(
            work_periods=[{"start": "09:00", "end": "10:00"}],
            reminders=[
                {
                    "id": "sit",
                    "title": "久坐提醒",
                    "message": "起来走走",
                    "interval_minutes": 60,
                }
            ],
        )
        engine = ReminderEngine(short_period_config)
        self.assertEqual(engine.poll(datetime(2026, 10, 15, 9, 0)), (True, []))
        self.assertEqual(engine.poll(datetime(2026, 10, 15, 10, 0)), (True, []))


class MainTests(unittest.TestCase):
    def test_keyboard_interrupt_closes_app_and_exits_cleanly(self):
        with (
            patch("health_reminder.load_config"),
            patch("health_reminder.ReminderApp") as app_class,
            patch("builtins.print") as print_mock,
        ):
            app = app_class.return_value
            app.run.side_effect = KeyboardInterrupt

            self.assertEqual(health_reminder.main(), 0)

        app.close.assert_called_once_with()
        print_mock.assert_called_once_with("\n健康提醒已退出。")


if __name__ == "__main__":
    unittest.main()