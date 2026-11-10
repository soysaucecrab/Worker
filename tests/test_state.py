"""state.json 읽기·쓰기 테스트 (SPEC 9장)."""
from __future__ import annotations

from state import State, load_state, save_state


def test_round_trip(tmp_path):
    p = tmp_path / "state.json"
    st = State(expanded={"카카오톡", "GroovSide"}, selected="카카오톡/학생회 집행부",
               seen={"카카오톡/학생회 집행부": 123.5})
    save_state(st, p)
    back = load_state(p)
    assert back.expanded == {"카카오톡", "GroovSide"}
    assert back.selected == "카카오톡/학생회 집행부"
    assert back.seen["카카오톡/학생회 집행부"] == 123.5


def test_missing_file_is_empty(tmp_path):
    st = load_state(tmp_path / "nope.json")
    assert st.expanded == set()
    assert st.selected is None
    assert st.seen == {}


def test_corrupt_file_is_empty(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json", encoding="utf-8")
    st = load_state(p)
    assert st.expanded == set()


def test_toggle():
    st = State()
    assert st.toggle("카카오톡") is True
    assert st.is_expanded("카카오톡")
    assert st.toggle("카카오톡") is False
    assert not st.is_expanded("카카오톡")


def test_mark_seen_keeps_latest():
    st = State()
    st.mark_seen("n", 100.0)
    st.mark_seen("n", 50.0)   # 더 과거면 무시
    assert st.seen["n"] == 100.0
    st.mark_seen("n", 200.0)
    assert st.seen["n"] == 200.0


def test_save_is_atomic_and_no_raise(tmp_path):
    # 디렉터리가 없어도 만들어 쓰고, 오류를 밖으로 던지지 않는다.
    p = tmp_path / "sub" / "state.json"
    save_state(State(selected="전체"), p)
    assert load_state(p).selected == "전체"
