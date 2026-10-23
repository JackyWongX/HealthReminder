"""Daily health reminders with configurable work periods."""

from __future__ import annotations

import json
import re
import sys
import tkinter as tk
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tkinter import font as tkfont
from typing import Any


TIME_PATTERN = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
POLL_INTERVAL_MS = 500
POPUP_GAP = 24


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
    dismiss_clicks: int


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
        dismiss_clicks = raw_reminder.get("dismiss_clicks", 3)
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
        if (
            isinstance(dismiss_clicks, bool)
            or not isinstance(dismiss_clicks, int)
            or dismiss_clicks <= 0
        ):
            raise ConfigError(f"{field}.dismiss_clicks 必须是正整数")

        identifiers.add(identifier)
        reminders.append(ReminderSpec(identifier, title, message, interval, dismiss_clicks))

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


def enable_high_dpi_awareness() -> None:
    """Prevent Windows from bitmap-scaling Tk windows on high-density displays."""
    if sys.platform != "win32":
        return

    import ctypes

    user32 = ctypes.windll.user32
    context = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    user32.SetProcessDpiAwarenessContext(context)


def popup_positions(
    screen_width: int,
    screen_height: int,
    popup_sizes: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Return centered positions that keep simultaneous popups side by side."""
    rows: list[list[tuple[int, int, int]]] = []
    row_width = 0
    for index, (width, height) in enumerate(popup_sizes):
        extra_width = width if not rows or not rows[-1] else POPUP_GAP + width
        if rows and rows[-1] and row_width + extra_width > screen_width:
            rows.append([])
            row_width = 0
            extra_width = width
        if not rows:
            rows.append([])
        rows[-1].append((index, width, height))
        row_width += extra_width

    row_heights = [max(height for _, _, height in row) for row in rows]
    total_height = sum(row_heights) + POPUP_GAP * (len(rows) - 1)
    y = max(0, (screen_height - total_height) // 2)
    positions: list[tuple[int, int] | None] = [None] * len(popup_sizes)
    for row, row_height in zip(rows, row_heights):
        content_width = sum(width for _, width, _ in row) + POPUP_GAP * (len(row) - 1)
        x = max(0, (screen_width - content_width) // 2)
        for index, width, height in row:
            positions[index] = (x, y + (row_height - height) // 2)
            x += width + POPUP_GAP
        y += row_height + POPUP_GAP

    return [position for position in positions if position is not None]


class ReminderEngine:
    """Track reminder deadlines independently within each work period."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._active_period_key: tuple[date, time, time] | None = None
        self._next_due: dict[str, datetime] = {}

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
            self._next_due = {}
            period_start = datetime.combine(moment.date(), period.start)
            for reminder in self.config.reminders:
                interval = timedelta(minutes=reminder.interval_minutes)
                elapsed_intervals = (moment - period_start) // interval
                self._next_due[reminder.identifier] = period_start + (
                    elapsed_intervals + 1
                ) * interval
        due_ids: list[str] = []
        for reminder in self.config.reminders:
            identifier = reminder.identifier
            if moment >= self._next_due[identifier]:
                due_ids.append(identifier)
                self._next_due[identifier] += timedelta(minutes=reminder.interval_minutes)
        return changed, due_ids

    def is_active(self, moment: datetime) -> bool:
        period = self._period_at(moment)
        return period is not None and (moment.date(), period.start, period.end) == self._active_period_key

    def _clear_period(self) -> None:
        self._active_period_key = None
        self._next_due.clear()


class ReminderApp:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.engine = ReminderEngine(config)
        self.reminders = {reminder.identifier: reminder for reminder in config.reminders}
        self.active_windows: dict[str, tk.Toplevel] = {}
        self.dismiss_click_counts: dict[str, int] = {}

        enable_high_dpi_awareness()
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
            for window in self.active_windows.values():
                window.destroy()
            self.active_windows.clear()
            self.dismiss_click_counts.clear()

        self._show_due(due_ids)
        self.root.after(POLL_INTERVAL_MS, self._poll)

    def _show_due(self, due_ids: list[str]) -> None:
        if not due_ids:
            return
        if not self.engine.is_active(datetime.now()):
            return

        windows = [
            self._create_popup(identifier)
            for identifier in due_ids
            if identifier not in self.active_windows
        ]
        if not windows:
            return

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        positions = popup_positions(
            screen_width,
            screen_height,
            [(window.winfo_width(), window.winfo_height()) for _, window in windows],
        )
        for (identifier, window), (x, y) in zip(windows, positions):
            window.geometry(f"+{x}+{y}")
            window.lift()

    def _create_popup(self, identifier: str) -> tuple[str, tk.Toplevel]:
        reminder = self.reminders[identifier]
        window = tk.Toplevel(self.root)
        self.active_windows[identifier] = window
        self.dismiss_click_counts[identifier] = 0
        window.title(reminder.title)
        window.resizable(False, False)
        window.attributes("-topmost", True)
        window.configure(bg="#F1F6F2")

        is_water_reminder = identifier.lower() in {"water", "drink"} or "喝水" in reminder.title
        accent = "#287F8D" if is_water_reminder else "#358264"
        accent_hover = "#216B78" if is_water_reminder else "#2A6D53"

        scale = max(1.0, window.winfo_fpixels("1i") / 96)
        message_font = tkfont.Font(
            root=window, family="Microsoft YaHei UI", size=round(14 * scale)
        )
        button_font = tkfont.Font(
            root=window, family="Microsoft YaHei UI", size=round(11 * scale), weight="bold"
        )
        message_width = message_font.measure(reminder.message)
        button_width = button_font.measure("我知道了") + 32
        content_width = max(message_width, button_width, 200)
        screen_width = window.winfo_screenwidth()
        max_popup_width = max(round(280 * scale), min(round(680 * scale), screen_width - 48))
        popup_width = min(max_popup_width, max(round(340 * scale), content_width + round(72 * scale)))
        message_wrap = max(1, min(message_width + 1, popup_width - round(72 * scale)))

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
            text=self._dismiss_button_text(identifier),
            command=lambda: self._record_dismiss_click(identifier, window, button),
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
        window.protocol("WM_DELETE_WINDOW", lambda: None)
        window.update_idletasks()
        window.geometry(f"{popup_width}x{window.winfo_reqheight()}")
        window.update_idletasks()
        window.bind("<Return>", lambda _event: self._record_dismiss_click(identifier, window, button))
        window.bind("<Escape>", lambda _event: None)
        return identifier, window

    def _dismiss_button_text(self, identifier: str) -> str:
        clicks = self.dismiss_click_counts[identifier]
        required_clicks = self.reminders[identifier].dismiss_clicks
        return f"我知道了（{clicks}/{required_clicks}）"

    def _record_dismiss_click(
        self,
        identifier: str,
        window: tk.Toplevel,
        button: tk.Button,
    ) -> None:
        if self.active_windows.get(identifier) is not window:
            return

        self.dismiss_click_counts[identifier] += 1
        if self.dismiss_click_counts[identifier] >= self.reminders[identifier].dismiss_clicks:
            self._dismiss(identifier, window)
            return
        button.configure(text=self._dismiss_button_text(identifier))

    def _dismiss(self, identifier: str, window: tk.Toplevel) -> None:
        if self.active_windows.get(identifier) is not window:
            return
        window.destroy()
        del self.active_windows[identifier]
        del self.dismiss_click_counts[identifier]


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