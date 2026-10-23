# 健康提醒

一个使用 Python 标准库和 Tkinter 实现的桌面提醒程序。程序在每天配置的工作时段内分别计时，到时显示久坐、喝水等自定义提醒弹窗；不需要安装第三方 Python 包。

## 默认提醒

当前 `config.json` 配置为：

| 工作时段（每天） | 提醒 | 间隔 |
| --- | --- | --- |
| 09:30–12:00 | 久坐提醒 | 60 分钟 |
| 13:30–18:30 | 久坐提醒 | 60 分钟 |
| 19:00–21:00 | 久坐提醒 | 60 分钟 |
| 以上所有时段 | 喝水提醒 | 30 分钟 |

开始时间包含在时段内，结束时间不包含。每个时段单独计时：提醒时点从该时段的开始时间按各自间隔对齐；程序在时段开始后才运行时，已经错过的提醒时点会跳过，等待下一个时点。离开时段后计时清零，下一个时段重新开始。程序约每 0.5 秒检查一次时间。

## 配置

编辑程序旁边的 `config.json`。程序启动时读取该文件；配置错误会显示错误信息并以非零状态退出。

- `work_periods`：每天生效的时间段数组，每项包含 `start` 和 `end`，格式为 24 小时制 `HH:MM`。至少配置一个时段；结束时间必须晚于开始时间，暂不支持跨午夜；时段不能重叠，相邻时段可以。
- `reminders`：至少配置一项提醒。每项包含：
  - `id`：非空且唯一的标识。
  - `title`：弹窗标题，非空字符串。
  - `message`：弹窗提示内容，非空字符串。
  - `interval_minutes`：提醒间隔，正整数。
  - `dismiss_clicks`：关闭弹窗所需的确认次数，正整数；省略时默认为 `3`。

时间格式、字段类型和正整数限制会在启动时校验。配置中的提醒会分别计时，多个提醒同时到期时会同时显示弹窗。

## 运行

需要 Python 3.10 或更高版本。打开项目目录中的 PowerShell 或终端运行：

```powershell
python health_reminder.py
```

程序会在后台持续运行，不显示主窗口；提醒到期时显示置顶弹窗。点击“我知道了”或按 Enter 可确认一次，按钮会显示当前次数，达到该提醒配置的 `dismiss_clicks` 后弹窗关闭。窗口关闭按钮和 Esc 不会关闭提醒；时段结束时，未关闭的提醒弹窗会自动关闭。按 `Ctrl+C` 结束程序。

## 登录后自动启动（Windows）

在项目目录打开 PowerShell，运行一次以下命令，以当前 Windows 用户注册计划任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_task.ps1
```

任务会在当前用户登录后延迟 30 秒启动 Python 程序，不显示命令行窗口，并在用户登录会话中运行，以便显示桌面弹窗。脚本优先使用 Python Launcher（`py.exe`）查找 Python 3 和对应的 `pythonw.exe`；未找到 Launcher 时使用 PATH 中的 `pythonw.exe`。若脚本找不到 Python 或程序文件，会报告错误。

删除计划任务：

```powershell
Unregister-ScheduledTask -TaskName HealthReminder -Confirm:$false
```

## 测试

在项目目录运行：

```powershell
python -m unittest discover -s tests
```
