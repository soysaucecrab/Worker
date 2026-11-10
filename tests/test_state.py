"""state.json 읽기·쓰기 테스트 (SPEC 9장)."""
from __future__ import annotations

from state import State, load_state, save_state


def test_round_trip(tmp_path):
    p = tmp_path / "state.json"
    st = State(expanded={"카카오톡", "GroovSide"}, selected="카카오톡/학생회 집행부")
    save_state(st, p)
    back = load_state(p)
    assert back.expanded == {"카카오톡", "GroovSide"}
    assert back.selected == "카카오톡/학생회 집행부"


def test_seen_not_persisted(tmp_path):
    # 봤음 처리를 하지 않으므로 state.json에 seen 키가 없다 (SPEC 6.3.2).
    import json
    p = tmp_path / "state.json"
    save_state(State(expanded={"a"}, selected="a"), p)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert "seen" not in raw


def test_missing_file_is_empty(tmp_path):
    st = load_state(tmp_path / "nope.json")
    assert st.expanded == set()
    assert st.selected is None


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


def test_save_is_atomic_and_no_raise(tmp_path):
    # 디렉터리가 없어도 만들어 쓰고, 오류를 밖으로 던지지 않는다.
    p = tmp_path / "sub" / "state.json"
    save_state(State(selected="전체"), p)
    assert load_state(p).selected == "전체"
