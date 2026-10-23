# 健康提醒

使用 Python 标准库在设定的每日工作时间内弹窗提醒久坐和喝水，无需安装第三方包。

## 配置

编辑 `config.json`：

- `work_periods`：每日生效的时间段，使用 24 小时制 `HH:MM`。开始时间包含在区间内，结束时间不包含；区间不能重叠，也暂不支持跨午夜。
- `reminders`：每项提醒的唯一 `id`、弹窗标题 `title`、提示内容 `message`、间隔 `interval_minutes`，以及关闭前需要点击确认按钮的次数 `dismiss_clicks`（省略时默认 `3`）。

默认时间段为 `09:00-12:00`、`13:30-18:30` 和 `19:00-21:00`。久坐与喝水分别每 60 分钟提醒一次。所有时间段每天生效。

## 运行

在此目录打开终端并运行：

```powershell
python health_reminder.py
```

脚本需保持运行。应用检测到进入工作区间时开始计时；区间外计时清零。因此即使在区间开始之后才启动应用，每项提醒也会等待完整的配置间隔后才首次弹出。提醒到期后计时会自动重新开始；按钮会显示“我知道了（当前次数/需点击次数）”，达到 `dismiss_clicks` 前弹窗不会关闭。多个提醒同时到期时会并排显示在屏幕中央。按 `Ctrl+C` 结束脚本。

## 开机启动

在此目录打开 PowerShell，运行一次以下命令注册 Windows 计划任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_task.ps1
```

任务会在当前用户登录后延迟 30 秒启动程序，并在后台持续运行，不显示命令行窗口。由于提醒需要显示桌面弹窗，任务在用户登录时启动，而不是在登录前的系统启动阶段启动。删除任务：

```powershell
Unregister-ScheduledTask -TaskName HealthReminder -Confirm:$false
```

运行测试：

```powershell
python -m unittest discover -s tests
```