# hud

macOS 터미널에서 알림(지정한 방·채널만), 일정, 할 일, iCampus 마감, Claude Code 세션 상태를 한 화면에 보여주는 nvitop 스타일 대시보드.

**작업을 시작하기 전에 `SPEC.md`를 읽는다.** 동작·화면·설정에 관한 질문의 답은 SPEC이 기준이다. SPEC과 다르게 구현해야 할 이유가 생기면 먼저 사용자에게 묻는다.

## 현재 상태

- v0 구현이 있다: `hud.py`, `collectors.py`, `claude_hook.py`, `install_hooks.py`, `install.sh`, `config.toml`.
- 다음 작업은 SPEC 14장의 M1부터 순서대로.
- 디자인 참고 이미지: `docs/previews/` (`nav_preview.png`가 v1 목표 화면).

## 기술 스택

- Python 3.11+ (`tomllib`), Textual, Rich, `pyobjc-framework-EventKit`
- HTTP는 표준 라이브러리 `urllib.request`. 새 의존성은 사용자에게 묻고 추가한다.
- 실제 데이터(Dock 배지, 알림 DB, EventKit)는 macOS에서만 동작한다. 그 외 환경에서는 `--demo`와 픽스처 테스트로 확인한다.

## 명령

```bash
uv venv && uv pip install textual pytest ruff     # M1에서 pyproject.toml을 만든 뒤에는: uv pip install -e ".[dev]"
python hud.py --demo                               # 가짜 데이터로 실행
python hud.py --doctor                             # 권한·설정 점검 (맥)
python hud.py --dump com.kakao.KakaoTalkMac        # 알림 원본 필드 확인 (M2에서 추가)
pytest -q
ruff check .
```

`tests/`와 `pyproject.toml`이 없으면 M1의 첫 작업으로 만든다.

## 반드시 지킬 것

- **앱이 죽으면 안 된다.** 수집 함수는 예외를 던지지 않고 `(데이터, 오류 문구 | None)`을 돌려준다. 패널 그리기는 패널 단위로 예외를 잡아 그 패널 안내 줄에 표시한다.
- **UI 스레드에서 I/O 금지.** 서브프로세스, SQLite, EventKit, 네트워크는 수집 스레드에서만. UI는 1초마다 마지막 스냅샷만 그린다.
- **`claude_hook.py`는 stdout에 아무것도 쓰지 않는다.** UserPromptSubmit hook의 stdout은 Claude 컨텍스트에 주입된다. 항상 exit 0, 표준 라이브러리만, 원자적 쓰기.
- **알림 DB는 읽기 전용.** `sqlite3.connect("file:...?mode=ro", uri=True)`. 절대 쓰지 않는다.
- **`~/.claude/settings.json`은 `install_hooks.py`만 수정한다.** 수정 전 백업, 다른 hook 보존, 여러 번 실행해도 결과가 같아야 한다.
- **비밀값은 macOS 키체인에만.** iCampus 토큰(`hud.icampus`), Discord 봇 토큰(`hud.discord`)을 설정 파일, 저장소, 테스트 픽스처, 로그, `--doctor` 출력에 남기지 않는다.
- **메시지 본문을 디스크에 저장하지 않는다.** `state.json`에는 봤음 시각만.
- **네트워크 대상은 iCampus `base_url`과 (켰을 때) Discord API뿐.** 다른 곳으로 요청을 보내야 하면 사용자에게 묻는다.

## 함정 (v0에서 실제로 겪은 것)

- **Rich `Text`의 기본 스타일**: `Text("제목", style="bold")` 뒤에 `append`한 글자도 전부 굵어진다. 여러 스타일을 섞을 때는 `t = Text(); t.append("제목", style="bold"); t.append(" 본문")`.
- **한글 폭**: 자르기·정렬은 `Text.truncate(width, overflow="ellipsis")`와 `cell_len`으로. `len()`이나 문자열 슬라이스로 자르면 한글이 깨지거나 줄이 밀린다.
- **Textual 타이머와 종료**: 종료 중에도 `set_interval` 콜백이 돌 수 있다. 그리기 시작 시 `self.is_running`을 확인하고 `NoMatches`를 잡는다.
- **DataTable 갱신**: `clear()`하면 커서와 스크롤이 처음으로 돌아간다. 다시 채운 뒤 커서 행과 `scroll_y`를 복원한다 (v0의 `Table.replace_rows`).
- **Footer**: 포커스된 DataTable이 가로챈 키(↑↓, Enter)는 기본 `Footer`에 안 보인다. 키 안내는 직접 그린 `Static`으로.
- **EventKit**: macOS 14+에서는 `requestFullAccessTo…WithCompletion:`을 써야 한다. 콜백은 임의 큐에서 오므로 `threading.Event`로 기다리고, 권한을 받은 뒤 store를 새로 만든다.
- **알림 DB 권한**: 전체 디스크 접근 권한이 없으면 SQLite 오류가 아니라 `open()`에서 `PermissionError`가 난다. 먼저 파일을 열어 보고 권한 안내를 돌려준다.
- **이모지 금지**: 터미널마다 폭이 달라 줄이 밀린다. SPEC 12장의 기호만 쓴다.

## 코드 규칙

- 타입 힌트, `dataclass` 사용. 화면에 보이는 문자열은 한국어.
- 오류·빈 상태 문구는 무엇을 하면 고쳐지는지 적는다. 예: `알림을 읽을 수 없음. 시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한에서 이 터미널을 켜세요.`
- 색은 ANSI 색 이름만 (`red`, `yellow`, `green`, `cyan`, `magenta`, `blue`, `dim`). 의미는 SPEC 6장 공통 규칙.
- 순수 로직(매칭, 트리 수 계산, 설정 검증, iCampus 변환)은 Textual과 분리된 모듈에 두고 단위 테스트한다.

## 검증 방법

- 수집·매칭·변환 로직을 바꾸면 픽스처 기반 테스트를 같이 추가한다. 알림 DB 픽스처는 `app`, `record` 테이블과 `plistlib.dumps(..., fmt=FMT_BINARY)`로 만든다.
- 화면을 바꾸면 `--demo` 상태에서 Textual pilot으로 140×42, 100×30 스크린샷을 저장해 직접 확인한다 (`app.save_screenshot()`).
- macOS에서만 확인할 수 있는 것은 직접 확인한 척하지 않는다. 각 작업 끝에 "사용자 맥에서 확인할 것" 목록을 남긴다 (SPEC 13장 형식).

## 작업 방식

- SPEC 14장 마일스톤 순서대로, 한 번에 한 단계. 각 단계는 테스트가 통과하고 실행 가능한 상태로 끝낸다.
- 사용자에게 보이는 동작이 바뀌면 `README.md`를 같이 고친다.
- SPEC 16장 열린 질문에 답이 나오면 SPEC에 기록하고 관련 기본값을 고친다.
- 먼저 물어볼 것: 키 바인딩 변경, 새 의존성, 새 네트워크 대상, `~/.claude/settings.json`에 hook 외의 변경, SPEC 15장 결정 사항과 다른 구현.
