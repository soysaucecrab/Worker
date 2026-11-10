"""앱 트리 모델 테스트 (SPEC 6.3, 13장)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from collectors import Notification, Snapshot
from config import Child, Config, IcampusConfig, Match, Source
from state import State
from tree import ALL_KEY, build_tree, node_key

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def _cfg() -> Config:
    return Config(sources=[
        Source(name="Slack", process="Slack", color="magenta"),
        Source(name="카카오톡", color="yellow", only_children=True, children=[
            Child(name="학생회 집행부", match=Match()),
            Child(name="랩 동기방", match=Match()),
        ]),
        Source(name="GroovSide", color="cyan", children=[
            Child(name="Instagram", match=Match()),
            Child(name="X", match=Match()),
        ]),
        Source(name="iCampus", kind="icampus", color="green"),
    ], icampus=IcampusConfig(enabled=True))


def _notif(source, child, mins):
    return Notification(NOW - timedelta(minutes=mins), "demo", source, "제목", "", "본문", child=child)


def _snap() -> Snapshot:
    return Snapshot(
        badges={"Slack": "3", "카카오톡": "12", "GroovSide": "2"},
        notifications=[
            _notif("Slack", None, 4),
            _notif("카카오톡", "학생회 집행부", 1),
            _notif("카카오톡", "학생회 집행부", 6),
            _notif("카카오톡", "랩 동기방", 15),
            _notif("GroovSide", "Instagram", 60),
            _notif("iCampus", None, 3),
            _notif("iCampus", None, 30),
        ],
    )


def test_all_node_first_and_total():
    nodes = build_tree(_cfg(), _snap(), State())
    assert nodes[0].key == ALL_KEY
    # 전체 = Slack(배지 3) + 카톡(2+1=3) + GroovSide(1+0=1) + iCampus(2) = 9
    assert nodes[0].new_count == 9


def test_collapsed_hides_children():
    nodes = build_tree(_cfg(), _snap(), State())  # 아무것도 안 펼침
    keys = [n.key for n in nodes]
    assert node_key("카카오톡", "학생회 집행부") not in keys
    assert "카카오톡" in keys


def test_expanded_shows_children():
    st = State(expanded={"카카오톡"})
    nodes = build_tree(_cfg(), _snap(), st)
    keys = [n.key for n in nodes]
    assert node_key("카카오톡", "학생회 집행부") in keys
    assert node_key("카카오톡", "랩 동기방") in keys
    # GroovSide는 안 펼쳤으니 하위 항목이 안 보인다
    assert node_key("GroovSide", "Instagram") not in keys


def test_parent_count_is_sum_of_children():
    nodes = {n.key: n for n in build_tree(_cfg(), _snap(), State())}
    assert nodes["카카오톡"].new_count == 3   # 학생회 2 + 랩 1
    assert nodes["GroovSide"].new_count == 1  # Instagram 1 + X 0


def test_child_counts_and_branch():
    st = State(expanded={"카카오톡", "GroovSide"})
    nodes = {n.key: n for n in build_tree(_cfg(), _snap(), st)}
    assert nodes[node_key("카카오톡", "학생회 집행부")].new_count == 2
    assert nodes[node_key("카카오톡", "랩 동기방")].new_count == 1
    assert nodes[node_key("카카오톡", "랩 동기방")].is_last_child
    assert not nodes[node_key("카카오톡", "학생회 집행부")].is_last_child
    assert nodes[node_key("GroovSide", "X")].new_count == 0


def test_leaf_badge_and_icampus():
    nodes = {n.key: n for n in build_tree(_cfg(), _snap(), State())}
    assert nodes["Slack"].badge == "3"
    assert nodes["Slack"].new_count == 1   # 알림 1개 (수 칸은 배지로 표시하지만 그룹은 1개)
    assert nodes["iCampus"].kind == "icampus"
    assert nodes["iCampus"].new_count == 2  # 공지 2개


def test_count_value_rules():
    nodes = {n.key: n for n in build_tree(_cfg(), _snap(), State())}
    assert nodes["Slack"].count_value == 3    # 리프: 숫자 배지
    assert nodes["카카오톡"].count_value == 3  # 부모: 하위 합
    assert nodes["iCampus"].count_value == 2


def test_latest_sorted_desc():
    nodes = {n.key: n for n in build_tree(_cfg(), _snap(), State(expanded={"카카오톡"}))}
    latest = nodes[node_key("카카오톡", "학생회 집행부")].latest
    assert latest is not None
    # 1분 전 알림이 6분 전보다 최신
    assert latest.when == NOW - timedelta(minutes=1)
