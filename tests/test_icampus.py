"""iCampus 변환·상태 매핑·캐시·클라이언트 테스트 (SPEC 7.6, 13장).

네트워크는 타지 않는다 — 순수 변환과, fetch를 가짜로 끼운 클라이언트 상태기만 본다.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import icampus
from config import IcampusConfig
from icampus import (
    IcampusClient,
    _next_link,
    is_2359,
    load_cache,
    parse_dt,
    save_cache,
    status_of,
    to_items_and_announcements,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _item(ptype, *, due=None, subs=None, title="제목", course="운영체제", date=None, created=None):
    pl = {"title": title}
    if due is not None:
        pl["due_at"] = due
    if created is not None:
        pl["created_at"] = created
    it = {"plannable_type": ptype, "plannable": pl, "context_name": course,
          "html_url": "https://canvas.skku.edu/x", "submissions": subs if subs is not None else False}
    if date is not None:
        it["plannable_date"] = date
    return it


# ───────── 상태 매핑 ─────────

def test_status_assignment():
    assert status_of("assignment", {"graded": True}) == ("채점 완료", True)
    assert status_of("assignment", {"submitted": True}) == ("제출 완료", True)
    assert status_of("assignment", {"submitted": True, "late": True}) == ("지각 제출", True)
    assert status_of("assignment", {"missing": True}) == ("미제출", False)
    assert status_of("assignment", False) == ("미제출", False)  # submissions가 False로 올 수 있음


def test_status_quiz_discussion():
    assert status_of("quiz", {"submitted": True}) == ("응시 완료", True)
    assert status_of("quiz", {}) == ("미응시", False)
    assert status_of("discussion_topic", {"graded": True}) == ("참여 완료", True)
    assert status_of("discussion_topic", {}) == ("미참여", False)


# ───────── 보조 ─────────

def test_parse_dt():
    assert parse_dt("2026-11-10T14:59:00Z") == datetime(2026, 11, 10, 14, 59, tzinfo=UTC)
    assert parse_dt("2026-11-10T14:59:00+09:00").utcoffset() == timedelta(hours=9)
    assert parse_dt(None) is None
    assert parse_dt("엉터리") is None


def test_is_2359():
    # 23:59 KST 마감
    assert is_2359(datetime(2026, 11, 10, 14, 59, tzinfo=UTC)) is True  # = 23:59 KST
    assert is_2359(datetime(2026, 11, 10, 5, 0, tzinfo=UTC)) is False
    assert is_2359(None) is False


def test_next_link():
    h = ('<https://canvas.skku.edu/api/v1/planner/items?page=1>; rel="current",'
         '<https://canvas.skku.edu/api/v1/planner/items?page=2>; rel="next",'
         '<https://canvas.skku.edu/api/v1/planner/items?page=9>; rel="last"')
    assert _next_link(h) == "https://canvas.skku.edu/api/v1/planner/items?page=2"
    assert _next_link(None) is None
    assert _next_link('<https://x/1>; rel="last"') is None


# ───────── 변환 ─────────

def test_transform_splits_and_filters():
    raw = [
        _item("assignment", due="2026-11-12T05:00:00Z", subs={"missing": True}),            # 미제출, +2일
        _item("assignment", due="2026-11-09T05:00:00Z", subs={"submitted": True, "late": True}),  # 지각 제출, 어제
        _item("quiz", due="2026-11-11T05:00:00Z", subs={"submitted": True}),                # 응시 완료, +1일
        _item("discussion_topic", due="2026-11-13T05:00:00Z", subs={}),                     # 미참여, +3일
        _item("announcement", date="2026-11-09T02:00:00Z", title="성적 공개", course="운영체제"),  # 공지 (어제)
        _item("announcement", date="2026-10-01T02:00:00Z", title="옛날 공지"),               # 14일 지나 제외
        _item("assignment", due="2027-01-20T05:00:00Z", subs={"missing": True}),            # days_ahead 밖 제외
        _item("wiki_page", due="2026-11-12T05:00:00Z"),                                      # 무시
    ]
    items, anns = to_items_and_announcements(raw, NOW, days_ahead=14, source_name="iCampus")
    kinds = sorted(it.kind for it in items)
    assert kinds == ["과제", "과제", "퀴즈", "토론"]
    statuses = {it.title: it.status for it in items}  # 모두 title "제목"이라 상태 집합으로 확인
    assert {it.status for it in items} == {"미제출", "지각 제출", "응시 완료", "미참여"}
    assert len(anns) == 1
    assert anns[0].source == "iCampus"
    assert anns[0].title == "[운영체제] 공지"
    assert anns[0].body == "성적 공개"
    assert statuses  # 사용


def test_transform_due_2359_and_done():
    raw = [_item("assignment", due="2026-11-20T14:59:00Z", subs={"graded": True})]  # 23:59 KST, 완료
    items, _ = to_items_and_announcements(raw, NOW, 14, "iCampus")
    assert len(items) == 1
    assert items[0].done is True
    assert items[0].due_2359 is True
    assert items[0].html_url == "https://canvas.skku.edu/x"


# ───────── 캐시 ─────────

def test_cache_round_trip(tmp_path):
    p = tmp_path / "icampus.json"
    raw = [
        _item("assignment", due="2026-11-12T05:00:00Z", subs={"missing": True}, title="HW5"),
        _item("announcement", date="2026-11-09T02:00:00Z", title="공지내용", course="확통"),
    ]
    items, anns = to_items_and_announcements(raw, NOW, 14, "iCampus")
    save_cache(items, anns, path=p)
    assert p.exists()
    items2, anns2 = load_cache("iCampus", path=p)
    assert [it.title for it in items2] == [it.title for it in items]
    assert items2[0].status == "미제출"
    assert anns2[0].title == "[확통] 공지"
    assert anns2[0].body == "공지내용"


def test_load_cache_missing_is_empty(tmp_path):
    items, anns = load_cache("iCampus", path=tmp_path / "nope.json")
    assert items == [] and anns == []


# ───────── 클라이언트 상태기 (네트워크 없이) ─────────

def _client(monkeypatch, *, token="tok", no_save=True):
    cfg = IcampusConfig(enabled=True, poll_minutes=10, days_ahead=14)
    c = IcampusClient(cfg, "iCampus")
    c._loaded = True  # 실제 캐시 파일을 읽지 않도록 (테스트 격리)
    monkeypatch.setattr(icampus, "get_token", lambda s: token)
    if no_save:
        monkeypatch.setattr(icampus, "save_cache", lambda *a, **k: None)
    return c


def test_client_keeps_cache_on_fetch_error(monkeypatch):
    c = _client(monkeypatch)
    cached = to_items_and_announcements(
        [_item("quiz", due="2026-11-11T05:00:00Z", subs={})], NOW, 14, "iCampus")
    c._items, c._anns = cached
    monkeypatch.setattr(c, "_fetch_planner", lambda token: (None, "서버 오류"))
    items, anns, err = c.poll(1000.0)
    assert err == "서버 오류"
    assert [it.status for it in items] == ["미응시"]   # 캐시 유지
    assert c._next_at > 1000.0                          # 백오프 예약
    assert c._fail == 1


def test_client_no_token(monkeypatch):
    c = _client(monkeypatch, token=None)
    items, anns, err = c.poll(500.0)
    assert "토큰" in err and "keychain" not in err  # 한국어 안내
    assert items == [] and anns == []


def test_client_success_populates(monkeypatch):
    c = _client(monkeypatch)
    raw = [
        _item("assignment", due="2026-11-12T05:00:00Z", subs={"missing": True}, title="HW"),
        _item("announcement", date="2026-11-09T02:00:00Z", title="안내", course="OS"),
    ]
    monkeypatch.setattr(c, "_fetch_planner", lambda token: (raw, None))
    items, anns, err = c.poll(0.0)
    assert err is None
    assert [it.kind for it in items] == ["과제"]
    assert anns[0].title == "[OS] 공지"
    assert c._fail == 0
    assert c._next_at == 0.0 + c.cfg.poll_minutes * 60


def test_client_disabled_returns_empty(monkeypatch):
    cfg = IcampusConfig(enabled=False)
    c = IcampusClient(cfg, "iCampus")
    assert c.poll(0.0) == ([], [], None)
