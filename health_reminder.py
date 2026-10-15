"""Daily health reminders with configurable work periods."""

from __future__ import annotations

import json
import re
import sys
import tkinter as tk
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tkinter import font as tkfont
from typing import Any


TIME_PATTERN = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
POLL_INTERVAL_MS = 500


@dataclass(frozen=True)
class WorkPeriod:
    start: time
    end: time


@dataclass(frozen=True)
class ReminderSpec:
    identifier: str
    title: str
    message: str
    interval_minutes: int


@dataclass(frozen=True)
class AppConfig:
    work_periods: tuple[WorkPeriod, ...]
    reminders: tuple[ReminderSpec, ...]


class ConfigError(ValueError):
    pass


def _parse_time(value: Any, field: str) -> time:
    if not isinstance(value, str) or not TIME_PATTERN.fullmatch(value):
        raise ConfigError(f"{field} 必须使用 HH:MM 格式，例如 09:00")
    return time.fromisoformat(value)


def parse_config(data: Any) -> AppConfig:
    if not isinstance(data, dict):
        raise ConfigError("配置根节点必须是 JSON 对象")

    raw_periods = data.get("work_periods")
    if not isinstance(raw_periods, list) or not raw_periods:
        raise ConfigError("work_periods 必须是至少包含一个时间段的数组")

    periods: list[WorkPeriod] = []
    for index, raw_period in enumerate(raw_periods):
        field = f"work_periods[{index}]"
        if not isinstance(raw_period, dict):
            raise ConfigError(f"{field} 必须是对象")
        start = _parse_time(raw_period.get("start"), f"{field}.start")
        end = _parse_time(raw_period.get("end"), f"{field}.end")
        if start >= end:
            raise ConfigError(f"{field} 的结束时间必须晚于开始时间，暂不支持跨午夜区间")
        periods.append(WorkPeriod(start, end))

    periods.sort(key=lambda period: period.start)
    for previous, current in zip(periods, periods[1:]):
        if current.start < previous.end:
            raise ConfigError("work_periods 不能重叠")

    raw_reminders = data.get("reminders")
    if not isinstance(raw_reminders, list) or not raw_reminders:
        raise ConfigError("reminders 必须是至少包含一项提醒的数组")

    reminders: list[ReminderSpec] = []
    identifiers: set[str] = set()
    for index, raw_reminder in enumerate(raw_reminders):
        field = f"reminders[{index}]"
        if not isinstance(raw_reminder, dict):
            raise ConfigError(f"{field} 必须是对象")

        identifier = raw_reminder.get("id")
        title = raw_reminder.get("title")
        message = raw_reminder.get("message")
        interval = raw_reminder.get("interval_minutes")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ConfigError(f"{field}.id 必须是非空字符串")
        if identifier in identifiers:
            raise ConfigError(f"提醒 id 不能重复：{identifier}")
        if not isinstance(title, str) or not title.strip():
            raise ConfigError(f"{field}.title 必须是非空字符串")
        if not isinstance(message, str) or not message.strip():
            raise ConfigError(f"{field}.message 必须是非空字符串")
        if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
            raise ConfigError(f"{field}.interval_minutes 必须是正整数")

        identifiers.add(identifier)
        reminders.append(ReminderSpec(identifier, title, message, interval))

    return AppConfig(tuple(periods), tuple(reminders))


def load_config(path: Path) -> AppConfig:
    try:
        with path.open("r", encoding="utf-8") as config_file:
            data = json.load(config_file)
    except FileNotFoundError as error:
        raise ConfigError(f"找不到配置文件：{path}") from error
    except json.JSONDecodeError as error:
        raise ConfigError(f"配置文件 JSON 格式错误：{error}") from error
    return parse_config(data)


class ReminderEngine:
    """Track reminder deadlines independently within each work period."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._active_period_key: tuple[date, time, time] | None = None
        self._next_due: dict[str, datetime] = {}
        self._outstanding: set[str] = set()

    def _period_at(self, moment: datetime) -> WorkPeriod | None:
        current_time = moment.time().replace(tzinfo=None)
        for period in self.config.work_periods:
            if period.start <= current_time < period.end:
                return period
        return None

    def poll(self, moment: datetime) -> tuple[bool, list[str]]:
        """Return (period_changed, newly_due_ids) for the supplied local time."""
        period = self._period_at(moment)
        if period is None:
            changed = self._active_period_key is not None
            self._clear_period()
            return changed, []

        period_key = (moment.date(), period.start, period.end)
        changed = period_key != self._active_period_key
        if changed:
            self._active_period_key = period_key
            period_start = datetime.combine(moment.date(), period.start)
            expired_before = moment - timedelta(seconds=2)
            self._next_due = {}
            for reminder in self.config.reminders:
                interval = timedelta(minutes=reminder.interval_minutes)
                next_due = period_start + interval
                if next_due < expired_before:
                    missed_intervals = (expired_before - next_due) // interval + 1
                    next_due += missed_intervals * interval
                self._next_due[reminder.identifier] = next_due
            self._outstanding.clear()

        due_ids: list[str] = []
        for reminder in self.config.reminders:
            identifier = reminder.identifier
            if moment >= self._next_due[identifier] and identifier not in self._outstanding:
                self._outstanding.add(identifier)
                due_ids.append(identifier)
        return changed, due_ids

    def acknowledge(self, identifier: str, moment: datetime) -> bool:
        """Reset one reminder only if its current work period is still active."""
        period = self._period_at(moment)
        if period is None or identifier not in self._outstanding:
            return False

        expected_key = (moment.date(), period.start, period.end)
        if expected_key != self._active_period_key:
            return False

        spec = next(
            reminder for reminder in self.config.reminders if reminder.identifier == identifier
        )
        self._next_due[identifier] = moment + timedelta(minutes=spec.interval_minutes)
        self._outstanding.remove(identifier)
        return True

    def is_active(self, moment: datetime) -> bool:
        period = self._period_at(moment)
        return period is not None and (moment.date(), period.start, period.end) == self._active_period_key

    def _clear_period(self) -> None:
        self._active_period_key = None
        self._next_due.clear()
        self._outstanding.clear()


class ReminderApp:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.engine = ReminderEngine(config)
        self.reminders = {reminder.identifier: reminder for reminder in config.reminders}
        self.queue: deque[str] = deque()
        self.current_window: tk.Toplevel | None = None
        self.current_identifier: str | None = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("健康提醒")
        self.root.after(POLL_INTERVAL_MS, self._poll)

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _poll(self) -> None:
        now = datetime.now()
        period_changed, due_ids = self.engine.poll(now)
        if period_changed:
            self.queue.clear()
            if self.current_window is not None:
                self.current_window.destroy()
                self.current_window = None
                self.current_identifier = None

        self.queue.extend(due_ids)
        self._show_next()
        self.root.after(POLL_INTERVAL_MS, self._poll)

    def _show_next(self) -> None:
        if self.current_window is not None or not self.queue:
            return
        if not self.engine.is_active(datetime.now()):
            return

        identifier = self.queue.popleft()
        reminder = self.reminders[identifier]
        window = tk.Toplevel(self.root)
        window.title(reminder.title)
        window.resizable(False, False)
        window.attributes("-topmost", True)
        window.configure(bg="#F1F6F2")

        is_water_reminder = identifier.lower() in {"water", "drink"} or "喝水" in reminder.title
        accent = "#287F8D" if is_water_reminder else "#358264"
        accent_hover = "#216B78" if is_water_reminder else "#2A6D53"

        screen_width = window.winfo_screenwidth()
        message_font = tkfont.Font(root=window, family="Microsoft YaHei UI", size=14)
        button_font = tkfont.Font(root=window, family="Microsoft YaHei UI", size=11, weight="bold")
        message_width = message_font.measure(reminder.message)
        button_width = button_font.measure("我知道了") + 32
        content_width = max(message_width, button_width, 200)
        max_popup_width = max(280, min(680, screen_width - 48))
        popup_width = min(max_popup_width, max(340, content_width + 72))
        message_wrap = max(1, min(message_width + 1, popup_width - 72))

        outer = tk.Frame(window, bg="#F1F6F2", padx=12, pady=12)
        outer.pack(fill="both", expand=True)
        card = tk.Frame(
            outer,
            bg="#FFFFFF",
            highlightbackground="#DCE8DF",
            highlightthickness=1,
        )
        card.pack(fill="both", expand=True)
        tk.Frame(card, bg=accent, height=4).pack(fill="x")

        content = tk.Frame(card, bg="#FFFFFF", padx=22, pady=20)
        content.pack(fill="both", expand=True)
        message_area = tk.Frame(content, bg="#FFFFFF")
        message_area.pack(fill="x", pady=(0, 20))
        tk.Label(
            message_area,
            text=reminder.message,
            wraplength=message_wrap,
            justify="center",
            anchor="center",
            bg="#FFFFFF",
            fg="#334A41",
            font=message_font,
            padx=0,
            pady=0,
        ).pack(fill="x", expand=True)

        button = tk.Button(
            content,
            text="我知道了",
            command=lambda: self._acknowledge(identifier),
            bg=accent,
            fg="#FFFFFF",
            activebackground=accent_hover,
            activeforeground="#FFFFFF",
            disabledforeground="#FFFFFF",
            font=button_font,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=16,
            pady=10,
            cursor="hand2",
        )
        button.pack(fill="x")
        button.bind("<Enter>", lambda _event: button.configure(bg=accent_hover))
        button.bind("<Leave>", lambda _event: button.configure(bg=accent))
        window.protocol("WM_DELETE_WINDOW", lambda: self._acknowledge(identifier))
        window.update_idletasks()
        window.geometry(f"{popup_width}x{window.winfo_reqheight()}")
        window.update_idletasks()
        x = max(0, (window.winfo_screenwidth() - window.winfo_width()) // 2)
        y = max(0, (window.winfo_screenheight() - window.winfo_height()) // 2)
        window.geometry(f"+{x}+{y}")
        window.bind("<Return>", lambda _event: self._acknowledge(identifier))
        window.bind("<Escape>", lambda _event: self._acknowledge(identifier))
        window.grab_set()
        window.lift()

        self.current_window = window
        self.current_identifier = identifier

    def _acknowledge(self, identifier: str) -> None:
        self.engine.acknowledge(identifier, datetime.now())
        if self.current_window is not None:
            self.current_window.destroy()
        self.current_window = None
        self.current_identifier = None
        self._show_next()


def main() -> int:
    config_path = Path(__file__).with_name("config.json")
    app: ReminderApp | None = None
    try:
        config = load_config(config_path)
        app = ReminderApp(config)
        app.run()
    except KeyboardInterrupt:
        if app is not None:
            app.close()
        print("\n健康提醒已退出。")
        return 0
    except ConfigError as error:
        print(f"配置错误：{error}", file=sys.stderr)
        return 1
    except tk.TclError as error:
        print(f"无法启动提醒窗口：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())