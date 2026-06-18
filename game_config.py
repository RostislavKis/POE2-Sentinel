"""
Game-config connector — read Path of Exile 2's own settings.

Reads ``poe2_production_Config.ini`` (the game's settings file) and the latest
crash-dump log to surface information POE2 Sentinel can use:

- screen resolution + window mode  -> validate OCR regions / overlay scale
- flask keybinds (slots 1..5)       -> auto-configure the flask bot's keys
- input mode (KBM vs gamepad)       -> warn that keyboard automation may not
                                       register while the game is in gamepad mode
- UI language                       -> caveat for window-title detection
- game build revision               -> detect when a patch likely broke offsets

This module is READ-ONLY with respect to the game; it only reads text files the
game itself writes. Nothing here touches game memory.
"""

import os
import glob
import json
import logging
import configparser
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger("poe2sentinel.game_config")

CONFIG_FILE_NAME = "poe2_production_Config.ini"

# The offsets shipped in terrain_reader.Poe2Offsets / flask_bot.StructureReader
# were last validated against this game build. If the live build differs, a patch
# may have shifted offsets/AOB patterns.
LAST_VALIDATED_BUILD = "4.5.2/311743"

# Windows virtual-key code -> `keyboard` library key name (covers what flask
# slots realistically use; unknown codes return None).
_VK_NAMES: Dict[int, str] = {
    0x08: "backspace", 0x09: "tab", 0x0D: "enter", 0x1B: "esc", 0x20: "space",
    0x21: "page up", 0x22: "page down", 0x23: "end", 0x24: "home",
    0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x2D: "insert", 0x2E: "delete",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/",
    0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}
_VK_NAMES.update({c: chr(c).lower() for c in range(0x30, 0x3A)})   # 0-9
_VK_NAMES.update({c: chr(c).lower() for c in range(0x41, 0x5B)})   # A-Z
_VK_NAMES.update({0x70 + i: f"f{i + 1}" for i in range(24)})        # F1-F24
_VK_NAMES.update({0x60 + i: str(i) for i in range(10)})            # numpad 0-9 -> digit


def vk_to_key_name(vk: int) -> Optional[str]:
    """Map a Windows virtual-key code to a `keyboard`-library key name."""
    return _VK_NAMES.get(int(vk))


@dataclass
class GameConfig:
    """Subset of PoE2 settings relevant to POE2 Sentinel."""
    ini_path: Optional[str] = None
    resolution: Optional[Tuple[int, int]] = None   # (width, height)
    windowed: bool = True
    borderless: bool = False
    input_mode: str = ""                            # "mouse_and_keyboard" / "gamepad"
    auto_input_switching: bool = False
    language: str = ""
    use_wasd: bool = False
    flask_keys: Dict[int, str] = field(default_factory=dict)  # slot (1..5) -> key name
    build: Optional[str] = None                     # e.g. "4.5.2/311743"

    @property
    def is_gamepad(self) -> bool:
        return self.input_mode == "gamepad"

    @property
    def build_matches_validated(self) -> Optional[bool]:
        """True/False if the build is known, None if it could not be read."""
        if not self.build:
            return None
        return self.build.split("/")[-1] == LAST_VALIDATED_BUILD.split("/")[-1]


def _documents_dir() -> Optional[str]:
    """Resolve the user's Documents folder, honouring OneDrive/localized redirects."""
    candidates: List[str] = []
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            personal, _ = winreg.QueryValueEx(handle, "Personal")
            if personal:
                candidates.append(os.path.expandvars(personal))
    except OSError:
        pass
    one_drive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if one_drive:
        candidates += [os.path.join(one_drive, "Documents"),
                       os.path.join(one_drive, "Документы")]
    home = os.path.expanduser("~")
    candidates += [os.path.join(home, "Documents"), os.path.join(home, "Документы")]
    for path in candidates:
        if path and os.path.isdir(path):
            return path
    return None


def find_settings_dir() -> Optional[str]:
    """Locate the PoE2 settings directory (``My Games/Path of Exile 2``)."""
    docs = _documents_dir()
    if not docs:
        return None
    settings = os.path.join(docs, "My Games", "Path of Exile 2")
    return settings if os.path.isdir(settings) else None


def find_config_ini() -> Optional[str]:
    """Return the path to ``poe2_production_Config.ini`` if it exists."""
    settings = find_settings_dir()
    if not settings:
        return None
    path = os.path.join(settings, CONFIG_FILE_NAME)
    return path if os.path.isfile(path) else None


def _latest_build(settings_dir: str) -> Optional[str]:
    """Best-effort: read the game build from the most recent crash-dump log."""
    logs = glob.glob(os.path.join(settings_dir, "poe2_production", "*.dmp.log.txt"))
    if not logs:
        return None
    newest = max(logs, key=os.path.getmtime)
    version = revision = None
    try:
        with open(newest, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if version is None and "tags/" in line:
                    # "... User agent: PoE poe2_production/tags/4.5.2 Windows x64"
                    after = line.split("tags/", 1)[1].strip().split()
                    if after:
                        version = after[0]
                if revision is None and "Build Revision:" in line:
                    revision = line.split("Build Revision:", 1)[1].strip().split()[0]
                if version and revision:
                    break
    except OSError:
        return None
    if version and revision:
        return f"{version}/{revision}"
    return version or revision


def active_build_paths(ini_path: Optional[str] = None) -> List[str]:
    """Return existing `.build` file paths referenced by the game's active builds.

    Reads ``[UI] active_builds`` (JSON the game writes) and returns the build-plan
    files it points at. Falls back to the newest files in ``BuildPlanner/`` if the
    active list is empty or unreadable.
    """
    path = ini_path or find_config_ini()
    paths: List[str] = []
    if path and os.path.isfile(path):
        parser = configparser.ConfigParser(interpolation=None, delimiters=("=",),
                                           strict=False)
        try:
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as fh:
                parser.read_file(fh)
            raw = _get(parser, "UI", "active_builds")
            if raw:
                data = json.loads(raw)
                for entry in data.get("characters_to_builds", []):
                    bp = entry.get("buildpath")
                    if bp and os.path.isfile(bp) and bp not in paths:
                        paths.append(bp)
        except (OSError, configparser.Error, json.JSONDecodeError, ValueError) as e:
            logger.debug("Could not read active_builds: %s", e)

    if not paths:
        settings = find_settings_dir()
        if settings:
            found = glob.glob(os.path.join(settings, "BuildPlanner", "*.build"))
            paths = sorted(found, key=os.path.getmtime, reverse=True)
    return paths


def _get_bool(parser: configparser.ConfigParser, section: str, key: str,
              default: bool = False) -> bool:
    try:
        return parser.getboolean(section, key)
    except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
        return default


def _get(parser: configparser.ConfigParser, section: str, key: str,
         default: str = "") -> str:
    try:
        return parser.get(section, key)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return default


def read_game_config(ini_path: Optional[str] = None) -> Optional[GameConfig]:
    """Parse the game config. Returns None if it cannot be found/read."""
    path = ini_path or find_config_ini()
    if not path or not os.path.isfile(path):
        logger.info("PoE2 game config not found")
        return None

    # `:` is allowed inside values (paths/JSON), so only split on `=`; disable
    # interpolation so stray `%` cannot raise.
    parser = configparser.ConfigParser(interpolation=None, delimiters=("=",),
                                       strict=False)
    try:
        # utf-8-sig strips a leading BOM (the game writes one).
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as fh:
            parser.read_file(fh)
    except (OSError, configparser.Error) as e:
        logger.warning("Failed to parse %s: %s", path, e)
        return None

    cfg = GameConfig(ini_path=path)

    # Resolution / window mode
    try:
        w = parser.getint("DISPLAY", "resolution_width")
        h = parser.getint("DISPLAY", "resolution_height")
        cfg.resolution = (w, h)
    except (configparser.Error, ValueError):
        cfg.resolution = None
    cfg.windowed = not _get_bool(parser, "DISPLAY", "fullscreen", False)
    cfg.borderless = _get_bool(parser, "DISPLAY", "borderless_windowed_fullscreen", False)

    cfg.input_mode = _get(parser, "GENERAL", "user_input_mode")
    cfg.auto_input_switching = _get_bool(parser, "GENERAL", "auto_input_method_switching", False)
    cfg.language = _get(parser, "LANGUAGE", "language")
    cfg.use_wasd = _get_bool(parser, "UI", "use_wasd_to_move", False)

    # Flask binds live in the active movement scheme's section.
    keys_section = "WASD_ACTION_KEYS" if cfg.use_wasd else "ACTION_KEYS"
    for slot in range(1, 6):
        raw = _get(parser, keys_section, f"use_flask_in_slot{slot}", "0")
        # Values look like "49" or sometimes "49 2" (key + modifier index).
        token = raw.strip().split()[0] if raw.strip() else "0"
        try:
            vk = int(token)
        except ValueError:
            continue
        if vk:
            name = vk_to_key_name(vk)
            if name:
                cfg.flask_keys[slot] = name

    settings_dir = os.path.dirname(path)
    cfg.build = _latest_build(settings_dir)

    return cfg


def apply_to_app_config(app_config: dict, game: GameConfig) -> List[str]:
    """Apply game settings onto POE2 Sentinel's config dict in place.

    Sets the flask bot's life/mana keys from the game's flask binds (slot 1 -> life,
    slot 2 -> mana) and validates OCR regions against the live resolution.
    Returns a list of human-readable change/warning messages (Russian).
    """
    messages: List[str] = []

    # Flask keys: slot 1 -> life, slot 2 -> mana (the bot's two-resource model).
    life_key = game.flask_keys.get(1)
    mana_key = game.flask_keys.get(2)
    if life_key:
        app_config.setdefault("life", {})
        if app_config["life"].get("flask_key") != life_key:
            app_config["life"]["flask_key"] = life_key
            messages.append(f"Клавиша лайф-фласки → «{life_key}» (слот 1 в игре)")
    if mana_key:
        app_config.setdefault("mana", {})
        if app_config["mana"].get("flask_key") != mana_key:
            app_config["mana"]["flask_key"] = mana_key
            messages.append(f"Клавиша мана-фласки → «{mana_key}» (слот 2 в игре)")
    if not life_key and not mana_key:
        messages.append("В игре не назначены клавиши фласок (слоты 1–2) — оставил как есть")

    # OCR-region sanity vs the live resolution.
    if game.resolution:
        w, h = game.resolution
        for res_name, label in (("life", "лайф"), ("mana", "мана")):
            region = app_config.get(res_name, {}).get("region")
            if not region:
                continue
            r = region
            if (r.get("left", 0) + r.get("width", 0) > w
                    or r.get("top", 0) + r.get("height", 0) > h):
                messages.append(
                    f"OCR-регион «{label}» выходит за пределы экрана {w}×{h} — "
                    "перенастрой его для текущего разрешения"
                )

    # Gamepad caveat. In PoE2 keyboard flask keys still fire while on a
    # controller, so automation works *if* the flasks are bound on the keyboard.
    if game.is_gamepad:
        if life_key or mana_key:
            note = ("Игра в режиме ГЕЙМПАДА, но фласки привязаны и к клавиатуре "
                    f"({life_key or '—'}/{mana_key or '—'}) — бот должен работать.")
            if game.auto_input_switching:
                note += (" Включён авто-переключатель ввода: при нажатии возможны "
                         "кратковременные KBM-подсказки в HUD.")
            messages.append(note)
        else:
            messages.append(
                "Игра в режиме ГЕЙМПАДА и фласки НЕ привязаны к клавиатуре — "
                "привяжи их на клавиши 1–5, иначе бот не сможет жать фласки."
            )

    # Build / offsets caveat.
    if game.build:
        if game.build_matches_validated is False:
            messages.append(
                f"Билд игры {game.build} ≠ проверенного {LAST_VALIDATED_BUILD}: "
                "оффсеты могли измениться после патча — проверь Structure-режим."
            )

    return messages
