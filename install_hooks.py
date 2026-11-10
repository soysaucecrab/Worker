#!/usr/bin/env python3
"""~/.claude/settings.json에 hud용 hook을 추가(또는 --uninstall로 제거)한다.

- 기존 설정은 settings.json.bak-<시각>으로 백업
- 이미 들어 있는 hud hook은 지우고 새로 넣으므로 여러 번 실행해도 중복되지 않음
- 다른 hook은 건드리지 않음
"""
import json
import shutil
import sys
import time
from pathlib import Path

MARK = "claude_hook.py"

# 이벤트 → [(matcher 또는 None, 상태)]
EVENTS = {
    "SessionStart": [(None, "idle")],
    "UserPromptSubmit": [(None, "working")],
    "PreToolUse": [("*", "working")],
    "PostToolUse": [("*", "working")],
    "Notification": [("permission_prompt", "permission"), ("idle_prompt", "idle")],
    "Stop": [(None, "done")],
    "SessionEnd": [(None, "end")],
}


def strip_ours(groups: list) -> list:
    kept = []
    for g in groups:
        hooks = [h for h in g.get("hooks", []) if MARK not in str(h.get("command", ""))]
        if hooks:
            kept.append({**g, "hooks": hooks})
    return kept


def main() -> int:
    uninstall = "--uninstall" in sys.argv
    hud_home = Path("~/.hud").expanduser()
    python = hud_home / "venv/bin/python"
    script = hud_home / "claude_hook.py"
    settings_path = Path("~/.claude/settings.json").expanduser()
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    settings = {}
    if settings_path.exists():
        text = settings_path.read_text(encoding="utf-8")
        try:
            settings = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError as e:
            print(f"✗ {settings_path}가 올바른 JSON이 아니라서 건드리지 않았어요: {e}")
            return 1
        stamp = time.strftime('%Y%m%d-%H%M%S')
        backup = settings_path.with_name(f"settings.json.bak-{stamp}")
        n = 1
        while backup.exists():
            backup = settings_path.with_name(f"settings.json.bak-{stamp}-{n}")
            n += 1
        shutil.copy2(settings_path, backup)
        print(f"· 기존 설정 백업: {backup}")

    hooks = settings.setdefault("hooks", {})
    for event in list(hooks):
        hooks[event] = strip_ours(hooks[event])
        if not hooks[event]:
            del hooks[event]

    if not uninstall:
        for event, entries in EVENTS.items():
            for matcher, state in entries:
                group = {"hooks": [{"type": "command",
                                    "command": f'"{python}" "{script}" {state}',
                                    "timeout": 5}]}
                if matcher is not None:
                    group = {"matcher": matcher, **group}
                hooks.setdefault(event, []).append(group)
    if not hooks:
        settings.pop("hooks", None)

    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"✓ {settings_path}에서 hud hook을 {'제거' if uninstall else '설치'}했어요.")
    if not uninstall:
        print("  열려 있는 Claude Code 세션은 다시 시작하거나 /hooks에서 변경 사항을 확인해야 적용돼요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
