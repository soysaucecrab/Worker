"""Textual pilot UI 테스트 (SPEC 5장, 13장). --demo 데이터로 돈다."""
from __future__ import annotations

import asyncio
from pathlib import Path

import hud
from config import load_config
from hud import HudApp, Table

ROOT = Path(__file__).resolve().parent.parent


def run(coro):
    return asyncio.run(coro)


def make_app() -> HudApp:
    cfg = load_config(ROOT / "config.toml")
    return HudApp(cfg, demo=True)


async def wait_ready(app: HudApp, pilot):
    for _ in range(40):
        await pilot.pause(0.05)
        if app.collector.snapshot().notifications:
            app.render_all()
            await pilot.pause(0.05)
            return
    raise AssertionError("데모 데이터가 채워지지 않음")


def sources(app) -> Table:
    return app.query_one("#sources", Table)


async def move_to(app, pilot, key):
    table = sources(app)
    table.move_cursor(row=table._keys.index(key))
    await pilot.pause(0.05)


def test_initial_focus_on_sources():
    async def inner():
        app = make_app()
        async with app.run_test(size=(140, 42)) as pilot:
            await wait_ready(app, pilot)
            assert app.focused is not None and app.focused.id == "sources"
    run(inner())


def test_enter_collapses_parent():
    async def inner():
        app = make_app()
        async with app.run_test(size=(140, 42)) as pilot:
            await wait_ready(app, pilot)
            # 데모는 GroovSide가 펼쳐진 상태로 시작
            assert "GroovSide/Instagram" in sources(app)._keys
            await move_to(app, pilot, "GroovSide")
            await pilot.press("enter")
            await pilot.pause(0.05)
            assert "GroovSide/Instagram" not in sources(app)._keys
            assert not app.state.is_expanded("GroovSide")
    run(inner())


def test_enter_expands_parent():
    async def inner():
        app = make_app()
        async with app.run_test(size=(140, 42)) as pilot:
            await wait_ready(app, pilot)
            # Discord는 접힌 상태로 시작
            assert "Discord/#운영진" not in sources(app)._keys
            await move_to(app, pilot, "Discord")
            await pilot.press("enter")
            await pilot.pause(0.05)
            assert "Discord/#운영진" in sources(app)._keys
            assert app.state.is_expanded("Discord")
    run(inner())


def test_selection_updates_notif_panel():
    async def inner():
        app = make_app()
        async with app.run_test(size=(140, 42)) as pilot:
            await wait_ready(app, pilot)
            await move_to(app, pilot, "Slack")
            panel = app.query_one("#notif-panel", hud.Panel)
            assert panel.border_title == "알림 › Slack 1"
            await move_to(app, pilot, "전체")
            assert str(panel.border_title).startswith("알림 ")
            assert "›" not in str(panel.border_title)  # 전체는 경로 없음
    run(inner())


def test_enter_opens_leaf_source(monkeypatch):
    async def inner():
        opened = []
        monkeypatch.setattr(hud, "open_source", lambda src: opened.append(src.name))
        app = make_app()
        async with app.run_test(size=(140, 42)) as pilot:
            await wait_ready(app, pilot)
            await move_to(app, pilot, "Slack")
            await pilot.press("enter")
            await pilot.pause(0.05)
            assert opened == ["Slack"]
    run(inner())


def test_enter_on_all_node_does_nothing(monkeypatch):
    async def inner():
        opened = []
        monkeypatch.setattr(hud, "open_source", lambda src: opened.append(src.name))
        monkeypatch.setattr(hud, "open_url", lambda url: opened.append(url))
        app = make_app()
        async with app.run_test(size=(140, 42)) as pilot:
            await wait_ready(app, pilot)
            await move_to(app, pilot, "전체")
            await pilot.press("enter")
            await pilot.pause(0.05)
            assert opened == []
    run(inner())


def test_tab_order():
    async def inner():
        app = make_app()
        async with app.run_test(size=(140, 42)) as pilot:
            await wait_ready(app, pilot)
            order = [app.focused.id]
            for _ in range(5):
                await pilot.press("tab")
                await pilot.pause(0.02)
                order.append(app.focused.id)
            assert order == ["sources", "calendar", "todos", "claude", "icampus", "notifs"]
    run(inner())


def test_number_and_arrow_keys_do_not_open(monkeypatch):
    async def inner():
        opened = []
        monkeypatch.setattr(hud, "open_source", lambda src: opened.append(src.name))
        monkeypatch.setattr(hud, "open_url", lambda url: opened.append(url))
        app = make_app()
        async with app.run_test(size=(140, 42)) as pilot:
            await wait_ready(app, pilot)
            await move_to(app, pilot, "Slack")
            for k in ("1", "2", "9", "left", "right"):
                await pilot.press(k)
                await pilot.pause(0.02)
            assert opened == []
            assert app.focused.id == "sources"
    run(inner())
