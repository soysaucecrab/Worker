# hud 명세서 v1

- 상태: 초안 (2026-11-10)
- 읽는 사람: 구현 담당(Claude Code), 사용자
- 기준 코드: v0 (`hud.py`, `collectors.py`, `claude_hook.py`, `install_hooks.py`, `install.sh`, `config.toml`)
- 참고 이미지: `docs/previews/hud_preview.png`(v0), `icampus_preview.png`, `nav_preview.png` — 저장소에 넣었다면 이 경로에 둔다

## 0. 요약

hud는 nvitop처럼 터미널 한 화면에 "지금 신경 써야 할 것"을 모아 보여주는 macOS용 대시보드다. v0은 앱별 안 읽은 수, 알림 피드, 일정, 할 일, Claude Code 세션 상태를 보여준다. v1에서는 다음을 바꾼다.

| 영역 | v0 | v1 |
|---|---|---|
| 앱 목록 | 평평한 목록, 숫자키 1–9로 앱 열기 | 펼치고 접는 트리, ↑↓와 Enter로만 조작 |
| 카톡·Discord | 앱의 모든 알림 | 지정한 방·채널만 |
| GroovSide | 한 줄 | Instagram / Threads / X 하위 항목 |
| 알림 패널 | 항상 전체 피드 | 앱 트리에서 고른 대상의 알림만 |
| 새 알림 수 | Dock 배지 | 하위 항목은 "hud에서 마지막으로 본 이후" 알림 수 |
| iCampus | 없음 | 마감 패널, 공지, 주의 띠 연동 |
| 화면 팝업 | 언급 없음 | macOS 알림 스타일 '없음'으로 팝업 없이 동작 (설정 안내) |

## 1. 배경과 목표

### 1.1 사용자

한 사람이 여러 채널을 동시에 지켜봐야 한다.

- 연구실 Slack
- 카카오톡: 학생회와 여러 연락. 그중 정해진 방만 중요
- Discord: miseskorea.org 서버 운영
- GroovSide(맥 앱): Instagram, Threads, X 계정을 한 앱에서 관리
- 개인 Instagram (브라우저)
- Claude Code: 여러 세션을 동시에 돌림
- iCampus: 성균관대 LMS(canvas.skku.edu, Canvas 기반)의 강의·과제·퀴즈 마감
- macOS 캘린더, 미리알림

### 1.2 목표

- **G1** 한 화면에서 위의 모든 것을 본다.
- **G2** 카톡과 Discord는 지정한 방·채널만 보이고, 나머지는 hud 어디에도 나오지 않는다.
- **G3** ↑↓, Enter, Tab만으로 탐색한다. 숫자키와 ←→는 쓰지 않는다.
- **G4** macOS 우측 상단 알림 팝업을 끈 상태에서도 동작한다.
- **G5** 데이터는 이 맥 밖으로 나가지 않는다. 예외는 사용자가 켠 iCampus API와 Discord 봇 호출뿐이다.

### 1.3 비목표

- 메시지 답장, 전송, 읽음 처리
- 카카오톡 앱 안의 실제 안 읽음 수 재현 (macOS에서 얻을 방법이 없음)
- macOS 외 운영체제
- GUI 앱이나 데스크톱 위젯 (부록 B에 후보로만 남김)

## 2. 실행 환경

- macOS 15 이상 (Sequoia, Tahoe), Apple Silicon
- Python 3.11 이상 (`tomllib` 사용), Textual 1.0 이상, Rich, `pyobjc-framework-EventKit`
- 터미널: hud 전용으로 Terminal.app 권장 (10장 전체 디스크 접근 권한 참고)
- 화면 크기: 최소 100×30, 권장 140×42 이상

## 3. 용어

| 용어 | 뜻 |
|---|---|
| 소스 | 지켜보는 앱 하나. 예: Slack, 카카오톡, iCampus |
| 하위 항목 | 소스 안의 방, 채널, 계정. 예: 학생회 집행부, #운영진, Threads |
| 노드 | 앱 트리의 한 줄. '전체' 노드, 소스 노드, 하위 항목 노드가 있다 |
| 부모 노드 | 하위 항목이 있는 소스 노드. 펼치고 접을 수 있다 |
| 리프 노드 | 하위 항목이 없는 노드 |
| 새 알림 | 해당 노드를 hud에서 마지막으로 본 시각 이후에 들어온 알림 |

## 4. 화면 구성

### 4.1 배치

```
 hud  11월 10일 화요일  09:11:47                 안 읽음 19 │ Claude 작업 1 │ 승인 대기 1
 ⚠ Claude Code 승인 대기 │ thesis-exp │ Bash 실행 권한 │ 3분째                     ← 주의 띠
 ▸ iCampus 2시간 50분 뒤 마감 │ 운영체제 10주차 동영상 강의 │ 1/2 시청                (0–3줄)
╭ 앱 ───────────────────────────────────────────────────────────────────────────────╮
│   전체                9   1분 전   학생회 집행부  김민지: 회의록 올렸습니다…           │
│   Slack               3   4분 전   김지훈 (#lab-general)  내일 랩미팅 발표자료…        │
│ ▾ 카카오톡            5            지켜보는 2개 │ 앱 전체 안 읽음 12                  │
│   ├ 학생회 집행부     4   1분 전   김민지: 회의록 올렸습니다. 확인 부탁드려요          │
│   └ 랩 동기방         1  15분 전   최유진: 오늘 점심 학식?                             │
│ ▸ Discord             1  47분 전   miseskorea #운영진  가입 신청 4건 대기 중            │
│ ▾ GroovSide           2            지켜보는 3개 │ 앱 전체 안 읽음 2                    │
│   ├ Instagram         1   1시간    user_123님이 회원님의 게시물을 좋아합니다           │
│   ├ Threads           1   9분 전   새 답글 3개: 지난주 글에 대한 반론이 달렸어요        │
│   └ X                 0            새 알림 없음                                        │
│   Instagram           —            새 알림 없음                                        │
│   iCampus             2   3분 전   [운영체제] 공지  중간고사 성적 공개 및 이의신청 안내  │
╰───────────────────────────────────────────────────────────────────────────────────╯
╭ 일정 ───────────────────────╮╭ Claude Code 3 ────────────────────────────────────────╮
│ 오늘                        ││ ⚠ 승인 대기  thesis-exp       Bash 실행 권한     3분   │
│ ▶ 08:46–09:46 랩미팅 302호  ││ ⠋ 작업 중   miseskorea-web   Edit 회원 가입…   1분   │
│   ██████░░░░ 41% 34분 남음  │╰──────────────────────────────────────────────────────╯
│ 10:39–11:39 학생회 정기회의 │╭ iCampus 5 ────────────────────────────── 갱신 3분 전 ╮
╰─────────────────────────────╯│ 2시간 50분 강의 운영체제   10주차 동영상 강의  1/2 시청 │
╭ 할 일 6 ────────────────────╮│ D-1        퀴즈 미시경제학 9주차 퀴즈          미응시   │
│ ! 어제 18:00 장학금 서류 제출││ ✓          과제 대학글쓰기 기말 보고서 초안   제출 완료 │
│ • 오늘 23:59 과제 3 제출    │╰──────────────────────────────────────────────────────╯
│ · 11/12 (목) Discord 공지   │╭ 알림 › 카카오톡 › 학생회 집행부 4 ─────────────────────╮
│                             ││ 09:10  김민지  회의록 올렸습니다. 확인 부탁드려요        │
╰─────────────────────────────╯╰──────────────────────────────────────────────────────╯
 ↑↓ 이동   Enter 펼치기·접기 / 열기   Tab 패널 이동   r 새로고침   c 세션 정리   q 종료
```

### 4.2 배치 규칙

- 상단 줄(1줄)과 주의 띠(0–3줄)는 항상 맨 위에 고정한다. 주의할 것이 없으면 주의 띠 자리에 "지금 처리할 것 없음" 한 줄을 흐리게 표시한다.
- 앱 패널은 전체 폭, 높이는 내용에 맞추되 최대 14줄이다. 넘치면 패널 안에서 스크롤한다.
- 가운데 영역은 두 열이다.
  - 왼쪽 열: 폭 40% (최소 36칸, 최대 56칸). 일정과 할 일이 높이를 반씩 나눈다.
  - 오른쪽 열: Claude Code(내용 높이, 최대 12줄), iCampus(내용 높이, 최대 9줄), 알림(남은 높이 전부).
- 맨 아래 한 줄은 키 안내다. Textual 기본 `Footer`는 포커스된 표가 가로챈 키를 숨기므로 쓰지 않고, 직접 그린 안내 줄을 쓴다.
- 포커스된 패널은 테두리 색을 강조색으로 바꾼다. 포커스가 없는 표는 커서를 숨긴다.

## 5. 조작

### 5.1 키

| 키 | 동작 |
|---|---|
| ↑ ↓ | 포커스된 패널 안에서 줄 이동 |
| Enter | 부모 노드면 펼치기·접기 전환, 그 외에는 대상 열기 (5.3) |
| Tab / Shift+Tab | 패널 이동: 앱 → 일정 → 할 일 → Claude Code → iCampus → 알림 |
| r | 모든 소스 즉시 새로고침 |
| c | 끝난 Claude Code 세션 정리 |
| q | 종료 |

숫자키 1–9와 ← →는 어떤 동작에도 연결하지 않는다.

### 5.2 포커스와 선택

- 시작하면 앱 패널에 포커스가 있고 커서는 '전체' 노드에 있다.
- 알림 패널은 앱 패널에서 마지막으로 고른 노드를 따라간다. 다른 패널로 포커스를 옮겨도 알림 패널 내용은 바뀌지 않는다.
- 펼침 상태와 마지막 선택 노드는 `~/.hud/state.json`에 저장해서 다시 실행해도 유지한다.

### 5.3 Enter로 여는 대상

| 위치 | Enter 동작 |
|---|---|
| '전체' 노드 | 없음 |
| 부모 노드 (카카오톡, Discord, GroovSide) | 펼치기·접기 |
| 하위 항목 노드 | 그 항목에 `url`이 설정돼 있으면 그 URL, 없으면 소스 앱 |
| 하위 항목 없는 소스 (Slack, Instagram) | `url`이 있으면 그 URL, 없으면 소스 앱 |
| iCampus 소스 노드 | iCampus 대시보드 (`{base_url}`) |
| 알림 패널의 줄 | 그 알림의 소스 앱 (하위 항목 `url`이 있으면 그 URL) |
| 일정 줄 | 캘린더 앱 |
| 할 일 줄 | 미리알림 앱 |
| iCampus 패널의 줄 | 그 항목의 `html_url` |
| Claude Code 줄 | v1에서는 없음 (M4: iTerm2 세션을 앞으로 가져오기) |

앱은 `open -a <process>`, 프로세스 이름이 없으면 `open -b <bundle_id>`, URL은 `open <url>`로 연다. 카카오톡은 특정 방으로 바로 들어가는 방법이 없으므로 앱만 연다.

## 6. 패널 명세

공통 규칙:

- 시간 표기: 오늘이면 `HH:MM`, 어제면 `어제HH:MM`, 그 이전이면 `M/D`.
- 경과 표기: 1분 미만 `방금`, 그 외 `N분 전`, `N시간 전`, `N일 전`.
- 기간 표기: `N초`, `N분`, `N시간 M분`(0분이면 생략), `N일`.
- 빈 상태와 오류는 패널 안 안내 문구로 보여준다. 오류 문구에는 고치는 방법을 적는다.
- 색은 터미널 ANSI 색 이름만 쓴다 (테마 `ansi-dark` 기본). 빨강은 지금 행동해야 하는 것, 노랑은 곧 해야 하는 것, 흐림은 끝났거나 조용한 것.

### 6.1 상단 줄

왼쪽에 ` hud `(반전), 날짜와 요일, 초 단위 시각. 오른쪽에 `안 읽음 N │ Claude 작업 N │ 승인 대기 N`. 0인 값은 흐리게, 안 읽음과 승인 대기가 1 이상이면 빨강 굵게, 작업 중이 1 이상이면 초록.

"안 읽음"은 앱 트리 최상위 노드들의 수 합계다 (6.3의 수 규칙을 따른다).

### 6.2 주의 띠

조건에 맞는 줄을 아래 우선순위대로 최대 3줄 표시한다.

| 순위 | 조건 | 문구 예 | 모양 |
|---|---|---|---|
| 1 | Claude Code 세션이 승인 대기 | `⚠ Claude Code 승인 대기 │ thesis-exp │ Bash 실행 권한 │ 3분째` | 흰 글자, 빨강 배경, 전체 폭 |
| 2 | 15분 안에 시작하는 일정 | `▸ 5분 뒤 학부 수업 조교 (09:00 · 공학관 204)` | 검정 글자, 노랑 배경, 전체 폭 |
| 3 | 6시간 안에 마감인 미완료 iCampus 항목 | `▸ iCampus 2시간 50분 뒤 마감 │ 운영체제 10주차 동영상 강의 │ 1/2 시청` | 검정 글자, 노랑 배경, 전체 폭 |
| 4 | 기한 지난 할 일 | `! 기한 지난 할 일 │ 장학금 서류 제출 외 1개` | 빨강 굵은 글자 |
| 5 | 10분 안에 끝난 Claude Code 세션 | `✓ Claude Code 응답 완료 │ hud │ 3분 전` | 청록 글자 |

같은 순위가 여러 개면 각각 한 줄씩이다 (예: 승인 대기 세션 2개 → 2줄). 아무것도 없으면 `지금 처리할 것 없음 │ 다음 일정 오늘 16:00 학생회 회의 (1시간 28분 뒤)`를 흐리게 표시한다.

### 6.3 앱 트리

**열**

| 열 | 폭 | 내용 |
|---|---|---|
| 이름 | 18 | 펼침 표시(`▸`/`▾`), 들여쓰기와 가지(`├ `, `└ `), 이름. 소스 이름은 소스 색으로 굵게 |
| 수 | 4 | 새 알림 수 또는 Dock 배지 |
| 경과 | 7 | 가장 최근 알림의 경과 시간 |
| 최근 메시지 | 나머지 | 제목(굵게) + 본문. 폭에 맞춰 말줄임 |

**줄 종류별 규칙**

| 줄 | 수 | 경과·메시지 |
|---|---|---|
| 전체 (항상 맨 위) | 모든 최상위 노드 수의 합 | 지켜보는 대상 전체에서 가장 최근 알림. 메시지 앞에 출처 이름 |
| 부모, 접힘 | 하위 항목 새 알림 수의 합 | 하위 항목 중 가장 최근 알림 |
| 부모, 펼침 | 같음 | `지켜보는 N개 │ 앱 전체 안 읽음 M` (흐리게, M은 Dock 배지. 배지가 없으면 앞부분만) |
| 하위 항목 | 그 항목의 새 알림 수 | 그 항목의 가장 최근 알림 본문 (보낸 사람 포함) |
| 하위 항목 없는 소스 | Dock 배지 (6.3.1) | 그 소스의 가장 최근 알림 |
| iCampus 소스 | 새 공지 수 (6.3.2 봤음 처리 적용) | 가장 최근 공지 `[과목] 제목` |

새 알림이 없으면 메시지 칸에 `새 알림 없음`을 흐리게 쓴다.

**6.3.1 Dock 배지 표시**

숫자 1 이상은 빨강 굵게, `•` 같은 문자는 노랑 굵게, 배지 없음은 `0` 흐리게, 앱이 꺼져 있으면 `꺼짐` 흐리게, 배지를 읽지 않는 소스(`process`가 빈 값)는 `—` 흐리게.

**6.3.2 새 알림 수와 '봤음' 처리**

- 하위 항목의 수 = 그 항목에 걸린 알림 중 `seen[항목]` 시각보다 늦게 도착한 개수. `seen`이 없으면 `notification_hours` 안의 전부.
- 커서가 어떤 노드에 `seen_dwell_seconds`(기본 2초) 이상 머물면 그 노드를 봤음 처리한다. 부모 노드는 모든 하위 항목을, '전체' 노드는 모든 노드를 봤음 처리한다.
- 봤음 시각은 `state.json`에 저장한다.
- 카카오톡 같은 앱의 실제 안 읽음 수와는 다를 수 있다. README와 `--doctor`에 이 점을 적는다.

**6.3.3 지정 방 밖의 알림**

`only_children = true`인 소스에서 어떤 하위 항목에도 걸리지 않은 알림은 버린다 (수, 피드, '전체' 어디에도 안 나옴). `only_children = false`면 걸리지 않은 알림을 자동 하위 항목 `기타`로 모으고, `기타`는 알림이 있을 때만 보인다.

### 6.4 알림 패널

- 제목: `알림` + 선택 경로 + 개수. 예: `알림 › 카카오톡 › 학생회 집행부 4`. '전체'면 `알림 9`.
- 최신순, 최대 200줄.

| 선택 | 열 |
|---|---|
| 전체, 부모 노드 | 시간(8) · 출처(10, 하위 항목 이름 또는 소스 이름, 소스 색) · 메시지(제목 굵게 + 부제목 흐리게 + 본문) |
| 하위 항목, 하위 없는 소스 | 시간(8) · 보낸 사람(10, 굵게) · 메시지(본문) |

- 보낸 사람은 소스의 `sender` 규칙(8장)으로 뽑는다. 뽑지 못하면 제목을 쓴다.
- 새 알림(봤음 시각 이후)은 보통 밝기, 이미 본 알림은 흐리게.
- 빈 상태: `최근 48시간 동안 받은 알림 없음`. 알림 DB를 못 읽으면 전체 디스크 접근 권한 안내.

### 6.5 일정 (v0 유지)

- 오늘부터 `calendar_days`일. 날짜가 바뀌는 곳에 `오늘`, `내일`, `11/12 (목)` 머리줄.
- 지난 일정은 흐리게, 종일 일정은 `종일`.
- 진행 중인 일정은 두 줄: `▶ 시작–끝 제목 장소`(초록 굵게)와 진행 막대 `██████░░░░ 41%  34분 남음`.
- 오늘 다음 일정에 `N분 뒤`(노랑) 표시. 15분 이내면 시각도 노랑 굵게.

### 6.6 할 일 (v0 유지)

- 미리알림의 미완료 항목. 정렬: 기한 있는 것 먼저 기한 순, 기한 없는 것은 아래.
- 표시: 기한 지남 `!` 빨강, 오늘 `•` 노랑, 그 외 `·`. 우선순위 높음은 제목 굵게. 제목 뒤에 목록 이름 흐리게.
- 시간 없는 기한은 그날이 지나야 기한 지남으로 본다.

### 6.7 Claude Code (v0 유지)

| 상태 | 표시 | 상세 | 시간 |
|---|---|---|---|
| permission | `⚠ 승인 대기` 빨강 굵게 | `<도구> 실행 권한` | 대기 시간, 빨강 |
| working | 스피너 + `작업 중` 초록 | 마지막 도구 + 프롬프트 앞부분 흐리게 | 작업 시간 |
| working, 15분 넘게 신호 없음 | `? 작업 중` 노랑 | `N분째 신호 없음 (중단했다면 c로 정리)` | |
| done | `✓ 완료` 청록 | 프롬프트 흐리게 | `N분 전` |
| idle | `· 대기` 흐리게 | `입력 기다리는 중` | `N분 전` |

정렬: permission → working → done → idle, 같은 상태는 최근 갱신 순. 24시간 넘게 갱신 없는 세션 파일은 지운다.

### 6.8 iCampus 패널

**열**

| 열 | 폭 | 규칙 |
|---|---|---|
| 남은 시간 | 11 | 완료 `✓` 초록 / 마감 지남 `지남` 빨강 굵게 / 24시간 미만 `N시간 M분` (6시간 미만 빨강 굵게, 그 외 노랑 굵게) / 24시간 이상 `D-N` (2일 이하 굵게) |
| 종류 | 4 | `강의`, `과제`, `퀴즈`, `토론` |
| 과목 | 11 | 과목 이름 굵게, 말줄임 |
| 항목 | 나머지 | 항목 제목 |
| 상태 | 10 | 7.6.3 매핑. 해야 할 상태(`미제출`, `미응시`, `0/3 시청` 등)는 노랑, 끝난 상태는 흐리게 |
| 마감 | 11 | 오늘·내일이면 `오늘 18:00`, 23:59 마감이면 `11/13 (금)`, 그 외 `11/13 18:00`. 흐리게 |

**범위와 정렬**

- 범위: 어제부터 `days_ahead`일(기본 14일) 뒤까지.
- 미완료를 위에 마감 순으로, 완료는 아래에 흐리게. 완료된 항목은 마감 후 `show_done_days`일(기본 1일)이 지나면 숨긴다.
- 제목: `iCampus N` (미완료 개수). 오른쪽 테두리에 `갱신 N분 전`.
- 갱신에 실패하면 마지막으로 받은 데이터를 유지하고 패널 안내 줄에 원인과 해결 방법을 쓴다.
- iCampus를 끄면(`enabled = false`) 패널을 숨긴다.

## 7. 데이터 소스

모든 수집은 UI 스레드가 아닌 수집 스레드에서 한다. 수집 함수는 예외를 밖으로 던지지 않고 `(데이터, 오류 문구 또는 None)`을 돌려준다.

| 소스 | 방법 | 주기 | 필요한 권한 |
|---|---|---|---|
| Dock 배지 | `lsappinfo` | 2초 | 없음 |
| 알림 | 알림 센터 SQLite DB | 2초 (파일이 바뀐 때만 다시 읽음) | 전체 디스크 접근 |
| 일정, 할 일 | EventKit (PyObjC) | 60초, `r`로 즉시 | 캘린더·미리알림 전체 접근 |
| Claude Code | hook이 쓰는 상태 파일 | 1초 | 없음 |
| iCampus | Canvas REST API | 10분, `r`로 즉시 | 개인 액세스 토큰 |
| Discord 봇 (선택) | Discord REST API | 60초 | 봇 토큰 |

### 7.1 Dock 배지

`lsappinfo info -only StatusLabel "<process>"`의 출력에서 `"label"="..."` 값을 읽는다.

- 출력이 비어 있으면 앱이 꺼진 것 → `None`
- `StatusLabel`은 있는데 `label`이 없으면 배지 없음 → `""`
- 그 외 → 배지 문자열 (`"12"`, `"•"` 등)

### 7.2 알림 센터 DB

- 경로: macOS 15 이상 `~/Library/Group Containers/group.com.apple.usernoted/db2/db`. 없으면 `$(getconf DARWIN_USER_DIR)/com.apple.notificationcenter/db2/db`.
- 반드시 읽기 전용(`file:...?mode=ro`)으로 연다. 절대 쓰지 않는다.
- 권한이 없으면 파일을 여는 순간 `PermissionError`가 난다. 이때 전체 디스크 접근 권한 안내를 돌려준다.
- `db`와 `db-wal`의 수정 시각·크기가 그대로면 다시 질의하지 않는다.

질의:

```sql
SELECT a.identifier, r.delivered_date, r.data
FROM record r JOIN app a ON a.app_id = r.app_id
ORDER BY r.delivered_date DESC LIMIT 300;
```

- `delivered_date`는 2001-01-01 UTC 기준 초(Cocoa 시각). 비어 있으면 plist의 `date`를 쓴다.
- `data`는 바이너리 plist다. `req` 딕셔너리에서 아래 키를 읽는다. 공백과 줄바꿈은 한 칸으로 합친다.

| plist 키 | 필드 이름 | 뜻 |
|---|---|---|
| `req.titl` | title | 제목 |
| `req.subt` | subtitle | 부제목 |
| `req.body` | body | 본문 |
| `req.thre` 또는 `req.thrd` | thread | 대화 묶음 식별자 (앱마다 다름, 없을 수 있음) |
| `req.cate` | category | 알림 종류 |

thread 키 이름은 macOS 버전에 따라 다를 수 있으니 둘 다 확인한다. `--dump`(11장)로 실제 키를 확인하고 이 표를 고친다.

### 7.3 소스·하위 항목 매칭

1. 알림의 번들 ID가 소스의 `bundle_ids` 중 하나와 맞는지 본다 (`*` 와일드카드). 소스에 `match`가 있으면 그것도 맞아야 한다. 위에서부터 처음 맞는 소스에 넣는다.
2. 그 소스의 하위 항목을 위에서부터 보며 `match`가 맞는 첫 항목에 넣는다.
3. 걸리는 하위 항목이 없으면 6.3.3 규칙을 따른다.
4. 어떤 소스에도 맞지 않는 알림은 `show_other_apps = true`일 때만 '전체' 피드에 출처를 번들 ID 끝부분으로 표시한다. 기본값은 `false`.

`match` 규칙:

- 키: `title`, `subtitle`, `body`, `thread`, `any`(제목·부제목·본문을 이어 붙인 것)
- 값: 대소문자 무시 부분 일치. `re:`로 시작하면 정규식
- 키가 여러 개면 모두 맞아야 한다

보낸 사람 추출(`sender`):

| 값 | 규칙 |
|---|---|
| `title` | 제목을 보낸 사람으로 |
| `subtitle` | 부제목을 보낸 사람으로 |
| `body_prefix` | 본문을 처음 나오는 `sender_sep`(기본 `": "`)에서 나눠 앞을 보낸 사람, 뒤를 메시지로 |
| `none` | 보낸 사람 열을 비움 |

앱별 알림 형식은 아직 확인하지 않았다 (16장 Q1, Q2). M2를 시작하기 전에 사용자의 맥에서 `--dump`로 확인하고 기본 설정 예시를 고친다.

### 7.4 캘린더 · 미리알림 (v0 유지)

- `EKEventStore`에 `requestFullAccessToEventsWithCompletion:` / `requestFullAccessToRemindersWithCompletion:`로 권한을 요청한다 (macOS 14 이상 API, 없으면 구 API). 완료 콜백은 임의 큐에서 오므로 `threading.Event`로 기다린다.
- 권한을 받은 뒤 store를 새로 만들고, 5분마다 다시 만든다.
- 일정: `predicateForEventsWithStartDate:endDate:calendars:`로 오늘 0시부터 `calendar_days`일.
- 할 일: `predicateForIncompleteRemindersWithDueDateStarting:ending:calendars:`(모두 nil)로 미완료 전체. 기한은 `NSCalendar.dateFromComponents`로 바꾸고, `hour`가 정의되지 않았으면 시간 없는 기한으로 본다.
- `exclude_calendars`, `exclude_reminder_lists`에 있는 이름은 뺀다.

### 7.5 Claude Code hook (v0 유지)

`install_hooks.py`가 `~/.claude/settings.json`에 아래 hook을 넣는다. 명령은 `"<~/.hud/venv/bin/python>" "<~/.hud/claude_hook.py>" <상태>`, timeout 5초.

| 이벤트 | matcher | 상태 인자 |
|---|---|---|
| SessionStart | — | `idle` |
| UserPromptSubmit | — | `working` |
| PreToolUse | `*` | `working` (도구 이름 기록) |
| PostToolUse | `*` | `working` |
| Notification | `permission_prompt` | `permission` |
| Notification | `idle_prompt` | `idle` |
| Stop | — | `done` |
| SessionEnd | — | `end` (상태 파일 삭제) |

`claude_hook.py` 규칙:

- stdin JSON에서 `session_id`, `cwd`, `hook_event_name`, `tool_name`, `message`, `prompt`, `source`를 읽어 `~/.hud/claude/<session_id>.json`에 원자적으로 쓴다 (임시 파일 후 `os.replace`).
- **stdout에 아무것도 출력하지 않는다.** UserPromptSubmit hook의 stdout은 Claude의 컨텍스트에 들어간다.
- 어떤 오류가 나도 exit 0. 표준 라이브러리만 쓴다.
- SessionStart의 `source`가 `startup`이 아니면(compact, resume 등) 기존 상태를 덮어쓰지 않는다.
- `done` 다음에 오는 `idle` 알림은 무시한다 (완료 표시 유지).
- 상태가 바뀔 때만 `since`를 갱신한다. 프롬프트는 공백을 합쳐 200자까지만 저장한다.

상태 파일 형식:

```json
{"session_id": "...", "cwd": "/Users/.../thesis-exp", "state": "permission",
 "since": 1794300751.1, "updated": 1794300751.1, "tool": "Bash",
 "message": "Claude needs your permission to use Bash", "prompt": "실험 돌려줘"}
```

### 7.6 iCampus (Canvas API)

#### 7.6.1 인증

- 기본 주소: `https://canvas.skku.edu` (설정 `base_url`)
- 개인 액세스 토큰을 macOS 키체인에 저장한다. 설정 파일, 저장소, 로그에는 절대 쓰지 않는다.
  - 저장: `security add-generic-password -a "$USER" -s hud.icampus -w` (값은 대화형 입력)
  - 읽기: `security find-generic-password -s hud.icampus -w`
- 요청 헤더: `Authorization: Bearer <토큰>`
- 학교가 학생 토큰 발급을 막아 두었을 수 있다 (16장 Q3). 막혀 있으면 7.6.5 대안을 쓴다.

#### 7.6.2 호출

구현 전에 Canvas 공식 API 문서로 경로와 필드를 다시 확인한다.

| 용도 | 요청 |
|---|---|
| 마감 항목 | `GET /api/v1/planner/items?start_date=<어제>&end_date=<+days_ahead일>&per_page=100` |
| 수강 과목 | `GET /api/v1/courses?enrollment_state=active&per_page=100` |
| 공지 | `GET /api/v1/announcements?context_codes[]=course_<id>&start_date=<-14일>&per_page=50` |

- 페이지는 `Link` 헤더의 `rel="next"`를 따라간다.
- 타임아웃 10초. 실패하면 2분, 4분, 8분… 최대 30분까지 늘려 다시 시도한다.
- 성공한 응답은 `~/.hud/cache/icampus.json`에 저장하고, 시작할 때 먼저 이 캐시를 보여준다.
- HTTP 클라이언트는 표준 라이브러리 `urllib.request`를 쓴다.
- 네트워크 대상은 `base_url` 호스트 하나뿐이다.

#### 7.6.3 항목 변환

planner item에서 쓰는 필드: `plannable_type`, `plannable.title`, `plannable_date`(또는 `plannable.due_at`), `context_name`, `course_id`, `html_url`, `submissions`. `submissions`는 객체 대신 `false`로 올 수 있으니 미제출로 처리한다.

| `plannable_type` | 종류 | 상태 |
|---|---|---|
| `assignment` | 과제 | `submissions.submitted`면 `제출 완료`(지각이면 `지각 제출`), `graded`면 `채점 완료`, `missing`이면 `미제출`(빨강), 그 외 `미제출` |
| `quiz` | 퀴즈 | 제출했으면 `응시 완료`, 아니면 `미응시` |
| `discussion_topic` | 토론 | 제출했으면 `참여 완료`, 아니면 `미참여` |
| 동영상 강의 | 강의 | `k/n 시청` (7.6.4) |
| `announcement` | — | 공지로 분류해 앱 트리와 알림 패널로 보냄 |
| `calendar_event`, `planner_note`, `wiki_page` | — | v1에서는 무시 |

완료 여부: 상태가 `제출 완료`, `지각 제출`, `채점 완료`, `응시 완료`, `참여 완료`, 또는 시청 `n/n`이면 완료다.

#### 7.6.4 동영상 강의 시청 현황

표준 Canvas API에는 동영상 시청·출석 정보가 없다. 학교 쪽 별도 기능일 가능성이 높다. 스파이크 S2(14장)에서 조사한다.

- 참고: 크롬 확장 iCampus Check V2 (MIT, `github.com/moseoridev/iCampusCheck`)는 canvas.skku.edu에서 강의·과제 마감과 출결/학습 현황을 가져온다. 어떤 엔드포인트를 쓰는지 확인한다.
- 가져올 수 없으면 강의 항목은 상태 칸을 `—`로 두고 마감만 보여준다.

#### 7.6.5 토큰을 못 쓸 때의 대안

Canvas 캘린더 화면의 캘린더 피드(ICS) 주소를 macOS 캘린더에 구독하면 과제 마감이 일정 패널에 나타난다. 제출 상태는 볼 수 없다. 이 경우 `enabled = false`로 iCampus 패널을 숨기고 README에 방법을 적는다.

### 7.7 Discord 봇 (선택, M4)

miseskorea 서버는 사용자가 운영하므로, 지정 채널을 알림 대신 봇으로 직접 읽을 수 있다. 알림 설정과 상관없이 모든 메시지를 받는다.

- 봇 토큰은 키체인 `hud.discord`에 저장한다.
- 개발자 포털에서 Message Content 권한을 켜고, 서버에서는 해당 채널의 채널 보기·메시지 기록 보기 권한만 준다.
- 하위 항목에 `channel_id`가 있으면 그 채널은 `GET /channels/{channel_id}/messages?limit=20`(헤더 `Authorization: Bot <토큰>`)을 60초마다 호출한 결과를 쓰고, 알림 매칭은 하지 않는다.
- Gateway(실시간 연결)는 v1에서 구현하지 않는다.

## 8. 설정 파일 (`~/.hud/config.toml`, 버전 1)

### 8.1 예시

```toml
version = 1

[general]
notification_hours = 48
show_other_apps = false
seen_dwell_seconds = 2
calendar_days = 3
exclude_calendars = ["생일", "Birthdays", "Siri Suggestions"]
exclude_reminder_lists = []
theme = "ansi-dark"

[[apps]]
name = "Slack"
process = "Slack"
bundle_ids = ["com.tinyspeck.slackmacgap"]
color = "magenta"
sender = "title"

[[apps]]
name = "카카오톡"
process = "KakaoTalk"
bundle_ids = ["com.kakao.KakaoTalkMac"]
color = "yellow"
only_children = true
sender = "body_prefix"          # --dump 결과를 보고 확정

  [[apps.children]]
  name = "학생회 집행부"
  match = { title = "학생회 집행부" }

  [[apps.children]]
  name = "랩 동기방"
  match = { title = "랩 동기방" }

[[apps]]
name = "Discord"
process = "Discord"
bundle_ids = ["com.hnc.Discord"]
color = "blue"
only_children = true

  [[apps.children]]
  name = "#운영진"
  match = { title = "#운영진" }
  url = "discord://-/channels/<서버ID>/<채널ID>"   # 선택. 동작 확인 필요
  # channel_id = "123456789"                      # Discord 봇을 쓸 때 (M4)

[[apps]]
name = "GroovSide"
process = "GroovSide"
bundle_ids = []                 # --doctor로 확인해서 채움
color = "cyan"
only_children = false           # 구분 안 되는 알림은 '기타'로

  [[apps.children]]
  name = "Instagram"
  match = { any = "instagram" }

  [[apps.children]]
  name = "Threads"
  match = { any = "threads" }

  [[apps.children]]
  name = "X"
  match = { any = "re:\\bx\\.com\\b|\\btwitter\\b" }

[[apps]]
name = "Instagram"
process = ""
bundle_ids = ["com.google.Chrome", "com.apple.Safari", "com.apple.Safari.WebApp.*"]
match = { any = "instagram" }
url = "https://www.instagram.com/direct/inbox/"
color = "bright_magenta"

[[apps]]
name = "iCampus"
kind = "icampus"
color = "green"

[icampus]
enabled = true
base_url = "https://canvas.skku.edu"
keychain_service = "hud.icampus"
poll_minutes = 10
days_ahead = 14
show_done_days = 1

[discord_bot]
enabled = false
keychain_service = "hud.discord"
poll_seconds = 60
```

GroovSide 하위 항목의 `match` 값은 자리표시다. 실제 알림 형식을 확인한 뒤 고친다.

### 8.2 필드

`[[apps]]` (나열한 순서가 트리 순서):

| 필드 | 기본값 | 뜻 |
|---|---|---|
| `name` | 필수 | 표시 이름. 같은 이름 금지 |
| `kind` | `"notifications"` | `"notifications"` 또는 `"icampus"` |
| `process` | `""` | Dock 배지를 읽고 앱을 열 때 쓰는 이름. 비우면 배지를 읽지 않음 |
| `bundle_ids` | `[]` | 알림 매칭용 번들 ID. `*` 가능 |
| `match` | 없음 | 소스 단위 매칭 규칙 (7.3) |
| `color` | `"white"` | ANSI 색 이름 또는 `#RRGGBB` |
| `only_children` | `false` | 하위 항목에 안 걸린 알림을 버릴지 |
| `sender` | `"title"` | 보낸 사람 추출 규칙 (7.3) |
| `sender_sep` | `": "` | `body_prefix`일 때 구분자 |
| `url` | 없음 | Enter로 열 주소 |
| `children` | `[]` | 하위 항목 목록 |

`[[apps.children]]`: `name`(필수), `match`(필수), `url`(선택), `channel_id`(선택, Discord 봇).

### 8.3 검증과 v0 호환

- 시작할 때 설정을 검증한다. 모르는 필드, 중복 이름, 잘못된 정규식은 화면을 띄우기 전에 파일 이름과 줄을 포함한 한국어 오류로 알리고 종료한다.
- `version`이 없으면 v0 설정으로 보고 읽는다. v0의 `key` 필드는 무시하고, 문자열 `match`는 `{ any = "<값>" }`으로 바꿔 읽는다. 시작 화면 대신 `--doctor`에서 "v1 형식으로 바꾸세요"라고 안내한다.

## 9. 상태 · 캐시 파일

모두 원자적으로 쓴다 (임시 파일 후 `os.replace`).

| 파일 | 내용 |
|---|---|
| `~/.hud/state.json` | `{"version": 1, "expanded": ["카카오톡", "GroovSide"], "selected": "카카오톡/학생회 집행부", "seen": {"카카오톡/학생회 집행부": 1794300751.1}}` |
| `~/.hud/claude/<session_id>.json` | 7.5 |
| `~/.hud/cache/icampus.json` | 마지막으로 받은 마감 항목과 공지 (메타데이터만) |

노드 키는 `소스이름` 또는 `소스이름/하위이름`이다. 설정에서 이름을 바꾸면 이전 키는 무시한다.

## 10. macOS 설정 안내 (README에 반영)

**전체 디스크 접근 권한**: 시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한에서 hud를 띄울 터미널을 켠다. 이 권한은 그 터미널에서 실행되는 모든 프로그램에 적용되므로, hud는 Terminal.app에서만 띄우고 Claude Code는 다른 터미널에서 쓰도록 권장한다.

**캘린더 · 미리알림**: 처음 실행할 때 뜨는 창에서 허용. 안 뜨면 Terminal.app에서 실행.

**앱별 알림 설정** (팝업 없이 기록만 남기기). 시스템 설정 → 알림에서 지켜보는 앱마다:

| 항목 | 설정 | 이유 |
|---|---|---|
| 알림 허용 | 켬 | 끄면 알림 센터에 기록되지 않음 |
| 알림 스타일 | 없음 | 우측 상단 팝업이 뜨지 않음 |
| 알림 센터에 표시 | 켬 | hud가 여기서 읽음 |
| 앱 아이콘에 배지 표시 | 켬 | Dock 배지 수 |
| 사운드 재생 | 끔 | 선택 |

**앱 안의 알림 설정**: 카톡에서 알림을 끈 방은 알림이 오지 않으므로 지켜볼 수 없다. Discord 서버 채널은 기본이 "@멘션만"이므로 지켜볼 채널은 "모든 메시지"로 바꾼다 (팝업은 위 설정으로 꺼져 있으므로 시끄럽지 않다). 앱에서 그 방을 보고 있을 때는 알림이 오지 않을 수 있다.

## 11. 명령줄

| 명령 | 동작 |
|---|---|
| `hud` | 대시보드 실행 |
| `hud --demo` | 가짜 데이터로 실행. 모든 상태(트리 펼침·접힘, 승인 대기, 진행 중 일정, 기한 지난 할 일, iCampus 각 상태)를 포함 |
| `hud --doctor` | 점검 결과 출력 (아래) |
| `hud --dump <번들ID> [-n 20]` | 그 앱의 최근 알림 원본 필드를 표로 출력: 시각, title, subtitle, body 앞 60자, thread, category. 매칭 규칙을 쓰기 위한 도구 |
| `hud --config <경로>` | 다른 설정 파일 사용 |

`--doctor` 점검 항목:

1. 설정 파일 검증 결과, v0 형식이면 안내
2. 알림 DB 접근 가능 여부와 번들 ID별 알림 개수, 연결된 소스
3. 소스별 Dock 배지 읽기 결과
4. 하위 항목별 최근 7일 매칭 개수. 0개면 "매칭되는 알림 없음 — `hud --dump <번들ID>`로 형식을 확인하세요"
5. 캘린더·미리알림 권한 상태
6. Claude Code hook 설치 여부, 기록된 세션 수
7. iCampus: 키체인 토큰 유무, `GET /api/v1/users/self` 응답 코드 (토큰 값은 출력하지 않음)

## 12. 비기능 요구사항

- **안정성**: 어떤 수집기나 패널에서 오류가 나도 앱이 죽지 않는다. 오류는 해당 패널 안내 줄에 표시한다. 종료 중에 타이머가 돌아도 오류가 나지 않는다.
- **반응성**: 키 입력은 100ms 안에 화면에 반영한다. 수집은 백그라운드 스레드에서 하고 UI는 1초마다 마지막 스냅샷을 그린다.
- **자원**: 대기 중 CPU 3% 이하, 메모리 150MB 이하.
- **한글**: 모든 폭 계산은 셀 폭(Rich `cell_len`, `Text.truncate`)으로 한다. `len()`으로 자르지 않는다.
- **글리프**: 이모지는 쓰지 않는다. 쓰는 기호: `⚠ ▸ ▶ ▾ ✓ ! • · │ ├ └ █ ░`, 점자 스피너 `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`.
- **보안·개인정보**: 토큰은 키체인에만. 메시지 본문은 디스크에 저장하지 않는다 (상태 파일에는 봤음 시각만, 캐시에는 iCampus 메타데이터만, Claude 프롬프트는 200자까지). 외부로 보내는 데이터 없음. 로그 파일을 만들지 않는다.
- **설정 파일 보호**: `~/.claude/settings.json`은 `install_hooks.py`만 수정하고, 수정 전에 항상 `settings.json.bak-<시각>`으로 백업한다. hud 본체는 이 파일을 읽기만 한다.

## 13. 테스트

자동 테스트 (Linux에서도 돌아가야 함):

- 알림 DB: 테스트용 SQLite를 만드는 픽스처(`app`, `record` 테이블, 바이너리 plist)로 파싱, 기간 필터, 캐시 동작 확인
- 매칭: 소스·하위 항목 매칭, `re:`, AND 조건, `only_children`, `기타`, `show_other_apps`
- 보낸 사람 추출: 네 가지 규칙과 실패 시 제목 대체
- 새 알림 수와 봤음 처리: 머문 시간, 부모·전체 노드의 일괄 처리, 저장·복원
- 설정: v1 예시 통과, 오류 사례별 메시지, v0 호환
- Claude hook: 상태 전환 시나리오 (시작 → 프롬프트 → 도구 → 승인 대기 → 도구 완료 → 완료 → idle 무시 → 종료), stdout이 비어 있는지, 잘못된 입력에도 exit 0
- `install_hooks.py`: 다른 hook 보존, 여러 번 실행해도 중복 없음, 제거, 백업 파일 이름 충돌
- iCampus: 저장해 둔 JSON 응답 픽스처로 변환, 상태 매핑, 페이지 넘김, 실패 시 캐시 유지
- UI (Textual pilot, `--demo`): ↑↓ 이동, Enter 펼치기·접기, 리프에서 Enter 시 `open` 호출(목으로 대체), 선택에 따라 알림 패널 제목·내용 변경, Tab 순서. 140×42와 100×30 스크린샷을 저장해 눈으로 확인

사용자 맥에서 확인할 것 (각 마일스톤 끝에 목록으로 남긴다):

- `hud --doctor` 전 항목 ✓
- 지정한 카톡 방에 메시지가 오면 해당 노드 수가 늘고, 2초 머물면 0이 됨
- 지정하지 않은 방의 메시지는 어디에도 안 보임
- 팝업 없이(알림 스타일 '없음') 알림 패널에 내용이 들어옴
- Claude Code에서 권한 요청 시 주의 띠에 빨간 줄이 뜨고, 승인하면 사라짐

## 14. 마일스톤

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| **M1** 탐색 구조 | 설정 v1 파서와 검증(v0 호환), 앱 트리(전체·부모·리프), Enter 펼치기·접기와 열기, 숫자키·←→ 제거, 알림 패널 선택 연동, 키 안내 줄, `state.json` | 13장의 설정·UI 자동 테스트 통과. `--demo` 스크린샷이 4.1 배치와 일치 |
| **M2** 지정 방 필터 | 매칭 엔진, `only_children`·`기타`, 보낸 사람 추출, 새 알림 수와 봤음 처리, `--dump`, `--doctor` 4번 항목 | 매칭·추출·봤음 테스트 통과. 사용자가 `--dump`로 규칙을 쓴 뒤 지정 방만 보임 |
| **S1** 스파이크 | 성균관대 학생 토큰 발급 가능 여부 | 결과를 16장 Q3에 기록 |
| **S2** 스파이크 | 동영상 시청 현황 데이터 출처 (iCampus Check V2 조사) | 결과를 16장 Q4와 7.6.4에 기록 |
| **M3** iCampus | 키체인 토큰, API 호출과 캐시, 마감 패널, 공지 노드, 주의 띠 3순위, `--doctor` 7번 항목 | iCampus 테스트 통과. 사용자 맥에서 실제 과목 마감이 보임 |
| **M4** 선택 | Discord 봇, Claude Code 줄 Enter → iTerm2 세션 포커스 | 사용자가 원할 때 진행 |

각 단계는 독립적으로 동작하는 상태로 끝낸다. README와 이 문서를 같이 갱신한다.

## 15. 결정 사항

대화에서 확정한 것:

1. GUI가 아니라 터미널(CLI) 대시보드로 간다. iCampus도 별도 프로그램이 아니라 hud의 패널로 넣는다.
2. 숫자키로 앱을 여는 기능은 없앤다. ↑↓로 이동하고 Enter로 펼치기·접기와 열기를 한다. ←→도 쓰지 않는다.
3. GroovSide는 Instagram, Threads, X 하위 항목으로 펼친다.
4. 카카오톡과 Discord는 지정한 방·채널만 보여준다.
5. 우측 상단 팝업은 끈다. macOS 알림 스타일을 '없음'으로 두고 알림 센터 기록을 읽는다.
6. 코드 구현은 이 명세서와 CLAUDE.md를 기준으로 Claude Code가 진행한다.

이 문서에서 제안한 것 (사용자 확인 필요):

- 앱 트리 맨 위의 '전체' 노드 (6.3)
- 하위 항목 수를 "hud에서 마지막으로 본 이후"로 세는 방식과 2초 머묾 규칙 (6.3.2)
- 알림 패널이 다른 패널로 포커스를 옮겨도 마지막 선택을 유지하는 동작 (5.2)
- `show_other_apps` 기본값을 `false`로 바꾸는 것 (7.3)

## 16. 열린 질문

| 번호 | 질문 | 확인 방법 | 영향 |
|---|---|---|---|
| Q1 | 카카오톡 맥 알림에서 단톡방 이름과 보낸 사람이 어느 필드에 들어가는가 | `hud --dump com.kakao.KakaoTalkMac` | 카톡 `match`, `sender` 기본값 |
| Q2 | GroovSide의 번들 ID와, 알림에 플랫폼(Instagram/Threads/X)이 구분되어 있는가 | `hud --doctor`, `--dump` | 구분이 안 되면 GroovSide는 하위 항목 없는 소스로 |
| Q3 | 성균관대 iCampus에서 학생이 개인 액세스 토큰을 만들 수 있는가 | 계정 → 설정에서 새 액세스 토큰 버튼 확인 | 막혀 있으면 7.6.5 대안 |
| Q4 | 동영상 강의 시청 현황을 어디서 가져올 수 있는가 | S2 | 강의 상태 칸 |
| Q5 | 카카오톡이 앱에서 읽은 메시지의 알림을 알림 센터에서 지우는가 | 메시지를 앱에서 읽은 뒤 `--dump` 비교 | 지운다면 봤음 처리 없이 알림 수만으로 충분할 수 있음 |
| Q6 | Discord 데스크톱 알림 제목에 서버·채널 이름이 들어가는가 | `hud --dump com.hnc.Discord` | Discord `match` 기본값 |

## 부록 A. 파일 구성 (목표)

| 파일 | 역할 |
|---|---|
| `hud.py` | 진입점, 명령줄 처리, Textual 앱과 패널 그리기 |
| `collectors.py` | Dock 배지, 알림 DB, EventKit, Claude 상태 수집 |
| `matching.py` | 소스·하위 항목 매칭, 보낸 사람 추출 |
| `tree.py` | 앱 트리 모델, 새 알림 수, 봤음 처리 |
| `icampus.py` | Canvas API 호출, 변환, 캐시 |
| `config.py` | 설정 읽기, 검증, v0 호환 |
| `state.py` | `state.json` 읽기·쓰기 |
| `claude_hook.py` | Claude Code hook (표준 라이브러리만) |
| `install_hooks.py`, `install.sh` | 설치 |
| `config.toml` | 기본 설정 예시 |
| `tests/` | 13장 자동 테스트와 픽스처 |
| `docs/previews/` | 디자인 참고 이미지 |

## 부록 B. GUI 후보 (v1 범위 밖)

터미널을 띄워 두지 않을 때도 보고 싶다면, hud가 모은 데이터를 App Group 공유 파일로 내보내고 WidgetKit 데스크톱 위젯이 "다음 마감 3개"와 "승인 대기 세션"만 보여주는 방식을 검토한다. 위젯은 시스템이 갱신 빈도를 제한하므로 실시간 감시용이 아니라 보조용이다.
