#!/usr/bin/env bash
# hud 설치: ~/.hud 에 가상환경과 파일을 두고, ~/.local/bin/hud 실행 파일을 만든다.
set -euo pipefail

HUD_HOME="$HOME/.hud"
SRC="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"

echo "▸ hud 설치 위치: $HUD_HOME"
mkdir -p "$HUD_HOME" "$BIN"

# Python 3.11 이상 준비 (설정 파일 파싱에 tomllib 필요)
if command -v uv >/dev/null 2>&1; then
  uv venv --quiet --allow-existing --python 3.12 "$HUD_HOME/venv"
  PIP=(uv pip install --quiet --python "$HUD_HOME/venv/bin/python")
else
  PY=""
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
      PY="$(command -v "$c")"; break
    fi
  done
  if [ -z "$PY" ]; then
    echo "✗ Python 3.11 이상이 필요해요. 'brew install uv' 또는 'brew install python@3.12' 후 다시 실행하세요."
    exit 1
  fi
  "$PY" -m venv "$HUD_HOME/venv"
  PIP=("$HUD_HOME/venv/bin/python" -m pip install --quiet --upgrade)
fi

echo "▸ 패키지 설치 (textual, pyobjc EventKit)"
"${PIP[@]}" "textual>=1.0" "pyobjc-framework-EventKit"

cp "$SRC/hud.py" "$SRC/collectors.py" "$SRC/config.py" "$SRC/state.py" "$SRC/tree.py" \
   "$SRC/matching.py" "$SRC/icampus.py" "$SRC/claude_hook.py" "$SRC/install_hooks.py" "$HUD_HOME/"
if [ ! -f "$HUD_HOME/config.toml" ]; then
  cp "$SRC/config.toml" "$HUD_HOME/config.toml"
  echo "▸ 설정 파일 생성: $HUD_HOME/config.toml"
else
  echo "▸ 기존 설정 파일 유지: $HUD_HOME/config.toml"
fi

cat > "$BIN/hud" <<EOF
#!/usr/bin/env bash
exec "$HUD_HOME/venv/bin/python" "$HUD_HOME/hud.py" "\$@"
EOF
chmod +x "$BIN/hud"

echo "▸ Claude Code hook 설치"
"$HUD_HOME/venv/bin/python" "$SRC/install_hooks.py"

echo
echo "✓ 설치 완료"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "  ! $BIN 이 PATH에 없어요. ~/.zshrc에 다음 줄을 추가하세요:"
     echo "      export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
echo "  다음 단계:"
echo "    1) hud --demo    가짜 데이터로 화면 미리보기"
echo "    2) 터미널 앱에 '전체 디스크 접근 권한' 주기 (README 참고) → 터미널 재시작"
echo "    3) hud --doctor  권한 점검 + 알림 앱 번들 ID 확인"
echo "    4) hud"
