"""iCampus(Canvas) 수집 — API 호출·항목 변환·캐시 (SPEC 7.6).

순수 로직(변환·상태 매핑)과 네트워크를 나눠 두었다. 네트워크 대상은 `base_url`
호스트 하나뿐이고, 어떤 함수도 예외를 밖으로 던지지 않는다((데이터, 오류) 반환).
비밀값(토큰)은 키체인에서만 읽고 로그·출력에 남기지 않는다.
"""
from __future__ import annotations

import json
import os
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from collectors import IcampusItem, Notification
from config import CACHE_DIR, IcampusConfig

CACHE_PATH = CACHE_DIR / "icampus.json"

# 표준 Canvas planner의 plannable_type → hud 종류. 동영상 강의는 LearningX라 여기 없음(SPEC 7.6.4).
KIND_MAP = {"assignment": "과제", "quiz": "퀴즈", "discussion_topic": "토론"}

_SYSTEM_CA_PATHS = ("/etc/ssl/cert.pem", "/private/etc/ssl/cert.pem")


# ───────────────────────── 토큰 (키체인) ─────────────────────────

def get_token(service: str) -> str | None:
    """키체인에서 iCampus 토큰을 읽는다. 없으면 None. 값은 절대 로그에 남기지 않는다."""
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    tok = out.stdout.strip()
    return tok or None


# ───────────────────────── SSL (CA 폴백) ─────────────────────────

def make_ssl_context() -> ssl.SSLContext:
    """시스템 CA가 없는 인터프리터(python.org 빌드 등)를 위해 시스템 번들을 폴백 로드한다."""
    ctx = ssl.create_default_context()
    try:
        if not ctx.get_ca_certs():
            for p in _SYSTEM_CA_PATHS:
                if os.path.exists(p):
                    ctx.load_verify_locations(p)
                    break
    except ssl.SSLError:
        pass
    return ctx


# ───────────────────────── 순수 변환 ─────────────────────────

def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def is_2359(due: datetime | None) -> bool:
    if due is None:
        return False
    d = due.astimezone()
    return d.hour == 23 and d.minute == 59


def status_of(ptype: str, submissions) -> tuple[str, bool]:
    """(상태 문구, 완료 여부). submissions는 dict이거나 False (미제출)일 수 있다 (SPEC 7.6.3)."""
    s = submissions if isinstance(submissions, dict) else {}
    submitted, graded = s.get("submitted"), s.get("graded")
    late, missing = s.get("late"), s.get("missing")
    if ptype == "assignment":
        if graded:
            return "채점 완료", True
        if submitted:
            return ("지각 제출" if late else "제출 완료"), True
        _ = missing  # missing이면 SPEC상 빨강이지만 상태 문구는 동일
        return "미제출", False
    if ptype == "quiz":
        if submitted or graded:
            return "응시 완료", True
        return "미응시", False
    if ptype == "discussion_topic":
        if submitted or graded:
            return "참여 완료", True
        return "미참여", False
    return "", False


def to_items_and_announcements(
    raw_items: list, now: datetime, days_ahead: int, source_name: str
) -> tuple[list[IcampusItem], list[Notification]]:
    """planner 응답을 마감 항목(IcampusItem)과 공지(Notification)로 나눈다 (SPEC 7.6.3).

    공지는 최근 14일, 마감 항목은 days_ahead 안쪽. 완료/오래된 것 추가 필터는 렌더가 한다.
    """
    horizon = now + timedelta(days=days_ahead)
    ann_cut = now - timedelta(days=14)
    items: list[IcampusItem] = []
    anns: list[Notification] = []
    for it in raw_items:
        ptype = it.get("plannable_type")
        pl = it.get("plannable") or {}
        course = it.get("context_name") or ""
        if ptype == "announcement":
            when = parse_dt(it.get("plannable_date")) or parse_dt(pl.get("created_at"))
            if when is None or when < ann_cut:
                continue
            subject = pl.get("title") or "(제목 없음)"
            anns.append(Notification(
                when.astimezone(), "icampus", source_name,
                f"[{course}] 공지", "", subject,
            ))
            continue
        if ptype not in KIND_MAP:
            continue
        due = parse_dt(pl.get("due_at")) or parse_dt(it.get("plannable_date"))
        if due is not None and due > horizon:
            continue
        status, done = status_of(ptype, it.get("submissions"))
        items.append(IcampusItem(
            kind=KIND_MAP[ptype], course=course,
            title=pl.get("title") or "(제목 없음)", status=status,
            due=due.astimezone() if due else None, done=done,
            due_2359=is_2359(due), html_url=it.get("html_url") or "",
        ))
    return items, anns


# ───────────────────────── 캐시 ─────────────────────────

def _items_to_json(items: list[IcampusItem], anns: list[Notification]) -> dict:
    return {
        "fetched_at": datetime.now(UTC).timestamp(),
        "items": [{
            "kind": it.kind, "course": it.course, "title": it.title,
            "status": it.status, "due": it.due.isoformat() if it.due else None,
            "done": it.done, "due_2359": it.due_2359, "html_url": it.html_url,
        } for it in items],
        "announcements": [{
            "when": n.when.isoformat(), "course": n.title, "subject": n.body,
        } for n in anns],
    }


def _json_to_items(d: dict, source_name: str) -> tuple[list[IcampusItem], list[Notification]]:
    items = [IcampusItem(
        kind=x["kind"], course=x["course"], title=x["title"], status=x["status"],
        due=parse_dt(x.get("due")), done=x.get("done", False),
        due_2359=x.get("due_2359", False), html_url=x.get("html_url", ""),
    ) for x in d.get("items", [])]
    anns = []
    for x in d.get("announcements", []):
        when = parse_dt(x.get("when")) or datetime.now(UTC)
        anns.append(Notification(when.astimezone(), "icampus", source_name,
                                 x.get("course", ""), "", x.get("subject", "")))
    return items, anns


def save_cache(items: list[IcampusItem], anns: list[Notification], path=None) -> None:
    path = path or CACHE_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_items_to_json(items, anns), ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def load_cache(source_name: str, path=None) -> tuple[list[IcampusItem], list[Notification]]:
    path = path or CACHE_PATH
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], []
    try:
        return _json_to_items(d, source_name)
    except (KeyError, TypeError):
        return [], []


# ───────────────────────── HTTP ─────────────────────────

def _next_link(header: str | None) -> str | None:
    """Canvas Link 헤더에서 rel="next" URL을 뽑는다."""
    if not header:
        return None
    for part in header.split(","):
        seg = part.split(";")
        if len(seg) < 2:
            continue
        url = seg[0].strip().strip("<>")
        rels = ";".join(seg[1:]).replace(" ", "")
        if 'rel="next"' in rels or "rel=next" in rels:
            return url
    return None


# ───────────────────────── 클라이언트 ─────────────────────────

@dataclass
class _Probe:
    status: int | None
    error: str | None


def check_auth(cfg: IcampusConfig) -> _Probe:
    """`--doctor`용: GET /api/v1/users/self 상태 코드만. 토큰 값은 출력하지 않는다."""
    token = get_token(cfg.keychain_service)
    if not token:
        return _Probe(None, f'키체인에 토큰 없음 — security add-generic-password -a "$USER" -s {cfg.keychain_service} -w')
    client = IcampusClient(cfg, "iCampus")
    data, nxt, err = client._get(cfg.base_url.rstrip("/") + "/api/v1/users/self", token)
    if err:
        return _Probe(None, err)
    ok = isinstance(data, dict) and "id" in data
    return _Probe(200 if ok else 0, None if ok else "토큰이 거부됨 — canvas.skku.edu에서 다시 발급하세요")


class IcampusClient:
    """수집 스레드에서만 쓴다 (UI 스레드 금지). poll()은 캐시를 즉시 돌려주고 때가 되면 갱신한다."""

    def __init__(self, cfg: IcampusConfig, source_name: str):
        self.cfg = cfg
        self.source_name = source_name
        self._ctx = make_ssl_context()
        self._host = urllib.parse.urlparse(cfg.base_url).hostname or ""
        self._items: list[IcampusItem] = []
        self._anns: list[Notification] = []
        self._loaded = False
        self._next_at = 0.0
        self._fail = 0
        self._last_error: str | None = None

    def poll(self, mono: float) -> tuple[list[IcampusItem], list[Notification], str | None]:
        if not self.cfg.enabled:
            return [], [], None
        if not self._loaded:
            self._items, self._anns = load_cache(self.source_name)
            self._loaded = True
        if mono < self._next_at:
            return self._items, self._anns, self._last_error

        token = get_token(self.cfg.keychain_service)
        if not token:
            self._last_error = ("iCampus 토큰이 없음. "
                                f'security add-generic-password -a "$USER" -s {self.cfg.keychain_service} -w '
                                "로 키체인에 넣으세요.")
            self._next_at = mono + 300
            return self._items, self._anns, self._last_error

        raw, err = self._fetch_planner(token)
        if err:
            self._fail += 1
            self._next_at = mono + min(30 * 60, 120 * (2 ** (self._fail - 1)))  # 2,4,8…30분
            self._last_error = err
            return self._items, self._anns, err  # 실패해도 캐시 유지 (SPEC 7.6.2)

        self._fail = 0
        self._last_error = None
        self._items, self._anns = to_items_and_announcements(
            raw, datetime.now(UTC), self.cfg.days_ahead, self.source_name)
        save_cache(self._items, self._anns)
        self._next_at = mono + self.cfg.poll_minutes * 60
        return self._items, self._anns, None

    def _fetch_planner(self, token: str) -> tuple[list | None, str | None]:
        now = datetime.now(UTC)
        start = (now - timedelta(days=14)).date().isoformat()
        end = (now + timedelta(days=self.cfg.days_ahead)).date().isoformat()
        url = (self.cfg.base_url.rstrip("/") +
               f"/api/v1/planner/items?start_date={start}&end_date={end}&per_page=100")
        out: list = []
        for _ in range(10):  # 최대 10쪽
            data, nxt, err = self._get(url, token)
            if err:
                return None, err
            if isinstance(data, list):
                out.extend(data)
            if not nxt or urllib.parse.urlparse(nxt).hostname != self._host:
                break  # 호스트가 다른 next는 따라가지 않음 (네트워크 대상은 base_url 하나)
            url = nxt
        return out, None

    def _get(self, url: str, token: str) -> tuple[object, str | None, str | None]:
        """(data, next_url, error). 예외를 던지지 않는다."""
        if urllib.parse.urlparse(url).hostname != self._host:
            return None, None, "iCampus 요청 대상이 base_url 호스트가 아님"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=10, context=self._ctx) as r:
                body = r.read().decode("utf-8")
                if body.startswith("while(1);"):
                    body = body[len("while(1);"):]
                return json.loads(body), _next_link(r.headers.get("Link")), None
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return None, None, f"iCampus 토큰이 거부됨(HTTP {e.code}). canvas.skku.edu에서 토큰을 다시 발급해 키체인에 넣으세요."
            return None, None, f"iCampus 응답 오류 (HTTP {e.code})"
        except urllib.error.URLError as e:
            reason = str(getattr(e, "reason", e))
            if "CERTIFICATE" in reason.upper() or "SSL" in reason.upper():
                return None, None, ("iCampus 연결의 CA 인증서를 찾지 못함. python.org Python이면 "
                                    "'Install Certificates.command'를 실행하거나 시스템 Python을 쓰세요.")
            return None, None, f"iCampus에 연결하지 못함: {reason}"
        except (TimeoutError, ssl.SSLError) as e:
            return None, None, f"iCampus 연결 실패: {e}"
        except (ValueError, UnicodeDecodeError):
            return None, None, "iCampus 응답을 해석하지 못함"
