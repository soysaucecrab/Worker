"""알림 → 소스·하위 항목 매칭과 보낸 사람 추출 (SPEC 7.3, 6.3.3).

순수 로직만 둔다 (수집기·Textual과 분리). 알림 하나를 받아 어느 소스/하위 항목에
속하는지, 버릴지, 보낸 사람이 누구인지 정한다.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from config import Source

OTHER = "기타"  # only_children=false 소스에서 어떤 하위 항목에도 안 걸린 알림을 모으는 자동 하위 항목


def build_fields(title: str, subtitle: str, body: str, thread: str = "") -> dict[str, str]:
    """match 규칙이 보는 필드 묶음 (7.3). any는 제목·부제목·본문을 이어 붙인 것."""
    return {"title": title, "subtitle": subtitle, "body": body, "thread": thread,
            "any": " ".join(x for x in (title, subtitle, body) if x)}


def source_owns(src: Source, bundle_id: str, fields: dict[str, str]) -> bool:
    """알림이 이 소스에 속하는지 (번들 ID 와일드카드 + 소스 단위 match)."""
    if not any(fnmatch.fnmatch(bundle_id, pat) for pat in src.bundle_ids):
        return False
    return (not src.match) or src.match.matches(fields)


def match_source(sources: list[Source], bundle_id: str, fields: dict[str, str]) -> Source | None:
    """위에서부터 처음 맞는 소스. iCampus 소스는 알림 매칭 대상이 아니다."""
    for s in sources:
        if s.is_icampus:
            continue
        if source_owns(s, bundle_id, fields):
            return s
    return None


def match_child(src: Source, fields: dict[str, str]) -> str | None:
    """소스 안에서 위에서부터 match가 맞는 첫 하위 항목 이름."""
    for c in src.children:
        if c.match and c.match.matches(fields):
            return c.name
    return None


def extract_sender(src: Source, title: str, subtitle: str, body: str) -> tuple[str, str]:
    """(보낸 사람, 메시지 본문). body_prefix는 본문을 sender_sep에서 나눈다 (7.3).

    뽑지 못하면 보낸 사람은 "" (표시할 때 제목으로 대체)."""
    if src.sender == "title":
        return title, body
    if src.sender == "subtitle":
        return subtitle, body
    if src.sender == "body_prefix":
        idx = body.find(src.sender_sep)
        if idx >= 0:
            return body[:idx], body[idx + len(src.sender_sep):]
        return "", body
    return "", body  # none


@dataclass
class Assignment:
    source: str | None      # 소스 이름 (없으면 None)
    child: str | None       # 하위 항목 이름 (없으면 None)
    sender: str
    body: str               # body_prefix면 보낸 사람을 뗀 나머지
    drop: bool = False       # only_children에서 하위 매칭 실패 → 버림


def classify(sources: list[Source], bundle_id: str, title: str, subtitle: str,
             body: str, thread: str = "") -> Assignment:
    """알림을 소스·하위 항목으로 분류한다 (7.3 + 6.3.3).

    - 소스에 안 걸리면 source=None (호출 쪽이 show_other_apps로 처리).
    - 하위 항목에 안 걸리면: only_children이면 버리고, 하위 항목이 있는 소스면 '기타'로,
      하위 항목이 없는 리프 소스면 child=None.
    """
    fields = build_fields(title, subtitle, body, thread)
    src = match_source(sources, bundle_id, fields)
    if src is None:
        return Assignment(None, None, "", body)

    sender, msg_body = extract_sender(src, title, subtitle, body)
    child = match_child(src, fields)
    if child is None:
        if src.only_children:
            return Assignment(src.name, None, sender, msg_body, drop=True)
        if src.children:
            child = OTHER
    return Assignment(src.name, child, sender, msg_body)
