"""앱 트리 모델 (SPEC 6.3).

설정(소스·하위 항목)과 스냅샷(알림·배지·iCampus)으로부터 '지금 화면에 보이는 노드'
목록을 만든다. 펼침 상태는 State가 쥐고 있다.

M1 범위: 노드 구조, 노드별 알림 묶기, 수 계산(배지/하위 수/합계), 최근 알림.
'봤음 처리로 수를 0으로 되돌리는 것'(2초 머묾)과 실제 매칭 엔진은 M2에서 붙인다.
지금은 알림에 이미 source/child가 태깅돼 있다고 보고 묶는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from collectors import Notification, Snapshot
from config import Config, Source
from matching import OTHER
from state import State

ALL_KEY = "전체"


def node_key(source: str, child: str | None = None) -> str:
    return f"{source}/{child}" if child else source


@dataclass
class Node:
    key: str
    kind: str                       # all | source | child | icampus
    name: str                       # 표시 이름 (가지 기호 제외)
    color: str = "white"
    depth: int = 0                  # 0 최상위, 1 하위 항목
    is_parent: bool = False
    is_last_child: bool = False     # └ 와 ├ 구분
    expanded: bool = False
    badge: str | None = None        # Dock 배지 (리프 소스 표시 / 부모의 '앱 전체 안 읽음')
    new_count: int = 0              # 새 알림 수 (하위·부모·iCampus·전체)
    child_total: int = 0            # 부모일 때 하위 항목 개수
    latest: Notification | None = None
    notifs: list[Notification] = field(default_factory=list)  # 알림 패널용 (최신순)
    source: Source | None = None    # Enter로 열 대상
    url: str | None = None          # 하위 항목/소스의 url

    @property
    def count_value(self) -> int:
        """최상위 수 합계에 더할 값. 리프 소스는 숫자 배지만, 나머지는 new_count."""
        if self.kind == "source" and not self.is_parent:
            return int(self.badge) if (self.badge or "").isdigit() else 0
        return self.new_count


def _badge_count(badge: str | None) -> int:
    return int(badge) if (badge or "").isdigit() else 0


def build_tree(cfg: Config, snap: Snapshot, state: State) -> list[Node]:
    """보이는 노드를 화면 순서대로 돌려준다. 맨 위는 항상 '전체'."""
    all_notifs = sorted(snap.notifications, key=lambda n: n.when, reverse=True)

    top_nodes: list[Node] = []
    for src in cfg.sources:
        if src.is_icampus:
            top_nodes.append(_icampus_node(src, snap))
        elif src.is_parent:
            top_nodes.append(_parent_node(src, all_notifs, state))
        else:
            top_nodes.append(_leaf_node(src, all_notifs, snap))

    total = sum(n.count_value for n in top_nodes)
    all_node = Node(
        key=ALL_KEY, kind="all", name="전체", new_count=total,
        latest=all_notifs[0] if all_notifs else None, notifs=all_notifs,
    )

    out: list[Node] = [all_node]
    for src, node in zip(cfg.sources, top_nodes):
        out.append(node)
        if node.is_parent and node.expanded:
            out.extend(_child_nodes(src, all_notifs))
    return out


def _by_source(notifs: list[Notification], name: str) -> list[Notification]:
    return [n for n in notifs if n.source == name]


def _by_child(notifs: list[Notification], source: str, child: str) -> list[Notification]:
    return [n for n in notifs if n.source == source and n.child == child]


def _leaf_node(src: Source, notifs: list[Notification], snap: Snapshot) -> Node:
    mine = _by_source(notifs, src.name)
    badge = snap.badges.get(src.name)
    return Node(
        key=src.name, kind="source", name=src.name, color=src.color,
        is_parent=False, badge=badge, new_count=len(mine),
        latest=mine[0] if mine else None, notifs=mine, source=src, url=src.url,
    )


def _parent_node(src: Source, notifs: list[Notification], state: State) -> Node:
    mine = _by_source(notifs, src.name)
    count = sum(1 for n in mine if n.child)  # 하위 항목('기타' 포함)에 걸린 것의 합
    return Node(
        key=src.name, kind="source", name=src.name, color=src.color,
        is_parent=True, expanded=state.is_expanded(src.name),
        badge=None,  # 부모의 badge 칸은 '앱 전체 안 읽음'(Dock)로 메시지 쪽에 쓴다
        new_count=count, child_total=len(src.children),
        latest=mine[0] if mine else None, notifs=mine, source=src, url=src.url,
    )


def _child_names(src: Source, notifs: list[Notification]) -> list[str]:
    """설정된 하위 항목 + (알림이 있을 때만) 자동 '기타' (6.3.3)."""
    names = [c.name for c in src.children]
    if any(n.child == OTHER for n in _by_source(notifs, src.name)):
        names.append(OTHER)
    return names


def _child_nodes(src: Source, notifs: list[Notification]) -> list[Node]:
    names = _child_names(src, notifs)
    by_name = {c.name: c for c in src.children}
    nodes = []
    for i, name in enumerate(names):
        c = by_name.get(name)
        mine = _by_child(notifs, src.name, name)
        nodes.append(Node(
            key=node_key(src.name, name), kind="child", name=name, color=src.color,
            depth=1, is_last_child=(i == len(names) - 1),
            new_count=len(mine), latest=mine[0] if mine else None, notifs=mine,
            source=src, url=(c.url if c else None) or src.url,
        ))
    return nodes


def _icampus_node(src: Source, snap: Snapshot) -> Node:
    # iCampus 소스 노드: 알림 트리에는 '공지'만 흐른다 (SPEC 6.3). 마감 항목은 iCampus 패널.
    anns = sorted((n for n in snap.notifications if n.source == src.name),
                  key=lambda n: n.when, reverse=True)
    return Node(
        key=src.name, kind="icampus", name=src.name, color=src.color,
        is_parent=False, new_count=len(anns),
        latest=anns[0] if anns else None, notifs=anns, source=src, url=src.url,
    )


def parent_badge(cfg: Config, snap: Snapshot, src: Source) -> str | None:
    """부모 노드 펼침 줄의 '앱 전체 안 읽음 M' (Dock 배지)."""
    return snap.badges.get(src.name)
