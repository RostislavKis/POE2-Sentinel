"""
Build guide (T1) — parse Path of Exile 2 ``.build`` plans into a readable,
Russian-language guide: target gear + desired stats per slot, active skills with
their support gems, and the passive list.

The ``.build`` files are GGG's in-game Build Planner JSON. The active build is
discovered from the game's own config (``active_builds``). This module is purely
local — it reads the plan files the user already has; it does not touch game
memory or the network.

Recommendation source: the plan itself (it is normally exported from a guide on
maxroll.gg / mobalytics.gg, so the "best" stats are already baked into it).
Passive *node names* are internal ids (e.g. ``projectiles15``) — turning those
into readable names needs a PoE2 passive-tree name table we don't ship yet, so
passives are listed by id with a note for now.
"""

import re
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import game_config

logger = logging.getLogger("poe2sentinel.build_guide")

REFERENCE_LINKS = ("https://maxroll.gg/poe2/", "https://mobalytics.gg/poe-2/")

# Equipment slot id -> Russian label.
SLOT_RU = {
    "Weapon1": "Оружие", "Weapon2": "Оружие (своп)",
    "Offhand1": "Левая рука", "Offhand2": "Левая рука (своп)",
    "Helm1": "Шлем", "BodyArmour1": "Нагрудник", "Gloves1": "Перчатки",
    "Boots1": "Ботинки", "Amulet1": "Амулет", "Belt1": "Пояс",
    "Ring1": "Кольцо 1", "Ring2": "Кольцо 2",
    "Flask1": "Фласки",
}
_SLOT_ORDER = ["Weapon1", "Offhand1", "Weapon2", "Offhand2", "Helm1", "BodyArmour1",
               "Gloves1", "Boots1", "Amulet1", "Ring1", "Ring2", "Belt1", "Flask1"]

# Ascendancy internal name -> Russian.
ASCENDANCY_RU = {
    "Huntress1": "Охотница", "Huntress2": "Охотница",
    "Warrior1": "Воин", "Warrior2": "Воин",
    "Ranger1": "Следопыт", "Ranger2": "Следопыт",
    "Witch1": "Ведьма", "Witch2": "Ведьма",
    "Monk1": "Монах", "Monk2": "Монах",
    "Mercenary1": "Наёмник", "Mercenary2": "Наёмник",
    "Sorceress1": "Чародейка", "Sorceress2": "Чародейка",
}

# Gem leaf name (after stripping path + Skill/SupportGem prefix) -> Russian.
GEM_RU = {
    "LightningSpear": "Молниеносное копьё",
    "ExplosiveSpear": "Взрывное копьё",
    "StormLance": "Грозовая пика",
    "HeraldOfThunder": "Вестник грома",
    "FrostBomb": "Морозная бомба",
    "CullTheWeak": "Добивание слабых",
    "Innervate": "Иннервация",
    "LightningInfusion": "Наполнение молнией",
    "Rage": "Ярость",
    "ThrillOfTheKill": "Азарт убийства",
    "Overabundance": "Изобилие",
    "PrimalArmament": "Первобытное вооружение",
    "ConcentratedEffect": "Сконцентрированный эффект",
}

# Ordered stat-line translation rules (regex -> Russian). Numbers are preserved.
# Unmatched English text is left intact (lossless), so nothing is hidden.
_STAT_RULES = [
    (r"Adds (\d+) to (\d+) Physical Damage", r"Добавляет \1–\2 физ. урона"),
    (r"Adds (\d+) to (\d+) Lightning [Dd]amage(?: to Attacks)?",
     r"Добавляет \1–\2 урона молнией"),
    (r"Adds (\d+) to (\d+) Cold [Dd]amage(?: to Attacks)?", r"Добавляет \1–\2 урона холодом"),
    (r"Adds (\d+) to (\d+) Fire [Dd]amage(?: to Attacks)?", r"Добавляет \1–\2 урона огнём"),
    (r"increased Critical Hit Chance", r"увеличение шанса крит. удара"),
    (r"to Critical Damage Bonus", r"к бонусу крит. урона"),
    (r"to Critical Hit Chance", r"к шансу крит. удара"),
    (r"increased Physical Damage", r"увеличение физ. урона"),
    (r"increased Evasion Rating", r"увеличение уклонения"),
    (r"increased Recovery rate", r"увеличение скорости восстановления"),
    (r"increased Rarity of Items found", r"увеличение редкости находимых предметов"),
    (r"increased Stun Buildup", r"увеличение накопления оглушения"),
    (r"to maximum Life", r"к максимуму здоровья"),
    (r"to maximum Energy Shield", r"к макс. энергощиту"),
    (r"to maximum Mana", r"к максимуму маны"),
    (r"to Lightning Resistance", r"к сопротивлению молнии"),
    (r"to Cold Resistance", r"к сопротивлению холоду"),
    (r"to Fire Resistance", r"к сопротивлению огню"),
    (r"to Chaos Resistance", r"к сопротивлению хаосу"),
    (r"to Accuracy Rating", r"к точности"),
    (r"to Evasion Rating", r"к уклонению"),
    (r"to Stun Threshold", r"к порогу оглушения"),
    (r"to Dexterity", r"к ловкости"),
    (r"to Strength", r"к силе"),
    (r"to Intelligence", r"к интеллекту"),
    (r"to Armour", r"к броне"),
    (r"Gain (\d+) Mana per enemy killed", r"+\1 маны за убийство врага"),
    (r"Gains ([\d.]+) Charges per Second", r"восстанавливает \1 заряда/сек"),
    (r"(\d+) to (\d+) Physical Thorns damage", r"\1–\2 физ. урона шипов"),
    (r"Physical Thorns damage", r"физ. урон шипов"),
    (r"to Attacks", r"к атакам"),
    (r"^Causes ", r"Вызывает "),
]
_STAT_RULES = [(re.compile(p), r) for p, r in _STAT_RULES]


@dataclass
class GuideItem:
    slot: str
    slot_ru: str
    name: str
    is_unique: bool
    mods_ru: List[str] = field(default_factory=list)
    level_min: int = 1


@dataclass
class GuideSkill:
    name_ru: str
    supports_ru: List[str] = field(default_factory=list)


@dataclass
class BuildGuide:
    name: str
    ascendancy_ru: str
    author: str
    items: List[GuideItem] = field(default_factory=list)
    skills: List[GuideSkill] = field(default_factory=list)
    passive_count: int = 0
    passive_ids: List[str] = field(default_factory=list)
    source_path: Optional[str] = None


def translate_stat(line: str) -> str:
    """Translate one mod line to Russian via the dictionary (lossless fallback)."""
    out = line.strip()
    for rgx, repl in _STAT_RULES:
        out = rgx.sub(repl, out)
    return out


def _gem_name(metadata_id: str) -> str:
    """Turn a gem metadata path into a readable (Russian where known) name."""
    leaf = metadata_id.rsplit("/", 1)[-1]
    for prefix in ("SupportGem", "SkillGem"):
        if leaf.startswith(prefix):
            leaf = leaf[len(prefix):]
            break
    if leaf in GEM_RU:
        return GEM_RU[leaf]
    # Fallback: split CamelCase into spaced English so it stays readable.
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", leaf)


def _parse_item(slot_entry: dict) -> GuideItem:
    slot = slot_entry.get("inventory_id", "")
    unique = slot_entry.get("unique_name")
    text = slot_entry.get("additional_text", "") or ""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    if unique:
        name, mod_lines = unique, []
    elif lines:
        name = lines[0]
        # Mods are usually "1. <mod>" numbered lines after the item name.
        mod_lines = [re.sub(r"^\d+\.\s*", "", ln) for ln in lines[1:]]
    else:
        name = SLOT_RU.get(slot, slot)
        mod_lines = []

    level = 1
    interval = slot_entry.get("level_interval")
    if isinstance(interval, list) and interval:
        try:
            level = int(interval[0])
        except (ValueError, TypeError):
            level = 1

    return GuideItem(
        slot=slot,
        slot_ru=SLOT_RU.get(slot, slot),
        name=name,
        is_unique=bool(unique),
        mods_ru=[translate_stat(m) for m in mod_lines],
        level_min=level,
    )


def parse_build(data: dict, source_path: Optional[str] = None) -> BuildGuide:
    """Parse a decoded ``.build`` JSON dict into a BuildGuide."""
    asc = data.get("ascendancy", "") or ""
    guide = BuildGuide(
        name=data.get("name", "Без названия"),
        ascendancy_ru=ASCENDANCY_RU.get(asc, asc),
        author=data.get("author", ""),
        source_path=source_path,
    )

    items = [_parse_item(s) for s in data.get("inventory_slots", []) if s.get("inventory_id")]
    # Stable, intuitive slot order; unknown slots go last.
    items.sort(key=lambda it: (_SLOT_ORDER.index(it.slot) if it.slot in _SLOT_ORDER else 99))
    guide.items = items

    for sk in data.get("skills", []):
        supports = [_gem_name(s.get("id", "")) for s in sk.get("support_skills", []) if s.get("id")]
        guide.skills.append(GuideSkill(name_ru=_gem_name(sk.get("id", "")), supports_ru=supports))

    passives = data.get("passives", [])
    guide.passive_count = len(passives)
    guide.passive_ids = [p.get("id", "") for p in passives if p.get("id")]
    return guide


def load_active_build(path: Optional[str] = None) -> Optional[BuildGuide]:
    """Locate (via the game's active build), parse and return the build guide."""
    if path is None:
        paths = game_config.active_build_paths()
        if not paths:
            logger.info("No active PoE2 build found")
            return None
        path = paths[0]
    try:
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to read build %s: %s", path, e)
        return None
    return parse_build(data, source_path=path)


def render_text(guide: BuildGuide) -> str:
    """Render the guide as a readable Russian multi-line string (for the overlay)."""
    lines: List[str] = []
    title = f"🛠  {guide.name}"
    if guide.ascendancy_ru:
        title += f"  ({guide.ascendancy_ru})"
    lines.append(title)
    if guide.author:
        lines.append(f"Автор: {guide.author}")
    lines.append("")

    lines.append("━━ СНАРЯЖЕНИЕ ━━")
    for it in guide.items:
        tag = " [уник]" if it.is_unique else ""
        lvl = f"  (с ур. {it.level_min})" if it.level_min > 1 else ""
        lines.append(f"• {it.slot_ru}: {it.name}{tag}{lvl}")
        for mod in it.mods_ru:
            lines.append(f"    – {mod}")
    lines.append("")

    lines.append("━━ НАВЫКИ ━━")
    for sk in guide.skills:
        lines.append(f"• {sk.name_ru}")
        if sk.supports_ru:
            lines.append(f"    саппорты: {', '.join(sk.supports_ru)}")
    lines.append("")

    lines.append(f"━━ ПАССИВЫ ({guide.passive_count}) ━━")
    lines.append("Названия узлов появятся после добавления таблицы дерева PoE2;")
    lines.append("пока — внутренние id:")
    lines.append("  " + ", ".join(guide.passive_ids))
    lines.append("")

    lines.append("Источники меты: " + " · ".join(REFERENCE_LINKS))
    return "\n".join(lines)
