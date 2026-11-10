"""hud 설정 (`~/.hud/config.toml`, 버전 1) 읽기·검증·v0 호환.

순수 로직만 둔다 (Textual·수집기와 분리). 검증 실패는 `ConfigError`로 올리고,
메시지에는 파일 이름과 (가능하면) 줄 번호, 고치는 방법을 한국어로 적는다.
SPEC 8장 참고.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUD_HOME = Path(os.environ.get("HUD_HOME", "~/.hud")).expanduser()
CLAUDE_STATE_DIR = HUD_HOME / "claude"
CACHE_DIR = HUD_HOME / "cache"
STATE_PATH = HUD_HOME / "state.json"

MATCH_KEYS = {"title", "subtitle", "body", "thread", "any"}
SENDERS = {"title", "subtitle", "body_prefix", "none"}
KINDS = {"notifications", "icampus"}

# Rich가 아는 ANSI 색 이름 중 SPEC에서 쓰는 것들 + 밝은 변형. #RRGGBB도 허용.
_ANSI_COLORS = {
    "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white", "dim",
    "bright_black", "bright_red", "bright_green", "bright_yellow", "bright_blue",
    "bright_magenta", "bright_cyan", "bright_white",
}
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

GENERAL_KEYS = {
    "notification_hours", "show_other_apps", "calendar_days",
    "exclude_calendars", "exclude_reminder_lists", "theme",
}
APP_KEYS = {
    "name", "kind", "process", "bundle_ids", "match", "color", "only_children",
    "sender", "sender_sep", "url", "children",
}
CHILD_KEYS = {"name", "match", "url", "channel_id"}
ICAMPUS_KEYS = {
    "enabled", "base_url", "keychain_service", "poll_minutes", "days_ahead", "show_done_days",
}
DISCORD_KEYS = {"enabled", "keychain_service", "poll_seconds"}
TOP_KEYS = {"version", "general", "apps", "icampus", "discord_bot"}


class ConfigError(Exception):
    """설정 검증 실패. 메시지를 사용자에게 그대로 보여주고 종료한다."""


# ───────────────────────── 데이터 모델 ─────────────────────────

@dataclass
class Rule:
    """match의 키-값 하나. `regex`가 있으면 정규식, 없으면 대소문자 무시 부분 일치."""
    key: str
    pattern: str
    regex: re.Pattern | None = None

    def matches(self, fields: dict[str, str]) -> bool:
        text = fields.get(self.key, "")
        if self.regex is not None:
            return self.regex.search(text) is not None
        return self.pattern.lower() in text.lower()


@dataclass
class Match:
    """AND로 묶인 규칙들. 비어 있으면 '항상 참'이 아니라 '규칙 없음'(bool False)."""
    rules: list[Rule] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.rules)

    def matches(self, fields: dict[str, str]) -> bool:
        return all(r.matches(fields) for r in self.rules)


@dataclass
class Child:
    name: str
    match: Match
    url: str | None = None
    channel_id: str | None = None


@dataclass
class Source:
    name: str
    kind: str = "notifications"
    process: str = ""
    bundle_ids: list[str] = field(default_factory=list)
    match: Match | None = None
    color: str = "white"
    only_children: bool = False
    sender: str = "title"
    sender_sep: str = ": "
    url: str | None = None
    children: list[Child] = field(default_factory=list)

    @property
    def is_parent(self) -> bool:
        return bool(self.children)

    @property
    def is_icampus(self) -> bool:
        return self.kind == "icampus"


@dataclass
class IcampusConfig:
    enabled: bool = False
    base_url: str = "https://canvas.skku.edu"
    keychain_service: str = "hud.icampus"
    poll_minutes: int = 10
    days_ahead: int = 14
    show_done_days: int = 1


@dataclass
class DiscordConfig:
    enabled: bool = False
    keychain_service: str = "hud.discord"
    poll_seconds: int = 60


@dataclass
class Config:
    sources: list[Source] = field(default_factory=list)
    notification_hours: int = 48
    show_other_apps: bool = False
    calendar_days: int = 3
    exclude_calendars: list[str] = field(default_factory=list)
    exclude_reminder_lists: list[str] = field(default_factory=list)
    theme: str = "ansi-dark"
    icampus: IcampusConfig = field(default_factory=IcampusConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    is_v0: bool = False
    path: Path | None = None


# ───────────────────────── 읽기 ─────────────────────────

def load_config(path: Path | None = None) -> Config:
    """설정을 읽어 검증한다. 파일이 없으면 빈 기본 설정을 돌려준다.

    검증에 실패하면 ConfigError를 올린다 (호출 쪽에서 화면 띄우기 전에 잡는다).
    """
    candidates = [path] if path else [HUD_HOME / "config.toml", HERE / "config.toml"]
    chosen: Path | None = None
    text = ""
    for p in candidates:
        if p and p.exists():
            chosen = p
            text = p.read_text(encoding="utf-8")
            break
    if chosen is None:
        return Config()

    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{chosen}: TOML 문법 오류 — {e}") from e

    return _validate(raw, text, chosen)


def _line_of(text: str, needle: str, occurrence: int = 1) -> int | None:
    """needle이 occurrence번째로 나오는 줄 번호(1부터). 못 찾으면 None."""
    seen = 0
    for i, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            seen += 1
            if seen == occurrence:
                return i
    return None


def _loc(path: Path, text: str, needle: str, occurrence: int = 1) -> str:
    line = _line_of(text, needle, occurrence)
    return f"{path}:{line}" if line else str(path)


def _validate(raw: dict, text: str, path: Path) -> Config:
    is_v0 = "version" not in raw

    unknown = set(raw) - TOP_KEYS
    if unknown:
        key = sorted(unknown)[0]
        raise ConfigError(f"{_loc(path, text, key)}: 모르는 최상위 설정 '{key}'. "
                          f"쓸 수 있는 것: {', '.join(sorted(TOP_KEYS))}")

    if not is_v0 and raw.get("version") != 1:
        raise ConfigError(f"{_loc(path, text, 'version')}: version은 1이어야 합니다 "
                          f"(지금 {raw.get('version')!r}).")

    g = raw.get("general", {})
    if not is_v0:
        _reject_unknown(g, GENERAL_KEYS, "[general]", path, text)

    cfg = Config(
        notification_hours=int(g.get("notification_hours", 48)),
        show_other_apps=bool(g.get("show_other_apps", True if is_v0 else False)),
        calendar_days=int(g.get("calendar_days", 3)),
        exclude_calendars=list(g.get("exclude_calendars", [])),
        exclude_reminder_lists=list(g.get("exclude_reminder_lists", [])),
        theme=str(g.get("theme", "ansi-dark")),
        is_v0=is_v0,
        path=path,
    )

    seen_names: set[str] = set()
    for i, a in enumerate(raw.get("apps", [])):
        src = _source(a, i, is_v0, path, text)
        if src.name in seen_names:
            raise ConfigError(f"{_loc(path, text, src.name, 2)}: 앱 이름 '{src.name}'이 중복됩니다. "
                              f"이름은 서로 달라야 합니다.")
        seen_names.add(src.name)
        cfg.sources.append(src)

    ic = raw.get("icampus", {})
    _reject_unknown(ic, ICAMPUS_KEYS, "[icampus]", path, text)
    cfg.icampus = IcampusConfig(
        enabled=bool(ic.get("enabled", False)),
        base_url=str(ic.get("base_url", "https://canvas.skku.edu")),
        keychain_service=str(ic.get("keychain_service", "hud.icampus")),
        poll_minutes=int(ic.get("poll_minutes", 10)),
        days_ahead=int(ic.get("days_ahead", 14)),
        show_done_days=int(ic.get("show_done_days", 1)),
    )

    db = raw.get("discord_bot", {})
    _reject_unknown(db, DISCORD_KEYS, "[discord_bot]", path, text)
    cfg.discord = DiscordConfig(
        enabled=bool(db.get("enabled", False)),
        keychain_service=str(db.get("keychain_service", "hud.discord")),
        poll_seconds=int(db.get("poll_seconds", 60)),
    )
    return cfg


def _reject_unknown(section: dict, allowed: set[str], label: str, path: Path, text: str) -> None:
    unknown = set(section) - allowed
    if unknown:
        key = sorted(unknown)[0]
        raise ConfigError(f"{_loc(path, text, key)}: {label}의 모르는 설정 '{key}'. "
                          f"쓸 수 있는 것: {', '.join(sorted(allowed))}")


def _source(a: dict, index: int, is_v0: bool, path: Path, text: str) -> Source:
    if "name" not in a:
        raise ConfigError(f"{path}: {index + 1}번째 [[apps]]에 name이 없습니다.")
    name = str(a["name"])
    allowed = APP_KEYS | ({"key"} if is_v0 else set())  # v0의 key는 무시
    unknown = set(a) - allowed
    if unknown:
        key = sorted(unknown)[0]
        extra = " (v1에서는 숫자키를 쓰지 않습니다)" if key == "key" else ""
        raise ConfigError(f"{_loc(path, text, key)}: 앱 '{name}'의 모르는 설정 '{key}'{extra}. "
                          f"쓸 수 있는 것: {', '.join(sorted(APP_KEYS))}")

    kind = str(a.get("kind", "notifications"))
    if kind not in KINDS:
        raise ConfigError(f"{_loc(path, text, 'kind')}: 앱 '{name}'의 kind는 "
                          f"{' 또는 '.join(sorted(KINDS))} 여야 합니다 (지금 {kind!r}).")

    sender = str(a.get("sender", "title"))
    if sender not in SENDERS:
        raise ConfigError(f"{_loc(path, text, 'sender')}: 앱 '{name}'의 sender는 "
                          f"{', '.join(sorted(SENDERS))} 중 하나여야 합니다 (지금 {sender!r}).")

    color = str(a.get("color", "white"))
    _check_color(color, name, path, text)

    match = _match(a.get("match"), is_v0, f"앱 '{name}'", path, text)

    children = []
    child_names: set[str] = set()
    for c in a.get("children", []):
        child = _child(c, name, is_v0, path, text)
        if child.name in child_names:
            raise ConfigError(f"{_loc(path, text, child.name, 2)}: 앱 '{name}'의 하위 항목 "
                              f"'{child.name}'이 중복됩니다.")
        child_names.add(child.name)
        children.append(child)

    return Source(
        name=name, kind=kind, process=str(a.get("process", "")),
        bundle_ids=list(a.get("bundle_ids", [])), match=match, color=color,
        only_children=bool(a.get("only_children", False)), sender=sender,
        sender_sep=str(a.get("sender_sep", ": ")), url=a.get("url"), children=children,
    )


def _child(c: dict, source_name: str, is_v0: bool, path: Path, text: str) -> Child:
    if "name" not in c:
        raise ConfigError(f"{path}: 앱 '{source_name}'의 하위 항목에 name이 없습니다.")
    name = str(c["name"])
    unknown = set(c) - CHILD_KEYS
    if unknown:
        key = sorted(unknown)[0]
        raise ConfigError(f"{_loc(path, text, key)}: 하위 항목 '{name}'의 모르는 설정 '{key}'. "
                          f"쓸 수 있는 것: {', '.join(sorted(CHILD_KEYS))}")
    if "match" not in c:
        raise ConfigError(f"{path}: 하위 항목 '{name}'에 match가 없습니다.")
    match = _match(c["match"], is_v0, f"하위 항목 '{name}'", path, text)
    return Child(name=name, match=match, url=c.get("url"), channel_id=c.get("channel_id"))


def _match(value, is_v0: bool, who: str, path: Path, text: str) -> Match:
    if value is None:
        return Match()
    if isinstance(value, str):
        if not is_v0:
            raise ConfigError(f"{_loc(path, text, 'match')}: {who}의 match는 "
                              f'{{ any = "..." }} 형식이어야 합니다 (문자열은 v0 형식).')
        value = {"any": value}  # v0 호환: 문자열 → any
    if not isinstance(value, dict):
        raise ConfigError(f"{_loc(path, text, 'match')}: {who}의 match 형식이 올바르지 않습니다.")

    rules = []
    for key, pat in value.items():
        if key not in MATCH_KEYS:
            raise ConfigError(f"{_loc(path, text, key)}: {who}의 match 키 '{key}'는 쓸 수 없습니다. "
                              f"쓸 수 있는 것: {', '.join(sorted(MATCH_KEYS))}")
        pat = str(pat)
        regex = None
        if pat.startswith("re:"):
            try:
                regex = re.compile(pat[3:], re.IGNORECASE)
            except re.error as e:
                raise ConfigError(f"{_loc(path, text, pat)}: {who}의 정규식이 올바르지 않습니다 — {e}") from e
        rules.append(Rule(key=key, pattern=pat[3:] if regex else pat, regex=regex))
    return Match(rules=rules)


def _check_color(color: str, name: str, path: Path, text: str) -> None:
    if color in _ANSI_COLORS or _HEX_RE.match(color):
        return
    raise ConfigError(f"{_loc(path, text, color)}: 앱 '{name}'의 color '{color}'를 알 수 없습니다. "
                      f"ANSI 색 이름(red, green, …)이나 #RRGGBB를 쓰세요.")
