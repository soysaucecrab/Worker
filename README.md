# hud

nvitop처럼 터미널 한 화면에 지금 신경 써야 할 것을 모아 보여주는 macOS 대시보드예요.

- **맨 위 줄**: 지금 당장 처리할 것 (Claude Code 승인 대기, 15분 안에 시작하는 일정, 6시간 안에 마감인 iCampus 항목, 기한 지난 할 일, 방금 끝난 Claude 작업)
- **앱**: 펼치고 접는 트리. 소스(Slack, 카카오톡, Discord, GroovSide, Instagram, iCampus)와 그 하위 항목(방·채널·계정). 카카오톡·Discord는 지정한 방·채널만 보여줘요
- **일정**: 오늘부터 3일치. 진행 중인 일정은 진행 막대와 남은 시간 표시
- **할 일**: 미리알림 앱의 미완료 항목. 기한 지난 것부터
- **Claude Code**: 열려 있는 세션마다 작업 중 / 승인 대기 / 완료 상태
- **iCampus**: 성균관대 LMS(canvas.skku.edu)의 강의·과제·퀴즈 마감 (설정에서 켜야 보임)
- **알림**: 앱 트리에서 고른 대상의 알림만. 소스를 고르면 그 소스, 하위 항목을 고르면 그 방의 알림

## 설치

```bash
cd hud
./install.sh
hud --demo        # 가짜 데이터로 화면부터 확인
```

`uv`가 있으면 그걸로, 없으면 Python 3.11 이상을 찾아서 `~/.hud`에 가상환경을 만들어요. 설치 중에 `~/.claude/settings.json`에 Claude Code hook이 추가되고, 원래 파일은 `settings.json.bak-날짜`로 백업돼요.

## 권한 (처음 한 번)

**1. 전체 디스크 접근 권한 — 알림 미리보기용**

시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한에서 hud를 띄울 터미널 앱을 켜고, 터미널을 완전히 종료한 뒤 다시 여세요.

> 주의: 이 권한은 그 터미널에서 실행되는 **모든 프로그램**에 적용돼요. Claude Code도 같은 터미널에서 돌리면 디스크 전체를 읽을 수 있게 되니까, hud 전용으로 Terminal.app에만 권한을 주고 Claude Code는 다른 터미널(iTerm2, Ghostty 등)에서 쓰는 걸 권장해요.

**2. 캘린더 · 미리알림**

hud를 처음 실행하면 권한 창이 떠요. "허용"을 누르세요. 창이 안 뜨면 Terminal.app에서 한 번 실행해 보세요.

**3. 앱별 알림 설정 (팝업 없이 기록만 남기기)**

시스템 설정 → 알림에서 지켜보는 앱마다: 알림 허용 **켬**, 알림 스타일 **없음**(우측 상단 팝업이 안 떠요), 알림 센터에 표시 **켬**, 앱 아이콘에 배지 표시 **켬**. 카톡에서 알림을 끈 방이나 Discord에서 "@멘션만"으로 둔 채널은 알림이 안 와서 지켜볼 수 없어요. 지켜볼 채널은 "모든 메시지"로 바꾸세요.

**4. Dock 배지**

권한이 필요 없어요.

## 연결 확인

```bash
hud --doctor
```

소스별 연결 상태, 하위 항목별 최근 7일 매칭 개수, 알림 센터에 기록된 앱의 번들 ID 목록을 보여줘요. GroovSide처럼 번들 ID를 모르는 앱은 여기서 찾아 `~/.hud/config.toml`의 `bundle_ids`에 넣으면 돼요.

```bash
hud --dump com.kakao.KakaoTalkMac      # 그 앱의 최근 알림 원본 필드 (title/subtitle/body/thread)
```

카톡·Discord·GroovSide처럼 "지정한 방·채널만" 보려면, `--dump`로 알림이 어느 필드에 방 이름·보낸 사람을 넣는지 확인한 뒤 `config.toml`의 각 하위 항목 `match`와 소스 `sender`를 맞추면 돼요.

## 조작

| 키 | 동작 |
|---|---|
| `↑` `↓` | 포커스된 패널 안에서 줄 이동 |
| `Enter` | 부모 노드면 펼치기·접기, 그 외에는 대상 열기 (앱/URL/대시보드) |
| `Tab` `Shift+Tab` | 패널 이동: 앱 → 일정 → 할 일 → Claude Code → iCampus → 알림 |
| `r` | 새로고침 (캘린더·iCampus도 즉시 다시 읽음) |
| `c` | 끝난 Claude Code 세션 정리 |
| `q` | 종료 |

숫자키와 `←` `→`는 쓰지 않아요. 펼침 상태와 마지막으로 고른 노드는 `~/.hud/state.json`에 저장돼서 다시 실행해도 유지돼요.

항상 띄워 두려면 터미널 창 하나를 hud 전용으로 쓰거나, tmux에서 `tmux split-window -h hud`로 Claude Code 옆에 붙이면 편해요.

## 알아둘 점

- 앱 트리의 "수"는 하위 항목이면 hud에서 마지막으로 본 이후의 새 알림 수, 하위 항목 없는 소스면 Dock 배지예요. 카카오톡 앱 안의 실제 안 읽음 수와는 다를 수 있어요(맥에서 그 값을 얻을 방법이 없어요).
- 알림 피드는 macOS 알림 센터에 남아 있는 것만 보여줘요. 알림 센터에서 지운 알림은 hud에서도 사라져요.
- 카카오톡이나 Slack에서 "알림에 메시지 내용 표시"를 꺼 두면 본문 대신 "새 메시지" 같은 문구만 보여요.
- Claude Code hook은 설치 후 **새로 시작한 세션부터** 적용돼요.
- Claude Code를 Esc로 중단하면 완료 신호가 오지 않아 "작업 중"으로 남을 수 있어요. 15분 동안 신호가 없으면 `?`로 표시되고, `c`로 정리할 수 있어요.
- iCampus(canvas.skku.edu) 마감은 Canvas 개인 액세스 토큰으로 읽어요. canvas.skku.edu → 계정 → 설정 → `+ 새 액세스 토큰`으로 발급한 뒤 키체인에 넣으세요: `security add-generic-password -a "$USER" -s hud.icampus -w` (실행하면 값을 물어봐요). 설정 파일엔 토큰을 넣지 마세요. `[icampus] enabled`로 켜고 끄고, `hud --doctor`로 연결을 확인해요.
- iCampus 패널은 과제·퀴즈·토론 마감과 공지를 보여줘요. **동영상 강의 시청 현황은 표준 API로 못 가져와서**(성균관대 LearningX가 로그인 세션 쿠키로만 주기 때문) 상태 칸이 `—`이고, 동영상 강의 마감 자체가 안 보일 수 있어요.
- `hud --doctor`에서 "iCampus 연결의 CA 인증서를 찾지 못함"이 뜨면, python.org용 `Install Certificates.command`를 한 번 실행하면 돼요.

## 제거

```bash
~/.hud/venv/bin/python ~/.hud/install_hooks.py --uninstall
rm -rf ~/.hud ~/.local/bin/hud
```

## 개발

```bash
uv venv && uv pip install -e ".[dev]"   # 또는: uv pip install textual pytest ruff
python hud.py --demo                     # 가짜 데이터로 실행
pytest -q                                # 테스트
ruff check .                             # 린트
```

## 파일 구성

| 파일 | 역할 |
|---|---|
| `hud.py` | 진입점, 명령줄, Textual 앱과 패널 그리기, `--doctor` |
| `collectors.py` | Dock 배지, 알림 센터 DB, EventKit, Claude 상태 수집, 데모 데이터 |
| `config.py` | 설정 읽기·검증·v0 호환 |
| `icampus.py` | iCampus(Canvas) API 호출·항목 변환·캐시 |
| `state.py` | `state.json` 읽기·쓰기 (펼침·선택·봤음) |
| `tree.py` | 앱 트리 모델 (전체·부모·리프 노드, 새 알림 수) |
| `claude_hook.py` | Claude Code hook. 세션 상태를 `~/.hud/claude/`에 기록 |
| `install_hooks.py` | `~/.claude/settings.json`에 hook 추가·제거 |
| `config.toml` | 감시할 앱 목록과 표시 옵션 (버전 1) |
| `tests/` | 설정·트리·상태·UI 자동 테스트 |
