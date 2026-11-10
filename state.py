"""`~/.hud/state.json` 읽기·쓰기 (SPEC 9장).

펼친 부모 노드와 마지막으로 고른 노드만 저장한다. hud는 '봤음' 처리를 하지 않으므로
봤음 시각은 저장하지 않는다 (6.3.2). 메시지 본문도 저장하지 않는다.
모두 원자적으로 쓴다 (임시 파일 후 os.replace).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from config import STATE_PATH

VERSION = 1


@dataclass
class State:
    expanded: set[str] = field(default_factory=set)
    selected: str | None = None

    def is_expanded(self, node_key: str) -> bool:
        return node_key in self.expanded

    def toggle(self, node_key: str) -> bool:
        """펼침 상태를 뒤집고 펼쳐졌는지 돌려준다."""
        if node_key in self.expanded:
            self.expanded.discard(node_key)
            return False
        self.expanded.add(node_key)
        return True


def load_state(path: Path | None = None) -> State:
    """상태를 읽는다. 파일이 없거나 깨졌으면 빈 상태를 돌려준다 (예외를 던지지 않음)."""
    p = path or STATE_PATH
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return State()
    if not isinstance(raw, dict):
        return State()
    expanded = raw.get("expanded", [])
    return State(
        expanded=set(e for e in expanded if isinstance(e, str)),
        selected=raw.get("selected") if isinstance(raw.get("selected"), str) else None,
    )


def save_state(state: State, path: Path | None = None) -> None:
    """상태를 원자적으로 쓴다. 실패해도 예외를 던지지 않는다."""
    p = path or STATE_PATH
    data = {
        "version": VERSION,
        "expanded": sorted(state.expanded),
        "selected": state.selected,
    }
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass
