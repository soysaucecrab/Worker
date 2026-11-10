"""매칭 엔진·보낸 사람 추출 테스트 (SPEC 7.3, 6.3.3, 13장)."""
from __future__ import annotations

import re

from config import Child, Match, Rule, Source
from matching import OTHER, build_fields, classify, extract_sender, match_child


def rule(key, pat):
    return Rule(key, pat, None)


def rx(key, pat):
    return Rule(key, pat, re.compile(pat, re.IGNORECASE))


def _sources():
    slack = Source(name="Slack", bundle_ids=["com.tinyspeck.slackmacgap"], sender="title")
    kakao = Source(
        name="카카오톡", bundle_ids=["com.kakao.KakaoTalkMac"], only_children=True,
        sender="body_prefix",
        children=[Child("학생회 집행부", Match([rule("title", "학생회 집행부")])),
                  Child("랩 동기방", Match([rule("title", "랩 동기방")]))],
    )
    groov = Source(
        name="GroovSide", bundle_ids=["com.example.groovside"], only_children=False,
        children=[Child("Instagram", Match([rule("any", "instagram")])),
                  Child("X", Match([rx("any", r"\bx\.com\b|\btwitter\b")]))],
    )
    insta = Source(name="Instagram", bundle_ids=["com.google.Chrome", "com.apple.Safari.WebApp.*"],
                   match=Match([rule("any", "instagram")]))
    return [slack, kakao, groov, insta]


def test_source_match_by_bundle():
    a = classify(_sources(), "com.tinyspeck.slackmacgap", "Alice", "", "안녕")
    assert a.source == "Slack"
    assert a.child is None
    assert a.sender == "Alice"   # title 규칙
    assert not a.drop


def test_unknown_source_is_none():
    a = classify(_sources(), "com.unknown.app", "x", "", "y")
    assert a.source is None
    assert not a.drop


def test_child_match_and_body_prefix_sender():
    a = classify(_sources(), "com.kakao.KakaoTalkMac", "학생회 집행부", "", "김민지: 회의록 올렸어요")
    assert a.source == "카카오톡"
    assert a.child == "학생회 집행부"
    assert a.sender == "김민지"
    assert a.body == "회의록 올렸어요"   # body_prefix로 보낸 사람 뗀 나머지


def test_only_children_drops_unmatched():
    a = classify(_sources(), "com.kakao.KakaoTalkMac", "다른 방", "", "홍길동: 안녕")
    assert a.source == "카카오톡"
    assert a.drop is True
    assert a.child is None


def test_other_child_when_not_only_children():
    a = classify(_sources(), "com.example.groovside", "", "", "알 수 없는 알림")
    assert a.source == "GroovSide"
    assert a.child == OTHER
    assert not a.drop


def test_regex_child_match():
    a = classify(_sources(), "com.example.groovside", "", "", "x.com 에 새 글")
    assert a.child == "X"
    b = classify(_sources(), "com.example.groovside", "", "", "instagram 좋아요")
    assert b.child == "Instagram"


def test_source_match_rule_required():
    # Chrome 번들이지만 'instagram'이 없으면 Instagram 소스로 안 걸린다
    a = classify(_sources(), "com.google.Chrome", "github", "", "PR 리뷰 요청")
    assert a.source is None
    b = classify(_sources(), "com.google.Chrome", "instagram", "", "DM 왔어요")
    assert b.source == "Instagram"


def test_wildcard_bundle():
    a = classify(_sources(), "com.apple.Safari.WebApp.ABC123", "instagram", "", "알림")
    assert a.source == "Instagram"


def test_and_condition():
    src = Source(name="S", bundle_ids=["com.x"],
                 children=[Child("C", Match([rule("title", "A"), rule("body", "B")]))],
                 only_children=True)
    assert classify([src], "com.x", "A코너", "", "B내용").child == "C"
    assert classify([src], "com.x", "A코너", "", "다른내용").drop is True  # body 조건 불충족


def test_first_child_wins():
    src = Source(name="S", bundle_ids=["com.x"], only_children=True,
                 children=[Child("First", Match([rule("any", "공통")])),
                           Child("Second", Match([rule("any", "공통")]))])
    assert classify([src], "com.x", "공통 알림", "", "").child == "First"


def test_extract_sender_rules():
    s_title = Source(name="t", sender="title")
    s_sub = Source(name="s", sender="subtitle")
    s_none = Source(name="n", sender="none")
    s_bp = Source(name="b", sender="body_prefix")
    assert extract_sender(s_title, "T", "S", "B") == ("T", "B")
    assert extract_sender(s_sub, "T", "S", "B") == ("S", "B")
    assert extract_sender(s_none, "T", "S", "B") == ("", "B")
    assert extract_sender(s_bp, "T", "S", "홍길동: 안녕") == ("홍길동", "안녕")
    # 구분자가 없으면 보낸 사람은 빈 문자열, 본문은 그대로
    assert extract_sender(s_bp, "T", "S", "구분자없음") == ("", "구분자없음")


def test_match_child_ignores_empty_match():
    src = Source(name="S", children=[Child("C", Match())])  # 빈 match는 아무것도 안 걸림
    assert match_child(src, build_fields("무엇이든", "", "")) is None
