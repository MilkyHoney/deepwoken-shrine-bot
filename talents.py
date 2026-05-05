"""
Talent cache module for Deepwoken Discord bot.
Reads from local talents_dump.txt (fallback if wiki scrape fails).
Refreshes every 6 hours via the talent_refresh_loop in main.py.
"""

import re
import time
import os
import requests
from bs4 import BeautifulSoup
from rapidfuzz import process as fuzz

WIKI_URL = "https://deepwoken.fandom.com/wiki/Talents"
DUMP_FILE = "talents_dump.txt"

RARITY_COLORS = {
    "Common": 0x95a5a6,
    "Rare": 0x3498db,
    "Advanced": 0x9b59b6,
    "Oath": 0xe74c3c,
    "Memento": 0xe74c3c,
    "Race": 0x2ecc71,
    "Mantra Level": 0xf1c40f,
    "Mastery": 0xf1c40f,
    "Origin": 0x1abc9c,
    "Quest": 0xe67e22,
    "Faction": 0xd35400,
    "Mantra": 0x34495e,
    "Mystery": 0x7f8c8d,
    "Equipment": 0xbdc3c7,
    "Outfit": 0xbdc3c7,
    "Unlockable": 0x8e44ad,
    "Dual Attunement": 0x16a085,
    "Triple Attunement": 0x27ae60,
    "Echo": 0xc0392b,
}

STAT_ALIASES = {
    "strength": "Strength", "str": "Strength",
    "fortitude": "Fortitude", "fort": "Fortitude",
    "agility": "Agility", "agi": "Agility",
    "intelligence": "Intelligence", "int": "Intelligence",
    "willpower": "Willpower", "will": "Willpower",
    "charisma": "Charisma", "cha": "Charisma",
    "flamecharm": "Flamecharm", "flame": "Flamecharm",
    "frostdraw": "Frostdraw", "frost": "Frostdraw",
    "thundercall": "Thundercall", "thunder": "Thundercall",
    "galebreathe": "Galebreathe", "gale": "Galebreathe",
    "shadowcast": "Shadowcast", "shadow": "Shadowcast",
    "ironsing": "Ironsing", "iron": "Ironsing",
    "bloodrend": "Bloodrend", "blood": "Bloodrend",
    "lightweapon": "LightWeapon", "light": "LightWeapon", "lht": "LightWeapon",
    "mediumweapon": "MediumWeapon", "medium": "MediumWeapon", "med": "MediumWeapon",
    "heavyweapon": "HeavyWeapon", "heavy": "HeavyWeapon", "hvy": "HeavyWeapon",
    "mind": "Mind",
    "weapon": "Weapon",
    "power": "Power",
    "element": "Element",
}

_VALID_STATS = list(dict.fromkeys(STAT_ALIASES.values()))

_talents = []
_talents_by_name = {}
_last_refresh = None


def _norm_stat(name):
    return STAT_ALIASES.get(name.lower().strip(), name.title())


def _is_garbage_line(line):
    garbage = [
        "http://", "https://", "fandom.com", "Fandom Apps", "Store icon",
        "View Mobile Site", "Fandom Games Community", "Take your favorite",
        "never miss a beat", "App logo", "mediakit", "apple.com", "play.google.com",
        "[edit]", "[show]", "[hide]", "Categories:", "Community content",
        "Follow on IG", "Follow on TikTok", "Follow on Twitter", "Subscribe on YT",
        "Fan Feed", "More Fandoms", "Explore properties", "Advertise", "Media Kit",
        "Contact", "Terms of Use", "Privacy Policy", "Do Not Sell", "Cookie Policy",
    ]
    low = line.lower()
    return any(g.lower() in low for g in garbage) or (line.startswith("[") and line.endswith("]") and line[1:-1].isdigit())


def _extract_rarity(tag_text):
    m = re.search(r"\[([^,\]]+)\s+Talent", tag_text)
    if m:
        return m.group(1).strip()
    for keyword in ["Oath Talent", "Origin Talent", "Quest Talent", "Faction Talent",
                    "Mastery Talent", "Mantra Level Talent", "Race Talent",
                    "Equipment Talent", "Echo Talent", "Unlockable Talent"]:
        if keyword in tag_text:
            return keyword.replace(" Talent", "").strip()
    return "Common"


def _extract_stats_from_line(line):
    stats = []
    for m in re.finditer(r"\b(\d+)\s+([A-Za-z]+)\b", line):
        num, word = m.groups()
        word = word.lower().strip()
        if word in STAT_ALIASES:
            stats.append(f"{num} {STAT_ALIASES[word]}")
        elif word in ("med", "medium"):
            stats.append(f"{num} MediumWeapon")
        elif word in ("lht", "light"):
            stats.append(f"{num} LightWeapon")
        elif word in ("hvy", "heavy"):
            stats.append(f"{num} HeavyWeapon")
        elif word == "str":
            stats.append(f"{num} Strength")
        elif word == "fort":
            stats.append(f"{num} Fortitude")
        elif word == "agi":
            stats.append(f"{num} Agility")
        elif word == "int":
            stats.append(f"{num} Intelligence")
        elif word == "will":
            stats.append(f"{num} Willpower")
        elif word == "cha":
            stats.append(f"{num} Charisma")
        elif word == "flame":
            stats.append(f"{num} Flamecharm")
        elif word == "frost":
            stats.append(f"{num} Frostdraw")
        elif word == "thunder":
            stats.append(f"{num} Thundercall")
        elif word == "gale":
            stats.append(f"{num} Galebreathe")
        elif word == "shadow":
            stats.append(f"{num} Shadowcast")
        elif word == "iron":
            stats.append(f"{num} Ironsing")
        elif word == "blood":
            stats.append(f"{num} Bloodrend")

    for m in re.finditer(r"\b(\d+)\s+([A-Za-z]+\s+[A-Za-z]+)\b", line):
        num, phrase = m.groups()
        phrase_clean = phrase.lower().strip().replace(" ", "")
        if phrase_clean in STAT_ALIASES:
            stats.append(f"{num} {STAT_ALIASES[phrase_clean]}")
        elif phrase_clean in ("lightweapon", "light weapon"):
            stats.append(f"{num} LightWeapon")
        elif phrase_clean in ("mediumweapon", "medium weapon"):
            stats.append(f"{num} MediumWeapon")
        elif phrase_clean in ("heavyweapon", "heavy weapon"):
            stats.append(f"{num} HeavyWeapon")

    seen = set()
    deduped = []
    for s in stats:
        if s.lower() not in seen:
            seen.add(s.lower())
            deduped.append(s)
    return deduped


def _parse_talent_block(lines):
    if not lines:
        return None
    first = lines[0]
    first = re.sub(r"^\s*•\s*", "", first)
    name_match = re.match(r"^\s*(.+?)\s*\[", first)
    if not name_match:
        return None
    name = name_match.group(1).strip()
    rarity = _extract_rarity(first)

    description = []
    prerequisites = []
    notes = []
    category = "General"

    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        if _is_garbage_line(line):
            continue
        if line.startswith("Prerequisite"):
            prerequisites.append(line)
        elif line.startswith("Prerequisites"):
            prerequisites.append(line)
        elif "Mutual Exclusive" in line:
            prerequisites.append(line)
        elif line.startswith("Obtained from"):
            prerequisites.append(line)
        else:
            description.append(line)

    # Extract stats from ALL lines (header + body)
    stats = []
    for line in lines:
        stats.extend(_extract_stats_from_line(line))
    seen = set()
    deduped = []
    for s in stats:
        if s.lower() not in seen:
            seen.add(s.lower())
            deduped.append(s)
    stats = deduped

    if any(o in first for o in ["Oath Talent", "Oath:"]):
        category = "Oath"
    elif "Quest Talent" in first:
        category = "Quest"
    elif "Faction Talent" in first:
        category = "Faction"
    elif "Race Talent" in first:
        category = "Race"
    elif "Mastery Talent" in first:
        category = "Mastery"
    elif "Mantra Level Talent" in first:
        category = "Mantra Level"
    elif "Origin Talent" in first:
        category = "Origin"
    elif any(w in first for w in ["Flamecharm", "Frostdraw", "Thundercall", "Galebreathe", "Shadowcast", "Ironsing", "Bloodrend"]):
        category = "Attunement"
    elif any(w in first for w in ["Light Weapon", "Medium Weapon", "Heavy Weapon", "Weapon"]):
        category = "Weapon"
    elif any(w in first for w in ["Strength", "Fortitude", "Agility", "Intelligence", "Willpower", "Charisma"]):
        category = "Attribute"

    return {
        "name": name,
        "rarity": rarity,
        "category": category,
        "stats": stats,
        "description": " ".join(description).replace("**", "").replace("*", "")[:500],
        "prerequisites": prerequisites,
        "notes": notes,
    }


def _parse_text_dump(text):
    parsed = []
    current_block = []

    for line in text.splitlines():
        line = line.strip()
        if not line or _is_garbage_line(line):
            continue

        if re.search(r"\[.*Talent.*\]", line) and not re.match(r"^\[\d+\]$", line):
            if current_block:
                t = _parse_talent_block(current_block)
                if t:
                    parsed.append(t)
            current_block = [line]
        elif current_block:
            current_block.append(line)

    if current_block:
        t = _parse_talent_block(current_block)
        if t:
            parsed.append(t)
    return parsed


def refresh_cache():
    global _talents, _talents_by_name, _last_refresh

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
        resp = requests.get(WIKI_URL, timeout=30, headers=headers)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        content = soup.get_text(separator="\n")
        parsed = _parse_text_dump(content)
        source = "wiki"
    except Exception as e:
        print(f"[talents] Wiki scrape failed: {e}")
        parsed = []
        source = None

    if not parsed and os.path.exists(DUMP_FILE):
        try:
            with open(DUMP_FILE, "r", encoding="utf-8") as f:
                parsed = _parse_text_dump(f.read())
            source = "local file"
        except Exception as e:
            print(f"[talents] Local file read failed: {e}")

    _talents = parsed
    _talents_by_name = {t["name"].lower(): t for t in parsed}
    _last_refresh = time.time()

    if parsed:
        print(f"[talents] Cache refreshed: {len(parsed)} talents loaded from {source}.")
    else:
        print("[talents] Warning: no talents loaded. /talents will return empty results.")


def parse_stat_query(query: str):
    m = re.match(r"^(\d+)\s+([A-Za-z\s]+)$", query.strip())
    if not m:
        return None
    level, stat_raw = m.groups()
    stat_raw = stat_raw.strip()

    norm = _norm_stat(stat_raw)
    if norm in _VALID_STATS:
        return int(level), norm

    match = fuzz.extractOne(stat_raw.lower(), [s.lower() for s in _VALID_STATS], score_cutoff=70)
    if match:
        for s in _VALID_STATS:
            if s.lower() == match[0]:
                return int(level), s

    return None


def search_by_stat(stat_name: str, level: int):
    """
    Return talents that require the given stat at EXACTLY the given level.
    Talents may have other stat requirements too — they are still shown.
    """
    stat_name = _norm_stat(stat_name)
    results = []
    for t in _talents:
        for req in t.get("stats", []):
            parts = req.split()
            if len(parts) >= 2:
                try:
                    req_level = int(parts[0])
                    req_stat = " ".join(parts[1:])
                    if req_stat.lower() == stat_name.lower() and req_level == level:
                        results.append(t)
                        break
                except ValueError:
                    continue
    return results


def search_by_name(query: str):
    query = query.lower().strip()
    if query in _talents_by_name:
        return _talents_by_name[query]
    names = list(_talents_by_name.keys())
    if not names:
        return None
    match = fuzz.extractOne(query, names, score_cutoff=60)
    if match:
        return _talents_by_name[match[0]]
    return None


refresh_cache()