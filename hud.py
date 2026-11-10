#!/usr/bin/env python3
"""hud — 알림·일정·할 일·iCampus·Claude Code를 한 화면에 보여주는 터미널 대시보드.

M1: 앱 트리(전체/부모/리프) 탐색, Enter 펼치기·접기와 열기, 알림 패널 선택 연동,
키 안내 줄, state.json. 일정·할 일·Claude 패널은 v0 로직을 유지한다.
"""
from __future__ import annotations

import argparse
import copy
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from rich.console import Console
from rich.table import Table as RichTable
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import DataTable, Static

from collectors import (
    EventKitReader,
    NotificationReader,
    Snapshot,
    clear_finished_claude_sessions,
    demo_snapshot,
    dump_raw,
    list_notification_apps,
    match_counts,
    notification_db_path,
    open_bundle,
    open_source,
    open_url,
    read_badge,
    read_claude_sessions,
)
from config import CLAUDE_STATE_DIR, Config, ConfigError, load_config
from icampus import IcampusClient, check_auth
from matching import OTHER, bundle_match
from state import State, load_state, save_state
from tree import ALL_KEY, Node, build_tree

WEEKDAYS = "월화수목금토일"
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
CAL_BUNDLE = "com.apple.iCal"
REMINDERS_BUNDLE = "com.apple.reminders"


# ───────────────────────── 수집 스레드 ─────────────────────────

class Collector(threading.Thread):
    def __init__(self, cfg: Config, demo: bool):
        super().__init__(daemon=True)
        self.cfg, self.demo = cfg, demo
        self._lock = threading.Lock()
        self._snap = Snapshot()
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.ek = None if demo else EventKitReader()
        self.ek_ready = False
        self.notif = None if demo else NotificationReader()
        self.icampus = None
        if not demo and cfg.icampus.enabled:
            isrc = next((s for s in cfg.sources if s.is_icampus), None)
            if isrc is not None:
                self.icampus = IcampusClient(cfg.icampus, isrc.name)

    def snapshot(self) -> Snapshot:
        with self._lock:
            return copy.copy(self._snap)

    def refresh(self):
        self.wake.set()

    def _init_eventkit(self):
        try:
            self.ek.ensure_access()
        except Exception as e:
            self.ek.import_error = f"EventKit 초기화 실패: {e}"
            self.ek.ek = None
        self.ek_ready = True
        self.wake.set()

    def run(self):
        if self.demo:
            while not self.stopped.is_set():
                with self._lock:
                    self._snap = demo_snapshot(self.cfg.sources)
                self.wake.wait(1.0)
                self.wake.clear()
            return

        threading.Thread(target=self._init_eventkit, daemon=True).start()
        cfg = self.cfg
        next_slow = 0.0
        events, todos = [], []
        ic_items, ic_anns = [], []
        errors: dict[str, str] = {}
        while not self.stopped.is_set():
            forced = self.wake.is_set()
            self.wake.clear()
            now = time.monotonic()

            badges = {s.name: read_badge(s.process) for s in cfg.sources}
            notifs, err = self.notif.read(cfg.sources, cfg.notification_hours, cfg.show_other_apps)
            errors["notifications"] = err or ""
            claude, err = read_claude_sessions()
            errors["claude"] = err if (err and not claude) else ""

            if forced or now >= next_slow:
                if self.ek_ready:
                    if forced and self.ek.store is not None:
                        self.ek._new_store()
                    try:
                        events, err = self.ek.events(cfg.calendar_days, cfg.exclude_calendars)
                        errors["events"] = err or ""
                        todos, err = self.ek.reminders(cfg.exclude_reminder_lists)
                        errors["todos"] = err or ""
                    except Exception as e:
                        errors["events"] = errors["todos"] = f"EventKit 오류: {e}"
                    next_slow = now + 60
                else:
                    msg = "캘린더·미리알림 권한 확인 중… 처음 실행이면 권한 요청 창에서 '허용'을 누르세요."
                    errors["events"] = errors["todos"] = msg
                    next_slow = now + 1

            if self.icampus is not None:
                ic_items, ic_anns, ierr = self.icampus.poll(now)
                errors["icampus"] = ierr or ""

            with self._lock:
                self._snap = Snapshot(badges, notifs + ic_anns, events, todos, claude,
                                      {k: v for k, v in errors.items() if v}, time.time(),
                                      icampus=ic_items)
            self.wake.wait(1.5)


# ───────────────────────── 표시 도우미 ─────────────────────────

def fmt_dur(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return f"{s}초"
    if s < 3600:
        return f"{s // 60}분"
    if s < 86400:
        h, m = divmod(s // 60, 60)
        return f"{h}시간 {m}분" if m else f"{h}시간"
    return f"{s // 86400}일"


def fmt_ago(dt: datetime, now: datetime) -> str:
    sec = (now - dt).total_seconds()
    return "방금" if sec < 60 else f"{fmt_dur(sec).split(' ')[0]} 전"


def day_label(d: datetime, now: datetime) -> str:
    delta = (d.date() - now.date()).days
    if delta == 0:
        return "오늘"
    if delta == 1:
        return "내일"
    if delta == -1:
        return "어제"
    return f"{d.month}/{d.day} ({WEEKDAYS[d.weekday()]})"


def time_cell(when: datetime, now: datetime) -> Text:
    if when.date() == now.date():
        return Text(f"{when:%H:%M}")
    if (now.date() - when.date()).days == 1:
        return Text(f"어제{when:%H:%M}", style="dim")
    return Text(f"{when.month}/{when.day}", style="dim")


def fit(text: Text | str, width: int) -> Text:
    t = text if isinstance(text, Text) else Text(text)
    t = t.copy()
    t.truncate(max(4, width), overflow="ellipsis")
    return t


def bar(ratio: float, width: int = 14) -> Text:
    ratio = min(max(ratio, 0.0), 1.0)
    filled = round(ratio * width)
    t = Text()
    t.append("█" * filled, style="green")
    t.append("░" * (width - filled), style="dim")
    t.append(f" {int(ratio * 100):>3}%", style="bold")
    return t


def is_overdue(todo, now: datetime) -> bool:
    if todo.due is None:
        return False
    return todo.due < now if todo.has_time else todo.due.date() < now.date()


# ───────────────────────── 위젯 ─────────────────────────

class Table(DataTable):
    """포커스가 있을 때만 커서를 보여주는 표."""

    def __init__(self, **kw):
        super().__init__(show_header=False, cursor_type="row", zebra_stripes=False, **kw)
        self.show_cursor = False
        self._keys: list[str] = []
        self._sig: tuple | None = None   # 마지막으로 그린 내용의 지문 (안 바뀌면 다시 안 그림)

    def on_focus(self):
        self.show_cursor = True

    def on_blur(self):
        self.show_cursor = False

    def replace_rows(self, rows: list[tuple[str, list, int]], cursor_key: str | None = None):
        """(key, cells, height) 목록으로 내용을 바꾸되 커서/스크롤을 유지한다.

        cursor_key를 주면 그 키의 줄로 커서를 옮긴다 (앱 트리의 선택 유지용).

        내용(키·셀 글자·높이·cursor_key)이 지난번과 같으면 표를 건드리지 않는다.
        1초마다 호출돼도 바뀐 게 없으면 다시 그리지 않아 스크롤·커서가 유지된다.
        """
        sig = (cursor_key, tuple((k, h, tuple(str(c) for c in cells)) for k, cells, h in rows))
        if sig == self._sig:
            return
        self._sig = sig

        prev_idx = self.cursor_row
        prev_key = self._keys[prev_idx] if 0 <= prev_idx < len(self._keys) else None
        scroll = self.scroll_y
        self.clear()
        self._keys = []
        for key, cells, height in rows:
            self.add_row(*cells, key=key, height=height)
            self._keys.append(key)
        if not self._keys:
            return
        target = cursor_key if cursor_key is not None else prev_key
        if target in self._keys:
            idx = self._keys.index(target)
        else:
            idx = min(max(prev_idx, 0), len(self._keys) - 1)
        self.move_cursor(row=idx, scroll=False)
        # clear() 직후엔 스크롤 가능 높이가 아직 0이라 scroll_to가 안 먹는다.
        # 레이아웃이 끝난 뒤(call_after_refresh) 복원한다.
        if scroll:
            self.call_after_refresh(self.scroll_to, y=scroll, animate=False)


class Panel(Vertical):
    def __init__(self, title: str, table_id: str, **kw):
        super().__init__(classes="panel", **kw)
        self.base_title = title
        self.border_title = title
        self.table_id = table_id

    def compose(self) -> ComposeResult:
        yield Table(id=self.table_id)
        yield Static("", classes="hint")

    @property
    def table(self) -> Table:
        return self.query_one(Table)

    def set_hint(self, msg: str):
        hint = self.query_one(".hint", Static)
        hint.update(msg)
        hint.display = bool(msg)

    def set_count(self, n: int | None):
        self.border_title = f"{self.base_title} {n}" if n else self.base_title


# ───────────────────────── 앱 ─────────────────────────

class HudApp(App):
    TITLE = "hud"
    AUTO_FOCUS = "#sources"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { layout: vertical; }
    #topbar { height: 1; padding: 0 1; }
    #attention { height: auto; max-height: 3; padding: 0 1; }
    #keyhint { height: 1; padding: 0 1; }
    .panel {
        border: round $foreground 30%;
        border-title-color: $foreground;
        border-title-style: bold;
        height: 1fr;
        padding: 0 0;
    }
    .panel:focus-within { border: round $accent; }
    .panel DataTable { background: transparent; height: auto; max-height: 100%; scrollbar-size-vertical: 1; }
    .hint { color: $warning; padding: 0 1; display: none; height: auto; }
    #sources-panel { height: auto; max-height: 14; }
    #middle { height: 1fr; }
    #left { width: 40%; min-width: 36; max-width: 56; }
    #right { width: 1fr; }
    #claude-panel { height: auto; max-height: 12; }
    #icampus-panel { height: auto; max-height: 9; }
    #notif-panel { height: 1fr; }
    """

    BINDINGS = [
        Binding("q", "quit", "종료"),
        Binding("r", "refresh", "새로고침"),
        Binding("c", "clear_claude", "세션 정리"),
    ]

    def __init__(self, cfg: Config, demo: bool = False):
        super().__init__()
        self.cfg = cfg
        self.demo = demo
        self.collector = Collector(cfg, demo)
        self.by_name = {s.name: s for s in cfg.sources}
        self.tick = 0
        self._tree_nodes: list[Node] = []
        self._node_by_key: dict[str, Node] = {}
        self._icampus_items: list = []
        if demo:
            self.state = State(expanded={"GroovSide"}, selected="GroovSide/Instagram")
        else:
            self.state = load_state()
        self.selected = self.state.selected or ALL_KEY

    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        yield Static(id="attention")
        yield Panel("앱", "sources", id="sources-panel")
        with Horizontal(id="middle"):
            with Vertical(id="left"):
                yield Panel("일정", "calendar", id="cal-panel")
                yield Panel("할 일", "todos", id="todo-panel")
            with Vertical(id="right"):
                yield Panel("Claude Code", "claude", id="claude-panel")
                yield Panel("iCampus", "icampus", id="icampus-panel")
                yield Panel("알림", "notifs", id="notif-panel")
        yield Static(id="keyhint")

    def on_mount(self):
        try:
            self.theme = self.cfg.theme
        except Exception:
            pass
        cols = {
            "sources": [("name", 18), ("count", 4), ("ago", 7), ("msg", None)],
            "calendar": [("time", 13), ("title", None)],
            "todos": [("mark", 1), ("due", 11), ("title", None)],
            "claude": [("state", 11), ("proj", 18), ("detail", None), ("age", 8)],
            "icampus": [("left", 11), ("kind", 4), ("course", 11), ("title", None),
                        ("status", 10), ("due", 11)],
            "notifs": [("time", 8), ("src", 10), ("msg", None)],
        }
        for tid, spec in cols.items():
            t = self.query_one(f"#{tid}", Table)
            for key, width in spec:
                t.add_column(key, key=key, width=width)
        self.query_one("#keyhint", Static).update(self._keyhint())
        if not self.cfg.icampus.enabled:
            self.query_one("#icampus-panel", Panel).display = False
        self.collector.start()
        self.set_interval(1.0, self.render_all)
        self.render_all()

    @staticmethod
    def _keyhint() -> Text:
        t = Text()
        for key, label in [("↑↓", "이동"), ("Enter", "펼치기·접기 / 열기"), ("Tab", "패널 이동"),
                           ("r", "새로고침"), ("c", "세션 정리"), ("q", "종료")]:
            t.append(f"  {key} ", style="bold")
            t.append(label, style="dim")
        return t

    # ── 동작 ──
    def action_refresh(self):
        self.collector.refresh()
        self.notify("새로고침했어요", timeout=1.5)

    def action_clear_claude(self):
        n = clear_finished_claude_sessions()
        self.notify(f"끝난 세션 {n}개를 정리했어요" if n else "정리할 세션이 없어요", timeout=2)
        self.collector.refresh()

    def _now(self) -> datetime:
        return datetime.now().astimezone()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        if event.data_table.id != "sources":
            return
        key = str(event.row_key.value or "")
        if key and key != self.selected:
            self.selected = key
            self.state.selected = key
            if not self.demo:
                save_state(self.state)
        try:
            self.render_notifs(self.collector.snapshot(), self._now())
        except Exception:
            pass

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        tid = event.data_table.id
        key = str(event.row_key.value or "")
        if tid == "sources":
            self._sources_enter(key)
        elif tid == "notifs":
            self._notifs_enter(key)
        elif tid == "icampus":
            self._icampus_enter(key)
        elif tid == "calendar":
            open_bundle(CAL_BUNDLE)
        elif tid == "todos":
            open_bundle(REMINDERS_BUNDLE)

    def _sources_enter(self, key: str):
        node = self._node_by_key.get(key)
        if node is None:
            return
        if node.is_parent:
            self.state.toggle(node.key)
            if not self.demo:
                save_state(self.state)
            snap, now = self.collector.snapshot(), self._now()
            self.render_sources(snap, now)
            self.render_notifs(snap, now)
        elif node.kind == "icampus":
            open_url(self.cfg.icampus.base_url)
        elif node.kind != "all":
            if node.url:
                open_url(node.url)
            elif node.source:
                open_source(node.source)

    def _notifs_enter(self, key: str):
        node = self._node_by_key.get(self.selected)
        notifs = node.notifs if node else []
        try:
            i = int(key.split(":")[1])
        except (IndexError, ValueError):
            return
        if not (0 <= i < len(notifs)):
            return
        n = notifs[i]
        src = self.by_name.get(n.source or "")
        url = None
        if src:
            url = next((c.url for c in src.children if c.name == n.child and c.url), None) or src.url
        if url:
            open_url(url)
        elif src:
            open_source(src)

    def _icampus_enter(self, key: str):
        try:
            i = int(key.split(":")[1])
        except (IndexError, ValueError):
            return
        if 0 <= i < len(self._icampus_items):
            item = self._icampus_items[i]
            open_url(item.html_url or self.cfg.icampus.base_url)

    # ── 그리기 ──
    def render_all(self):
        if not self.is_running or not self.screen.is_mounted:
            return
        self.tick += 1
        snap = self.collector.snapshot()
        now = self._now()
        steps = [
            ("#sources-panel", lambda: self.render_sources(snap, now)),  # 먼저: topbar 안읽음이 트리 수에 의존
            (None, lambda: self.render_topbar(snap, now)),
            (None, lambda: self.render_attention(snap, now)),
            ("#cal-panel", lambda: self.render_calendar(snap, now)),
            ("#todo-panel", lambda: self.render_todos(snap, now)),
            ("#claude-panel", lambda: self.render_claude(snap)),
            ("#icampus-panel", lambda: self.render_icampus(snap, now)),
            ("#notif-panel", lambda: self.render_notifs(snap, now)),
        ]
        for panel_id, step in steps:
            try:
                step()
            except NoMatches:
                return
            except Exception as e:
                if panel_id:
                    try:
                        self.query_one(panel_id, Panel).set_hint(f"표시 오류: {type(e).__name__}: {e}")
                    except NoMatches:
                        return

    def _width(self, tid: str, fixed: int) -> int:
        return self.query_one(f"#{tid}", Table).size.width - fixed

    def render_topbar(self, snap: Snapshot, now: datetime):
        unread = self._tree_nodes[0].new_count if self._tree_nodes else 0
        working = sum(s.state == "working" for s in snap.claude)
        waiting = sum(s.state == "permission" for s in snap.claude)
        left = Text()
        left.append(" hud ", style="bold reverse")
        left.append(f"  {now.month}월 {now.day}일 {WEEKDAYS[now.weekday()]}요일  ")
        left.append(now.strftime("%H:%M:%S"), style="bold")
        right = Text()
        right.append(f"안 읽음 {unread}", style="bold red" if unread else "dim")
        right.append("  │  ", style="dim")
        right.append(f"Claude 작업 {working}", style="green" if working else "dim")
        right.append("  │  ", style="dim")
        right.append(f"승인 대기 {waiting}", style="bold red" if waiting else "dim")
        grid = RichTable.grid(expand=True)
        grid.add_column()
        grid.add_column(justify="right")
        grid.add_row(left, right)
        self.query_one("#topbar", Static).update(grid)

    def render_attention(self, snap: Snapshot, now: datetime):
        ts = time.time()
        lines: list[Text] = []
        for s in snap.claude:  # 1순위: 승인 대기
            if s.state == "permission":
                what = (s.tool and f"{s.tool} 실행 권한") or s.message
                lines.append(Text(f" ⚠ Claude Code 승인 대기 │ {s.project} │ {what} │ {fmt_dur(ts - s.since)}째 ",
                                  style="bold white on red"))
        for ev in snap.events:  # 2순위: 15분 안에 시작
            if ev.all_day:
                continue
            until = (ev.start - now).total_seconds()
            if 0 < until <= 15 * 60:
                loc = f" · {ev.location}" if ev.location else ""
                lines.append(Text(f" ▸ {fmt_dur(until)} 뒤 {ev.title} ({ev.start:%H:%M}{loc}) ",
                                  style="bold black on yellow"))
        for it in snap.icampus:  # 3순위: 6시간 안 마감 미완료
            if it.done or it.due is None:
                continue
            until = (it.due - now).total_seconds()
            if 0 < until <= 6 * 3600:
                lines.append(Text(f" ▸ iCampus {fmt_dur(until)} 뒤 마감 │ {it.course} {it.title} │ {it.status} ",
                                  style="bold black on yellow"))
        overdue = [t for t in snap.todos if is_overdue(t, now)]  # 4순위: 기한 지난 할 일
        if overdue:
            more = f" 외 {len(overdue) - 1}개" if len(overdue) > 1 else ""
            lines.append(Text(f" ! 기한 지난 할 일 │ {overdue[0].title}{more}", style="bold red"))
        for s in snap.claude:  # 5순위: 10분 안에 끝난 세션
            if s.state == "done" and ts - s.since < 600:
                lines.append(Text(f" ✓ Claude Code 응답 완료 │ {s.project} │ {fmt_dur(ts - s.since)} 전",
                                  style="cyan"))
        if not lines:
            nxt = next((e for e in snap.events if not e.all_day and e.start > now), None)
            msg = " 지금 처리할 것 없음"
            if nxt:
                msg += (f" │ 다음 일정 {day_label(nxt.start, now)} {nxt.start:%H:%M} {nxt.title} "
                        f"({fmt_dur((nxt.start - now).total_seconds())} 뒤)")
            lines.append(Text(msg, style="dim"))
        width = self.query_one("#attention", Static).size.width - 2
        for line in lines:
            if line.style and " on " in str(line.style):
                line.pad_right(max(0, width - line.cell_len))
        self.query_one("#attention", Static).update(Text("\n").join(lines[:3]))

    # ── 앱 트리 ──
    def render_sources(self, snap: Snapshot, now: datetime):
        panel = self.query_one("#sources-panel", Panel)
        width = self._width("sources", 18 + 4 + 7)
        nodes = build_tree(self.cfg, snap, self.state)
        self._tree_nodes = nodes
        self._node_by_key = {n.key: n for n in nodes}
        if self.selected not in self._node_by_key:
            self.selected = ALL_KEY
        rows = [(n.key, self._source_cells(n, snap, now, width), 1) for n in nodes]
        panel.table.replace_rows(rows, cursor_key=self.selected)
        panel.set_hint("" if self.cfg.sources else "config.toml의 [[apps]]에 볼 앱을 추가하세요.")

    def _source_cells(self, node: Node, snap: Snapshot, now: datetime, width: int) -> list:
        return [self._name_cell(node), self._count_cell(node),
                self._ago_cell(node, now), self._msg_cell(node, snap, width)]

    def _name_cell(self, node: Node) -> Text:
        t = Text()
        if node.kind == "child":
            t.append("   " + ("└ " if node.is_last_child else "├ "), style="dim")
            t.append(node.name)
        elif node.is_parent:
            t.append(f" {'▾' if node.expanded else '▸'} ", style=node.color)
            t.append(node.name, style=f"bold {node.color}")
        elif node.kind == "all":
            t.append("   ")
            t.append(node.name, style="bold")
        else:
            t.append("   ")
            t.append(node.name, style=f"bold {node.color}")
        return fit(t, 18)

    def _count_cell(self, node: Node) -> Text:
        if node.kind == "source" and not node.is_parent:
            return self._badge_cell(node.badge, node)
        n = node.new_count
        return Text(str(n), style="bold" if n else "dim")

    @staticmethod
    def _badge_cell(badge: str | None, node: Node) -> Text:
        if badge is None:
            return Text("꺼짐" if (node.source and node.source.process) else "—", style="dim")
        if badge == "":
            return Text("0", style="dim")
        if badge.isdigit():
            return Text(badge, style="bold red")
        return Text(badge, style="bold yellow")

    @staticmethod
    def _ago_cell(node: Node, now: datetime) -> Text:
        if node.is_parent and node.expanded:
            return Text("")
        return Text(fmt_ago(node.latest.when, now), style="dim") if node.latest else Text("")

    def _msg_cell(self, node: Node, snap: Snapshot, width: int) -> Text:
        if node.is_parent and node.expanded:
            badge = snap.badges.get(node.name)
            txt = f"지켜보는 {node.child_total}개"
            if badge and badge.isdigit():
                txt += f" │ 앱 전체 안 읽음 {badge}"
            return fit(Text(txt, style="dim"), width)
        if node.latest is None:
            return Text("새 알림 없음", style="dim")
        n = node.latest
        t = Text()
        if node.kind == "all":
            label = n.child or n.source or ""
            if label:
                t.append(label + "  ", style="dim")
        if n.title:
            t.append(n.title, style="bold")
            if n.body:
                t.append("  " + n.body)
        else:
            t.append(n.body)
        return fit(t, width)

    # ── 알림 ──
    def render_notifs(self, snap: Snapshot, now: datetime):
        panel = self.query_one("#notif-panel", Panel)
        node = self._node_by_key.get(self.selected)
        notifs = (node.notifs if node else snap.notifications)[:200]
        if node is None or node.kind == "all":
            panel.border_title = f"알림 {len(notifs)}"
        elif node.kind == "child":
            panel.border_title = f"알림 › {node.source.name} › {node.name} {len(notifs)}"
        else:
            panel.border_title = f"알림 › {node.name} {len(notifs)}"
        detailed = node is None or node.kind == "all" or node.is_parent
        width = self._width("notifs", 8 + 10)
        rows = []
        for i, n in enumerate(notifs):
            tcell = time_cell(n.when, now)
            if detailed:
                label = n.child or n.source or n.bundle_id.split(".")[-1]
                src = self.by_name.get(n.source or "")
                scell = Text(label, style=src.color if src else "dim")
                msg = Text()
                if n.title:
                    msg.append(n.title, style="bold")
                if n.subtitle:
                    msg.append(f" {n.subtitle}", style="dim")
                if n.body:
                    msg.append(("  " if (n.title or n.subtitle) else "") + n.body)
            else:
                scell = Text(n.sender or n.title or "", style="bold")
                msg = Text(n.body or n.title)
            rows.append((f"n:{i}", [tcell, fit(scell, 10), fit(msg, width)], 1))
        panel.table.replace_rows(rows)
        err = snap.errors.get("notifications", "")
        panel.set_hint(err or ("" if rows else f"최근 {self.cfg.notification_hours}시간 동안 받은 알림 없음"))

    # ── iCampus ──
    def render_icampus(self, snap: Snapshot, now: datetime):
        panel = self.query_one("#icampus-panel", Panel)
        width = self._width("icampus", 11 + 4 + 11 + 10 + 11)
        far = datetime.max.replace(tzinfo=now.tzinfo)
        cutoff = now - timedelta(days=self.cfg.icampus.show_done_days)
        visible = [it for it in snap.icampus
                   if not (it.done and it.due is not None and it.due < cutoff)]
        items = sorted(visible, key=lambda it: (it.done, it.due or far))
        self._icampus_items = items
        rows = []
        for i, it in enumerate(items):
            rows.append((f"ic:{i}", [
                self._icampus_left(it, now), Text(it.kind),
                fit(Text(it.course, style="bold"), 11), fit(Text(it.title), width),
                Text(it.status, style="dim" if it.done else "yellow"),
                self._icampus_due(it, now),
            ], 1))
        panel.table.replace_rows(rows)
        incomplete = sum(not it.done for it in items)
        panel.set_count(incomplete)
        if not items:
            panel.set_hint("iCampus 마감 항목 없음")
        else:
            panel.set_hint("")

    @staticmethod
    def _icampus_left(it, now: datetime) -> Text:
        if it.done:
            return Text("✓", style="green")
        if it.due is None:
            return Text("")
        until = (it.due - now).total_seconds()
        if until < 0:
            return Text("지남", style="bold red")
        if until < 24 * 3600:
            style = "bold red" if until < 6 * 3600 else "bold yellow"
            return Text(fmt_dur(until), style=style)
        days = (it.due.date() - now.date()).days
        return Text(f"D-{days}", style="bold" if days <= 2 else "")

    @staticmethod
    def _icampus_due(it, now: datetime) -> Text:
        if it.due is None:
            return Text("")
        delta = (it.due.date() - now.date()).days
        if delta in (0, 1):
            txt = f"{day_label(it.due, now)} {it.due:%H:%M}"
        elif it.due_2359:
            txt = day_label(it.due, now)
        else:
            txt = f"{it.due.month}/{it.due.day} {it.due:%H:%M}"
        return Text(txt, style="dim")

    # ── 일정 (v0 유지) ──
    def render_calendar(self, snap: Snapshot, now: datetime):
        panel = self.query_one("#cal-panel", Panel)
        width = self._width("calendar", 13 + 5)
        rows, last_day = [], None
        next_marked = False
        events = sorted(snap.events, key=lambda e: (e.start, not e.all_day))
        for i, ev in enumerate(events):
            if ev.end < now and ev.start.date() != now.date():
                continue
            d = day_label(ev.start, now)
            if d != last_day:
                rows.append((f"day:{d}", [Text(d, style="bold"), Text("")], 1))
                last_day = d
            title = Text()
            title.append(ev.title)
            if ev.location:
                title.append(f"  {ev.location}", style="dim")
            if ev.all_day:
                rows.append((f"ev:{i}", [Text("종일", style="magenta"), fit(title, width)], 1))
                continue
            when = f"{ev.start:%H:%M}–{ev.end:%H:%M}"
            if ev.end <= now:
                rows.append((f"ev:{i}", [Text(when, style="dim"), fit(Text(ev.title, style="dim"), width)], 1))
            elif ev.start <= now:
                total = (ev.end - ev.start).total_seconds() or 1
                ratio = (now - ev.start).total_seconds() / total
                prog = bar(ratio, 10)
                prog.append(f"  {fmt_dur((ev.end - now).total_seconds())} 남음", style="dim")
                title.stylize("bold green", 0, len(ev.title))
                rows.append((f"ev:{i}", [Text("▶ " + when, style="bold green"),
                                         Text("\n").join([fit(title, width), fit(prog, width)])], 2))
            else:
                until = (ev.start - now).total_seconds()
                style = "bold yellow" if until <= 15 * 60 else ("bold" if not next_marked else "")
                if not next_marked and ev.start.date() == now.date():
                    title.append(f"  {fmt_dur(until)} 뒤", style="yellow")
                next_marked = True
                rows.append((f"ev:{i}", [Text(when, style=style), fit(title, width)], 1))
        panel.table.replace_rows(rows)
        err = snap.errors.get("events", "")
        panel.set_hint(err or ("" if rows else f"앞으로 {self.cfg.calendar_days}일 동안 일정 없음"))

    # ── 할 일 (v0 유지) ──
    def render_todos(self, snap: Snapshot, now: datetime):
        panel = self.query_one("#todo-panel", Panel)
        width = self._width("todos", 1 + 11 + 7)
        far = datetime.max.replace(tzinfo=now.tzinfo)
        todos = sorted(snap.todos, key=lambda t: (t.due is None, t.due or far))
        rows = []
        for i, t in enumerate(todos):
            title = Text()
            title.append(t.title, style="bold" if t.priority == 1 else "")
            if t.list_name:
                title.append(f"  {t.list_name}", style="dim")
            if t.due is None:
                mark, due = Text("·", style="dim"), Text("기한 없음", style="dim")
            else:
                label = day_label(t.due, now) + (f" {t.due:%H:%M}" if t.has_time else "")
                if is_overdue(t, now):
                    mark, due = Text("!", style="bold red"), Text(label, style="red")
                elif t.due.date() == now.date():
                    mark, due = Text("•", style="yellow"), Text(label, style="yellow")
                else:
                    mark, due = Text("·", style="dim"), Text(label)
            rows.append((f"t:{i}", [mark, due, fit(title, width)], 1))
        panel.table.replace_rows(rows)
        panel.set_count(len(todos))
        err = snap.errors.get("todos", "")
        panel.set_hint(err or ("" if rows else "남은 할 일 없음"))

    # ── Claude Code (v0 유지) ──
    def render_claude(self, snap: Snapshot):
        panel = self.query_one("#claude-panel", Panel)
        width = self._width("claude", 11 + 18 + 8 + 8)
        ts = time.time()
        rows = []
        for s in snap.claude:
            age = ts - s.since
            if s.state == "permission":
                state = Text("⚠ 승인 대기", style="bold red")
                detail = Text(f"{s.tool} 실행 권한" if s.tool else s.message, style="red")
                when = Text(fmt_dur(age), style="bold red")
            elif s.state == "working":
                silent = ts - s.updated
                if silent > 15 * 60:
                    state = Text("? 작업 중", style="yellow")
                    detail = Text(f"{fmt_dur(silent)}째 신호 없음 (중단했다면 c로 정리)", style="dim")
                else:
                    state = Text(f"{SPINNER[self.tick % len(SPINNER)]} 작업 중", style="bold green")
                    detail = Text()
                    detail.append(s.tool or "", style="green")
                    if s.prompt:
                        detail.append(("  " if s.tool else "") + s.prompt, style="dim")
                when = Text(fmt_dur(age))
            elif s.state == "done":
                state = Text("✓ 완료", style="cyan")
                detail = Text(s.prompt, style="dim")
                when = Text(f"{fmt_dur(age).split(' ')[0]} 전", style="dim")
            else:
                state = Text("· 대기", style="dim")
                detail = Text(s.prompt or "입력 기다리는 중", style="dim")
                when = Text(f"{fmt_dur(age).split(' ')[0]} 전", style="dim")
            rows.append((f"c:{s.session_id}", [state, fit(Text(s.project, style="bold"), 18),
                                               fit(detail, width), when], 1))
        panel.table.replace_rows(rows)
        panel.set_count(len(rows))
        panel.set_hint(snap.errors.get("claude", "") if not rows else "")

    def on_unmount(self):
        self.collector.stopped.set()
        self.collector.wake.set()


# ───────────────────────── 점검 모드 ─────────────────────────

def doctor(cfg: Config) -> int:
    con = Console()
    ok, bad = "[green]✓[/]", "[red]✗[/]"

    con.rule("설정")
    con.print(f"{ok} {cfg.path or '기본값 (설정 파일 없음)'}")
    if cfg.is_v0:
        con.print("[yellow]·[/] v0 형식으로 읽었어요. SPEC 8장을 보고 v1 형식(version = 1, children 등)으로 "
                  "바꾸면 트리·지정 방 기능을 쓸 수 있어요.")

    con.rule("알림 센터 DB")
    path = notification_db_path()
    apps, err = list_notification_apps()
    if err:
        con.print(f"{bad} {err}")
    else:
        con.print(f"{ok} {path}")
        t = RichTable("번들 ID", "개수", "최근 알림", "config.toml에 연결된 앱", box=None)
        for bundle, n, title in apps[:30]:
            owner = next((s.name for s in cfg.sources
                          if bundle_match(bundle, s.bundle_ids)), "")
            t.add_row(bundle, str(n), (title or "")[:40], owner or "[dim]-[/]")
        con.print(t)
        con.print("[dim]연결 안 된 앱을 보려면 위 번들 ID를 config.toml의 bundle_ids에 넣으세요.[/]")

    con.rule("Dock 배지")
    for s in cfg.sources:
        if s.is_icampus:
            continue
        if not s.process:
            con.print(f"[dim]-[/] {s.name}: process가 비어 있어 배지를 읽지 않음")
            continue
        b = read_badge(s.process)
        state = "앱이 꺼져 있거나 이름이 다름" if b is None else (f"배지 '{b}'" if b else "배지 없음 (0)")
        con.print(f"{ok if b is not None else bad} {s.name} (process='{s.process}'): {state}")

    con.rule("하위 항목 매칭 (최근 7일)")
    counts, err = match_counts(cfg.sources)
    if err:
        con.print(f"{bad} {err}")
    else:
        for s in cfg.sources:
            if s.is_icampus:
                continue
            if s.children:
                targets = [c.name for c in s.children] + ([] if s.only_children else [OTHER])
            else:
                targets = [None]  # 리프 소스: 소스 전체 개수
            for name in targets:
                n = counts.get((s.name, name), 0)
                label = s.name if name is None else f"{s.name} › {name}"
                if n:
                    con.print(f"{ok} {label}: {n}개")
                else:
                    hint = s.bundle_ids[0] if s.bundle_ids else "<번들ID>"
                    con.print(f"{bad} {label}: 매칭되는 알림 없음 — hud --dump {hint} 로 형식을 확인하세요")

    con.rule("캘린더 · 미리알림")
    ek = EventKitReader()
    if ek.ek is None:
        con.print(f"{bad} {ek.import_error}")
    else:
        names = {0: "아직 묻지 않음 (hud를 실행하면 권한 창이 뜸)", 1: "제한됨", 2: "거부됨",
                 3: "전체 접근 허용", 4: "쓰기 전용 (전체 접근으로 바꿔야 함)"}
        for label, ent in (("캘린더", ek.ek.EKEntityTypeEvent), ("미리알림", ek.ek.EKEntityTypeReminder)):
            st = int(ek.ek.EKEventStore.authorizationStatusForEntityType_(ent))
            con.print(f"{ok if st == 3 else bad} {label}: {names.get(st, st)}")

    con.rule("Claude Code")
    settings = Path("~/.claude/settings.json").expanduser()
    installed = settings.exists() and "claude_hook.py" in settings.read_text(encoding="utf-8")
    con.print(f"{ok if installed else bad} ~/.claude/settings.json hook "
              + ("설치됨" if installed else "없음 (python install_hooks.py 실행)"))
    sessions, _ = read_claude_sessions()
    con.print(f"{ok if sessions else '[yellow]·[/]'} 기록된 세션 {len(sessions)}개 ({CLAUDE_STATE_DIR})")

    con.rule("iCampus")
    if not cfg.icampus.enabled:
        con.print("[dim]-[/] 꺼짐 (config.toml의 [icampus] enabled = true 로 켜세요)")
    else:
        probe = check_auth(cfg.icampus)
        if probe.error:
            con.print(f"{bad} {probe.error}")
        elif probe.status == 200:
            con.print(f"{ok} 토큰 유효 — GET {cfg.icampus.base_url}/api/v1/users/self → 200")
        else:
            con.print(f"{bad} 토큰 확인 실패 (HTTP {probe.status})")
    return 0


def dump(bundle_pattern: str, n: int) -> int:
    """그 앱의 최근 알림 원본 필드를 표로 출력 (매칭 규칙을 쓰기 위한 도구, SPEC 11)."""
    con = Console()
    rows, err = dump_raw(bundle_pattern, n)
    if err:
        con.print(f"[red]{err}[/]")
        return 1
    if not rows:
        con.print(f"[yellow]{bundle_pattern} 에 맞는 최근 알림이 없어요. hud --doctor로 번들 ID를 확인하세요.[/]")
        return 0
    t = RichTable("시각", "title", "subtitle", "body (앞 60자)", "thread", "category", box=None)
    for r in rows:
        t.add_row(f"{r.when.astimezone():%m/%d %H:%M}", r.title, r.subtitle,
                  r.body[:60], r.thread, r.category)
    con.print(t)
    con.print("[dim]title/subtitle/body 중 방 이름이 든 칸을 config.toml의 match로, "
              "보낸 사람이 든 칸을 sender로 쓰세요.[/]")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="hud", description="알림·일정·할 일·iCampus·Claude Code를 한 화면에")
    ap.add_argument("--demo", action="store_true", help="가짜 데이터로 화면 미리보기")
    ap.add_argument("--doctor", action="store_true", help="권한과 설정 점검")
    ap.add_argument("--dump", metavar="번들ID", help="그 앱의 최근 알림 원본 필드를 표로 출력")
    ap.add_argument("-n", type=int, default=20, help="--dump에서 보여줄 개수 (기본 20)")
    ap.add_argument("--config", type=Path, help="설정 파일 경로 (기본: ~/.hud/config.toml)")
    args = ap.parse_args()
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"설정 오류: {e}", file=sys.stderr)
        return 1
    if args.dump:
        return dump(args.dump, args.n)
    if args.doctor:
        return doctor(cfg)
    HudApp(cfg, demo=args.demo).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
