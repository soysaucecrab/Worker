"""hud 데이터 수집기.

각 수집기는 실패해도 예외를 밖으로 던지지 않고 (데이터, 오류 메시지)를 돌려준다.
오류 메시지는 화면에 그대로 표시되므로 "무엇을 하면 고쳐지는지"를 적는다.
"""
from __future__ import annotations

import fnmatch
import json
import plistlib
import re
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from config import CLAUDE_STATE_DIR, Source

COCOA_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)


# ───────────────────────── 데이터 모델 ─────────────────────────

def notif_fields(title: str, subtitle: str, body: str, thread: str = "") -> dict[str, str]:
    """match 규칙(7.3)이 보는 필드 묶음."""
    return {"title": title, "subtitle": subtitle, "body": body, "thread": thread,
            "any": " ".join(x for x in (title, subtitle, body) if x)}


def source_owns(src: Source, bundle_id: str, fields: dict[str, str]) -> bool:
    """알림이 이 소스에 속하는지 (번들 ID + 소스 단위 match)."""
    if not any(fnmatch.fnmatch(bundle_id, pat) for pat in src.bundle_ids):
        return False
    return (not src.match) or src.match.matches(fields)


@dataclass
class Notification:
    when: datetime
    bundle_id: str
    source: str | None          # 소스 이름 (매칭된 것). 없으면 None
    title: str
    subtitle: str
    body: str
    child: str | None = None    # 하위 항목 이름 (M2 매칭). 없으면 None
    sender: str = ""            # 보낸 사람 (M2 추출). 없으면 ""


@dataclass
class Event:
    title: str
    start: datetime
    end: datetime
    all_day: bool
    calendar: str
    location: str = ""


@dataclass
class Todo:
    title: str
    due: datetime | None
    has_time: bool
    list_name: str
    priority: int = 0  # 1 높음, 5 보통, 9 낮음, 0 없음


@dataclass
class IcampusItem:
    """iCampus 마감 패널의 한 줄 (SPEC 6.8 / 7.6.3)."""
    kind: str                   # 강의 | 과제 | 퀴즈 | 토론
    course: str
    title: str
    status: str                 # 미제출, 미응시, "1/2 시청", 제출 완료 …
    due: datetime | None
    done: bool = False
    due_2359: bool = False      # 23:59 마감이면 마감 칸을 날짜만 표기
    html_url: str = ""


@dataclass
class ClaudeSession:
    session_id: str
    cwd: str
    state: str  # working | permission | done | idle
    since: float
    updated: float
    tool: str = ""
    message: str = ""
    prompt: str = ""

    @property
    def project(self) -> str:
        return Path(self.cwd).name if self.cwd else self.session_id[:8]


@dataclass
class Snapshot:
    badges: dict[str, str | None] = field(default_factory=dict)
    notifications: list[Notification] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    todos: list[Todo] = field(default_factory=list)
    claude: list[ClaudeSession] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    updated: float = 0.0
    icampus: list[IcampusItem] = field(default_factory=list)


# ───────────────────────── Dock 배지 ─────────────────────────

_LABEL_RE = re.compile(r'"label"="([^"]*)"')


def read_badge(process: str) -> str | None:
    """앱의 Dock 배지 문자열. 앱이 꺼져 있으면 None, 배지가 없으면 ""."""
    if not process:
        return None
    try:
        out = subprocess.run(
            ["lsappinfo", "info", "-only", "StatusLabel", process],
            capture_output=True, text=True, timeout=2,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not out.strip():
        return None
    m = _LABEL_RE.search(out)
    return m.group(1) if m else ""


# ───────────────────────── 알림 센터 DB ─────────────────────────

def notification_db_path() -> Path | None:
    modern = Path("~/Library/Group Containers/group.com.apple.usernoted/db2/db").expanduser()
    if modern.exists():
        return modern
    try:  # macOS 14 이하
        darwin = subprocess.run(["getconf", "DARWIN_USER_DIR"], capture_output=True,
                                text=True, timeout=2).stdout.strip()
        legacy = Path(darwin) / "com.apple.notificationcenter/db2/db"
        if legacy.exists():
            return legacy
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


FDA_HINT = ("알림을 읽을 수 없음. 시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한에서 "
            "이 터미널 앱을 켠 뒤 터미널을 다시 실행하세요.")


class NotificationReader:
    def __init__(self, path: Path | None = None):
        self.path = path or notification_db_path()
        self._sig: tuple | None = None
        self._cache: list[tuple[str, datetime, str, str, str]] = []

    def _signature(self) -> tuple:
        assert self.path
        parts = []
        for suffix in ("", "-wal"):
            p = Path(str(self.path) + suffix)
            try:
                st = p.stat()
                parts.append((st.st_mtime_ns, st.st_size))
            except OSError:
                parts.append(None)
        return tuple(parts)

    def read(self, sources: list[Source], hours: int, show_other: bool,
             limit: int = 300) -> tuple[list[Notification], str | None]:
        if self.path is None:
            return [], "알림 DB를 찾지 못함 (macOS 전용 기능)"
        try:
            with open(self.path, "rb"):
                pass
        except PermissionError:
            return [], FDA_HINT
        except OSError as e:
            return [], f"알림 DB 열기 실패: {e}"

        sig = self._signature()
        if sig != self._sig:
            try:
                self._cache = self._query(limit)
                self._sig = sig
            except sqlite3.Error as e:
                msg = str(e)
                if "authoriz" in msg or "unable to open" in msg:
                    return [], FDA_HINT
                return [], f"알림 DB 읽기 실패: {msg}"

        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        out: list[Notification] = []
        for bundle, when, title, subt, body in self._cache:
            if when < cutoff:
                continue
            fields = notif_fields(title, subt, body)
            # M1: 소스까지만 매칭한다. 하위 항목 매칭과 보낸 사람 추출은 M2(matching.py).
            src = next((s.name for s in sources
                        if not s.is_icampus and source_owns(s, bundle, fields)), None)
            if src is None and not show_other:
                continue
            out.append(Notification(when.astimezone(), bundle, src, title, subt, body))
        return out, None

    def _query(self, limit: int):
        uri = f"file:{self.path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=1)
        try:
            rows = conn.execute(
                "SELECT a.identifier, r.delivered_date, r.data FROM record r "
                "JOIN app a ON a.app_id = r.app_id "
                "ORDER BY r.delivered_date DESC LIMIT ?", (limit,)
            ).fetchall()
        finally:
            conn.close()
        result = []
        for bundle, delivered, blob in rows:
            try:
                d = plistlib.loads(blob)
            except Exception:
                continue
            req = d.get("req") or {}
            ts = delivered if delivered is not None else d.get("date")
            if ts is None:
                continue
            when = COCOA_EPOCH + timedelta(seconds=float(ts))
            result.append((
                str(bundle or d.get("app") or "?"), when,
                _clean(req.get("titl")), _clean(req.get("subt")), _clean(req.get("body")),
            ))
        return result


def _clean(v) -> str:
    return " ".join(str(v).split()) if v else ""


def list_notification_apps() -> tuple[list[tuple[str, int, str]], str | None]:
    """hud --doctor용: 알림 DB에 있는 번들 ID별 개수와 최근 제목."""
    path = notification_db_path()
    if path is None:
        return [], "알림 DB를 찾지 못함"
    reader = NotificationReader(path)
    try:
        rows = reader._query(2000)
    except (sqlite3.Error, PermissionError):
        return [], FDA_HINT
    stats: dict[str, list] = {}
    for bundle, _when, title, _s, body in rows:
        entry = stats.setdefault(bundle, [0, title or body])
        entry[0] += 1
    ordered = sorted(stats.items(), key=lambda kv: -kv[1][0])
    return [(b, n, t) for b, (n, t) in ordered], None


# ───────────────────────── 캘린더 · 미리알림 ─────────────────────────

_UNDEFINED = 2**63 - 1  # NSDateComponentUndefined


class EventKitReader:
    """EventKit(PyObjC)으로 캘린더 일정과 미리알림을 읽는다."""

    def __init__(self):
        try:
            import EventKit  # type: ignore
            import Foundation  # type: ignore
            self.ek, self.fd = EventKit, Foundation
            self.import_error = None
        except ImportError:
            self.ek = self.fd = None
            self.import_error = "pyobjc-framework-EventKit이 설치되지 않음 (install.sh를 다시 실행)"
        self.store = None
        self.events_ok = False
        self.reminders_ok = False
        self._store_born = 0.0

    def ensure_access(self) -> None:
        """권한 요청(처음 한 번 시스템 창이 뜸). 블로킹이므로 백그라운드 스레드에서 호출."""
        if self.ek is None:
            return
        ek = self.ek
        self.store = ek.EKEventStore.alloc().init()
        self.events_ok = self._request(ek.EKEntityTypeEvent)
        self.reminders_ok = self._request(ek.EKEntityTypeReminder)
        self._new_store()

    def _new_store(self):
        self.store = self.ek.EKEventStore.alloc().init()
        self._store_born = time.monotonic()

    def _request(self, entity) -> bool:
        ek = self.ek
        status = ek.EKEventStore.authorizationStatusForEntityType_(entity)
        if status == 3:  # fullAccess (구 authorized)
            return True
        if status in (1, 2):  # restricted, denied
            return False
        done, box = threading.Event(), {"ok": False}

        def handler(granted, _error):
            box["ok"] = bool(granted)
            done.set()

        name = ("requestFullAccessToEventsWithCompletion_" if entity == ek.EKEntityTypeEvent
                else "requestFullAccessToRemindersWithCompletion_")
        fn = getattr(self.store, name, None)
        if fn is not None:
            fn(handler)
        else:
            self.store.requestAccessToEntityType_completion_(entity, handler)
        done.wait(180)
        return box["ok"]

    def _refresh_store_if_old(self):
        if time.monotonic() - self._store_born > 300:
            self._new_store()

    def events(self, days: int, exclude: list[str]) -> tuple[list[Event], str | None]:
        if self.ek is None:
            return [], self.import_error
        if not self.events_ok:
            return [], "캘린더 권한 없음. 시스템 설정 → 개인정보 보호 및 보안 → 캘린더에서 이 터미널을 '전체 접근'으로 바꾸세요."
        self._refresh_store_if_old()
        start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=days)
        pred = self.store.predicateForEventsWithStartDate_endDate_calendars_(
            self._ns(start), self._ns(end), None)
        out = []
        for e in self.store.eventsMatchingPredicate_(pred) or []:
            cal = e.calendar()
            cal_name = str(cal.title()) if cal is not None else ""
            if cal_name in exclude:
                continue
            out.append(Event(
                title=str(e.title() or "(제목 없음)"),
                start=self._py(e.startDate()), end=self._py(e.endDate()),
                all_day=bool(e.isAllDay()), calendar=cal_name,
                location=str(e.location() or ""),
            ))
        out.sort(key=lambda ev: (ev.start, not ev.all_day))
        return out, None

    def reminders(self, exclude: list[str]) -> tuple[list[Todo], str | None]:
        if self.ek is None:
            return [], self.import_error
        if not self.reminders_ok:
            return [], "미리알림 권한 없음. 시스템 설정 → 개인정보 보호 및 보안 → 미리알림에서 이 터미널을 '전체 접근'으로 바꾸세요."
        self._refresh_store_if_old()
        pred = self.store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
            None, None, None)
        done, box = threading.Event(), {"items": []}

        def handler(items):
            box["items"] = list(items or [])
            done.set()

        self.store.fetchRemindersMatchingPredicate_completion_(pred, handler)
        if not done.wait(15):
            return [], "미리알림을 불러오는 데 시간이 너무 오래 걸림"
        cal = self.fd.NSCalendar.currentCalendar()
        out = []
        for r in box["items"]:
            lst = r.calendar()
            list_name = str(lst.title()) if lst is not None else ""
            if list_name in exclude:
                continue
            due, has_time = None, False
            comps = r.dueDateComponents()
            if comps is not None:
                nsdate = cal.dateFromComponents_(comps)
                if nsdate is not None:
                    due = self._py(nsdate)
                    has_time = comps.hour() != _UNDEFINED
            out.append(Todo(str(r.title() or "(제목 없음)"), due, has_time, list_name,
                            int(r.priority())))
        return out, None

    def _ns(self, dt: datetime):
        return self.fd.NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())

    @staticmethod
    def _py(nsdate) -> datetime:
        return datetime.fromtimestamp(nsdate.timeIntervalSince1970()).astimezone()


# ───────────────────────── Claude Code ─────────────────────────

def read_claude_sessions(max_age_hours: float = 24) -> tuple[list[ClaudeSession], str | None]:
    if not CLAUDE_STATE_DIR.exists():
        return [], "Claude Code hook이 아직 기록한 세션이 없음 (install.sh 실행 후 Claude Code를 다시 시작)"
    now = time.time()
    out = []
    for f in CLAUDE_STATE_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        updated = float(d.get("updated", 0))
        if now - updated > max_age_hours * 3600:
            f.unlink(missing_ok=True)
            continue
        out.append(ClaudeSession(
            session_id=d.get("session_id", f.stem), cwd=d.get("cwd") or "",
            state=d.get("state", "idle"), since=float(d.get("since", updated)),
            updated=updated, tool=d.get("tool") or "", message=d.get("message") or "",
            prompt=d.get("prompt") or "",
        ))
    order = {"permission": 0, "working": 1, "done": 2, "idle": 3}
    out.sort(key=lambda s: (order.get(s.state, 9), -s.updated))
    return out, None


def clear_finished_claude_sessions() -> int:
    n = 0
    for s in read_claude_sessions()[0]:
        if s.state in ("done", "idle"):
            (CLAUDE_STATE_DIR / f"{s.session_id}.json").unlink(missing_ok=True)
            n += 1
    return n


# ───────────────────────── 앱 열기 ─────────────────────────

def _spawn(cmd: list[str]) -> None:
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def open_url(url: str) -> None:
    if url:
        _spawn(["open", url])


def open_bundle(bundle_id: str) -> None:
    if bundle_id:
        _spawn(["open", "-b", bundle_id])


def open_source(src: Source) -> None:
    """소스 앱을 연다. process가 있으면 `open -a`, 없으면 구체 번들 ID로 `open -b`."""
    concrete = [b for b in src.bundle_ids if "*" not in b]
    if src.process:
        _spawn(["open", "-a", src.process])
    elif concrete:
        _spawn(["open", "-b", concrete[0]])


# ───────────────────────── 데모 데이터 ─────────────────────────

def demo_snapshot(sources: list[Source]) -> Snapshot:
    """4.1 배치 / nav_preview.png 와 비슷한 가짜 데이터. 소스 이름 기준으로 태깅한다."""
    now = datetime.now().astimezone()
    t0 = time.time()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def at(h, m=0, day=0):
        return today + timedelta(days=day, hours=h, minutes=m)

    def ago(minutes):
        return now - timedelta(minutes=minutes)

    def msg(source, child, minutes, sender, body):
        return Notification(ago(minutes), "demo", source, sender, "", body,
                            child=child, sender=sender)

    def social(source, child, minutes, body):
        return Notification(ago(minutes), "demo", source, "", "", body, child=child)

    notifications = [
        msg("Slack", None, 4, "김지훈 (#lab-general)",
            "내일 랩미팅 발표자료 금요일까지 드라이브에 올려주세요"),
        msg("카카오톡", "학생회 집행부", 1, "김민지", "회의록 올렸습니다. 확인 부탁드려요"),
        msg("카카오톡", "학생회 집행부", 6, "박준호", "예산안 수정본 금요일까지 받을게요"),
        msg("카카오톡", "학생회 집행부", 22, "이서연", "오늘 저녁 학생회실 열려있어?"),
        msg("카카오톡", "학생회 집행부", 95, "김민지", "다음 회의 목요일 7시로 확정"),
        msg("카카오톡", "랩 동기방", 15, "최유진", "오늘 점심 학식?"),
        msg("Discord", "#운영진", 47, "miseskorea #운영진", "가입 신청 4건 대기 중"),
        social("GroovSide", "Instagram", 60, "user_123님이 회원님의 게시물을 좋아합니다"),
        social("GroovSide", "Threads", 9, "새 답글 3개: 지난주 글에 대한 반론이 달렸어요"),
        msg("iCampus", None, 3, "[운영체제] 공지", "중간고사 성적 공개 및 이의신청 안내"),
        msg("iCampus", None, 180, "[확률과통계] 공지", "과제 제출 기한 연장 안내"),
    ]

    return Snapshot(
        badges={"Slack": "3", "카카오톡": "12", "Discord": "1", "GroovSide": "2", "Instagram": None},
        notifications=notifications,
        events=[
            Event("학부 수업 조교", at(9), at(10, 30), False, "학교", "공학관 204"),
            Event("랩미팅", now - timedelta(minutes=25), now + timedelta(minutes=35), False, "연구실", "302호"),
            Event("학생회 정기회의", now + timedelta(minutes=88), now + timedelta(minutes=148), False, "학생회", "학생회실"),
            Event("miseskorea 독서모임", at(20), at(21, 30), False, "miseskorea", "Discord 음성"),
            Event("논문 리딩 마감", at(0, 0, 1), at(0, 0, 2), True, "연구실"),
            Event("지도교수 면담", at(11, 0, 1), at(11, 30, 1), False, "연구실"),
        ],
        todos=[
            Todo("장학금 서류 제출", at(18, 0, -1), True, "학교", 1),
            Todo("과제 3 제출", at(23, 59), True, "학교", 5),
            Todo("실험 로그 정리", at(0), False, "연구실"),
            Todo("Discord 공지 작성", at(0, 0, 2), False, "miseskorea"),
            Todo("학생회 예산안 검토", at(0, 0, 4), False, "학생회"),
            Todo("책 반납", None, False, "개인"),
        ],
        claude=[
            ClaudeSession("a1", "/Users/me/research/thesis-exp", "permission", t0 - 190, t0 - 190,
                          tool="Bash", message="Claude needs your permission to use Bash"),
            ClaudeSession("b2", "/Users/me/code/miseskorea-web", "working", t0 - 72, t0 - 3,
                          tool="Edit", prompt="회원 가입 폼 검증 로직 고쳐줘"),
            ClaudeSession("c3", "/Users/me/code/hud", "done", t0 - 480, t0 - 480,
                          prompt="알림 패널 정렬 순서 바꿔줘"),
        ],
        icampus=[
            IcampusItem("강의", "운영체제", "10주차 동영상 강의", "1/2 시청",
                        now + timedelta(hours=2, minutes=50)),
            IcampusItem("과제", "확률과통계", "HW5 베이즈 추론", "미제출",
                        now + timedelta(hours=9, minutes=3)),
            IcampusItem("퀴즈", "미시경제학", "9주차 퀴즈", "미응시", at(23, 59, 1), due_2359=True),
            IcampusItem("과제", "운영체제", "Lab 4 스케줄러 구현", "미제출", at(18, 0, 3)),
            IcampusItem("강의", "확률과통계", "11주차 동영상 강의", "0/3 시청", at(23, 59, 6), due_2359=True),
            IcampusItem("과제", "대학글쓰기", "기말 보고서 초안", "제출 완료",
                        at(23, 59, 2), done=True, due_2359=True),
        ],
        updated=t0,
    )
