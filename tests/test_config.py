"""설정 파서·검증·v0 호환 테스트 (SPEC 8장, 13장)."""
from __future__ import annotations

from pathlib import Path

import pytest

from config import ConfigError, load_config

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_v1_example_loads():
    """저장소의 config.toml(v1 예시)이 통과한다."""
    cfg = load_config(ROOT / "config.toml")
    assert not cfg.is_v0
    assert [s.name for s in cfg.sources] == ["Slack", "카카오톡", "Discord", "GroovSide", "Instagram", "iCampus"]
    kakao = cfg.sources[1]
    assert not kakao.only_children          # 전부 수신 (오픈채팅은 카톡 앱에서 음소거)
    assert kakao.children == []             # 지정 방 하위 항목 없음
    assert cfg.show_other_apps is False
    assert cfg.icampus.enabled
    # 정규식 match가 컴파일되었는지 (GroovSide › X)
    x = cfg.sources[3].children[2]
    assert x.match.rules[0].regex is not None


def test_regex_match_applies():
    cfg = load_config(ROOT / "config.toml")
    x = cfg.sources[3].children[2]
    assert x.match.matches({"any": "글이 twitter 에서", "title": "", "subtitle": "", "body": "", "thread": ""})
    assert not x.match.matches({"any": "instagram 좋아요", "title": "", "subtitle": "", "body": "", "thread": ""})


def test_unknown_general_field(tmp_path):
    p = write(tmp_path, "version = 1\n[general]\nnope = 1\n")
    with pytest.raises(ConfigError) as e:
        load_config(p)
    assert "nope" in str(e.value)


def test_unknown_app_field(tmp_path):
    p = write(tmp_path, 'version = 1\n[[apps]]\nname = "A"\nweird = 1\n')
    with pytest.raises(ConfigError) as e:
        load_config(p)
    assert "weird" in str(e.value)


def test_key_field_rejected_in_v1(tmp_path):
    p = write(tmp_path, 'version = 1\n[[apps]]\nname = "A"\nkey = "1"\n')
    with pytest.raises(ConfigError) as e:
        load_config(p)
    assert "key" in str(e.value)


def test_duplicate_name(tmp_path):
    p = write(tmp_path, 'version = 1\n[[apps]]\nname = "A"\n[[apps]]\nname = "A"\n')
    with pytest.raises(ConfigError) as e:
        load_config(p)
    assert "중복" in str(e.value)


def test_bad_regex(tmp_path):
    p = write(tmp_path, 'version = 1\n[[apps]]\nname = "A"\nmatch = { any = "re:(" }\n')
    with pytest.raises(ConfigError) as e:
        load_config(p)
    assert "정규식" in str(e.value)


def test_bad_kind(tmp_path):
    p = write(tmp_path, 'version = 1\n[[apps]]\nname = "A"\nkind = "weird"\n')
    with pytest.raises(ConfigError):
        load_config(p)


def test_bad_sender(tmp_path):
    p = write(tmp_path, 'version = 1\n[[apps]]\nname = "A"\nsender = "weird"\n')
    with pytest.raises(ConfigError):
        load_config(p)


def test_string_match_rejected_in_v1(tmp_path):
    p = write(tmp_path, 'version = 1\n[[apps]]\nname = "A"\nmatch = "instagram"\n')
    with pytest.raises(ConfigError) as e:
        load_config(p)
    assert "match" in str(e.value)


def test_child_requires_match(tmp_path):
    p = write(tmp_path, 'version = 1\n[[apps]]\nname = "A"\n  [[apps.children]]\n  name = "c"\n')
    with pytest.raises(ConfigError):
        load_config(p)


def test_v0_compat(tmp_path):
    """version 없음 = v0. key 무시, 문자열 match → any 규칙, show_other_apps 기본 True."""
    text = (
        '[general]\nnotification_hours = 24\n'
        '[[apps]]\nname = "Slack"\nkey = "1"\nprocess = "Slack"\n'
        'bundle_ids = ["com.tinyspeck.slackmacgap"]\ncolor = "magenta"\n'
        '[[apps]]\nname = "Insta"\nkey = "2"\nmatch = "instagram"\nbundle_ids = ["com.google.Chrome"]\n'
    )
    p = write(tmp_path, text)
    cfg = load_config(p)
    assert cfg.is_v0
    assert cfg.notification_hours == 24
    assert cfg.show_other_apps is True  # v0 기본값
    insta = cfg.sources[1]
    assert insta.match is not None
    assert insta.match.rules[0].key == "any"
    assert insta.match.rules[0].pattern == "instagram"


def test_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.sources == []
    assert cfg.is_v0 is False


def test_toml_syntax_error(tmp_path):
    p = write(tmp_path, "version = = 1\n")
    with pytest.raises(ConfigError) as e:
        load_config(p)
    assert "TOML" in str(e.value)
