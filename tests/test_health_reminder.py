import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

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
                    "dismiss_clicks": 3,
                },
                {
                    "id": "water",
                    "title": "喝水提醒",
                    "message": "喝点水",
                    "interval_minutes": 60,
                    "dismiss_clicks": 3,
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

    def test_rejects_invalid_dismiss_clicks(self):
        with self.assertRaisesRegex(ConfigError, "dismiss_clicks 必须是正整数"):
            make_config(
                reminders=[
                    {
                        "id": "sit",
                        "title": "久坐提醒",
                        "message": "起来走走",
                        "interval_minutes": 60,
                        "dismiss_clicks": 0,
                    }
                ]
            )


class ReminderEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = ReminderEngine(make_config())

    def test_deadline_is_anchored_to_the_start_of_the_work_period(self):
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 9, 59, 59)),
            (True, []),
        )
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 10, 0)),
            (False, ["sit", "water"]),
        )

    def test_starting_late_skips_elapsed_deadlines_and_keeps_period_cadence(self):
        self.engine = ReminderEngine(
            make_config(
                reminders=[
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
                        "interval_minutes": 30,
                    },
                ]
            )
        )
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 16, 44)),
            (True, []),
        )
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 16, 59, 59)),
            (False, []),
        )
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 17, 0)),
            (False, ["water"]),
        )
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 17, 29, 59)),
            (False, []),
        )
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 17, 30)),
            (False, ["sit", "water"]),
        )

    def test_simultaneous_reminders_restart_their_timers_when_due(self):
        self.engine.poll(datetime(2026, 10, 15, 9, 0))
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 10, 0))[1],
            ["sit", "water"],
        )
        self.assertEqual(self.engine.poll(datetime(2026, 10, 15, 10, 59, 59))[1], [])
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 11, 0))[1],
            ["sit", "water"],
        )

    def test_each_reminder_restarts_its_timer_when_due(self):
        self.engine = ReminderEngine(
            make_config(
                reminders=[
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
                        "interval_minutes": 30,
                    },
                ]
            )
        )
        self.engine.poll(datetime(2026, 10, 15, 9, 0))
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 9, 30))[1],
            ["water"],
        )
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 10, 0))[1],
            ["sit", "water"],
        )
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 10, 30))[1],
            ["water"],
        )

    def test_leaving_period_clears_timers_and_next_period_restarts_them(self):
        self.engine.poll(datetime(2026, 10, 15, 9, 0))
        self.assertEqual(self.engine.poll(datetime(2026, 10, 15, 12, 0)), (True, []))
        self.assertEqual(self.engine.poll(datetime(2026, 10, 15, 13, 30)), (True, []))
        self.assertEqual(
            self.engine.poll(datetime(2026, 10, 15, 14, 30))[1],
            ["sit", "water"],
        )

    def test_schedule_repeats_cleanly_across_seven_days(self):
        reminder_ids = [reminder.identifier for reminder in self.engine.config.reminders]
        first_day = datetime(2026, 10, 12)

        for day_offset in range(7):
            day = first_day + timedelta(days=day_offset)
            self.assertEqual(self.engine.poll(day.replace(hour=9, minute=0)), (True, []))
            self.assertEqual(
                self.engine.poll(day.replace(hour=10, minute=0)),
                (False, reminder_ids),
            )
            self.assertEqual(self.engine.poll(day.replace(hour=12, minute=0)), (True, []))

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


class ReminderAppTests(unittest.TestCase):
    def test_dismissing_popup_does_not_acknowledge_engine(self):
        app = health_reminder.ReminderApp.__new__(health_reminder.ReminderApp)
        window = Mock()
        app.active_windows = {"sit": window}
        app.dismiss_click_counts = {"sit": 0}
        app.engine = Mock()

        app._dismiss("sit", window)

        self.assertEqual(app.active_windows, {})
        app.engine.acknowledge.assert_not_called()

    def test_dismiss_requires_the_configured_number_of_clicks(self):
        app = health_reminder.ReminderApp.__new__(health_reminder.ReminderApp)
        window = Mock()
        button = Mock()
        app.active_windows = {"sit": window}
        app.dismiss_click_counts = {"sit": 0}
        app.reminders = {"sit": Mock(dismiss_clicks=3)}
        app._dismiss_button_text = Mock(return_value="我知道了（1/3）")
        app._dismiss = Mock()

        app._record_dismiss_click("sit", window, button)

        self.assertEqual(app.dismiss_click_counts["sit"], 1)
        button.configure.assert_called_once_with(text="我知道了（1/3）")
        app._dismiss.assert_not_called()

        app.dismiss_click_counts["sit"] = 2
        app._record_dismiss_click("sit", window, button)

        app._dismiss.assert_called_once_with("sit", window)

    def test_poll_keeps_running_while_popup_is_open(self):
        app = health_reminder.ReminderApp.__new__(health_reminder.ReminderApp)
        app.engine = Mock()
        app.engine.poll.return_value = (False, [])
        app.active_windows = {"sit": Mock()}
        app.root = Mock()
        app._show_due = Mock()

        app._poll()

        app.engine.poll.assert_called_once()
        app._show_due.assert_called_once_with([])
        app.root.after.assert_called_once_with(health_reminder.POLL_INTERVAL_MS, app._poll)

    def test_click_for_other_popup_does_not_close_current_popup(self):
        app = health_reminder.ReminderApp.__new__(health_reminder.ReminderApp)
        current_window = Mock()
        stale_window = Mock()
        app.active_windows = {"water": current_window}
        app.dismiss_click_counts = {"water": 0}
        app.reminders = {"sit": Mock(dismiss_clicks=3)}

        app._record_dismiss_click("sit", stale_window, Mock())

        stale_window.destroy.assert_not_called()
        current_window.destroy.assert_not_called()

    def test_popup_positions_center_simultaneous_popups_side_by_side(self):
        positions = health_reminder.popup_positions(
            screen_width=1000,
            screen_height=800,
            popup_sizes=[(300, 200), (300, 200)],
        )

        self.assertEqual(positions, [(188, 300), (512, 300)])


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