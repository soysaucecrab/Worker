#!/usr/bin/env python3
"""Claude Code hook → hud 상태 기록.

사용: claude_hook.py <working|permission|idle|done|end>
Claude Code가 stdin으로 넘겨주는 JSON(session_id, cwd, tool_name, message, prompt …)을 읽어
~/.hud/claude/<session_id>.json 에 현재 상태를 적는다.

주의: UserPromptSubmit hook의 stdout은 Claude의 컨텍스트에 들어가므로 절대 아무것도 출력하지 않는다.
어떤 오류가 나도 Claude Code 작업을 막지 않도록 항상 exit 0.
"""
import json
import os
import sys
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("HUD_HOME", "~/.hud")).expanduser() / "claude"


def main() -> None:
    state = sys.argv[1] if len(sys.argv) > 1 else "idle"
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    sid = str(data.get("session_id") or "unknown")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"{sid}.json"

    if state == "end":
        path.unlink(missing_ok=True)
        return

    try:
        prev = json.loads(path.read_text())
    except Exception:
        prev = {}

    event = data.get("hook_event_name", "")
    # 대화 압축(compact)이나 재개 때의 SessionStart는 진행 중인 상태를 덮어쓰지 않음
    if event == "SessionStart" and prev and data.get("source") not in (None, "startup"):
        state = prev.get("state", state)
    # 응답이 끝난 뒤 60초 지나 오는 idle 알림은 "완료" 표시를 유지
    if state == "idle" and prev.get("state") == "done":
        state = "done"

    now = time.time()
    rec = dict(prev)
    rec.update(session_id=sid, cwd=data.get("cwd") or prev.get("cwd", ""), state=state, updated=now)
    if state != prev.get("state"):
        rec["since"] = now
    if event == "UserPromptSubmit":
        rec["prompt"] = " ".join(str(data.get("prompt", "")).split())[:200]
        rec["tool"] = ""
        rec["message"] = ""
    if data.get("tool_name"):
        rec["tool"] = data["tool_name"]
    if event == "Notification":
        rec["message"] = data.get("message", "")
    elif state != "permission":
        rec.pop("message", None)

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False))
    os.replace(tmp, path)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
