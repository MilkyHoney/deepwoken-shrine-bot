import json
import os
import re

import discord
from rapidfuzz import process as fuzz

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "talents.json")

_cache = {"talents": []}

# ---------------------------------------------------------------------------
# Rarity colors for embeds
# ---------------------------------------------------------------------------

RARITY_COLORS = {
    "Common":    0x95a5a6,
    "Rare":      0x3498db,
    "Advanced":  0x9b59b6,
    "Oath":      0xe74c3c,
    "Innate":    0x2ecc71,
    "Quest":     0xf39c12,
    "Murmur":    0x1abc9c,
    "Spec":      0x1abc9c,
    "Faction":   0xe67e22,
    "Origin":    0x34495e,
    "Equipment": 0x7f8c8d,
    "Outfit":    0x7f8c8d,
    "Memento":   0x8e44ad,
    "Weapon":    0xf1c40f,
}

# ---------------------------------------------------------------------------
# Stat aliases — for parsing user input
# ---------------------------------------------------------------------------

STAT_ALIASES = {
    "str": "Strength", "strength": "Strength",
    "fort": "Fortitude", "fortitude": "Fortitude",
    "agi": "Agility", "agility": "Agility",
    "int": "Intelligence", "intelligence": "Intelligence",
    "will": "Willpower", "willpower": "Willpower",
    "cha": "Charisma", "charisma": "Charisma",
    "flame": "Flamecharm", "flamecharm": "Flamecharm",
    "frost": "Frostdraw", "frostdraw": "Frostdraw",
    "thunder": "Thundercall", "thundercall": "Thundercall",
    "gale": "Galebreathe", "galebreathe": "Galebreathe",
    "shadow": "Shadowcast", "shadowcast": "Shadowcast",
    "iron": "Ironsing", "ironsing": "Ironsing",
    "blood": "Bloodrend", "bloodrend": "Bloodrend",
    "light": "Light Weapon", "lightweapon": "Light Weapon", "lht": "Light Weapon",
    "med": "Medium Weapon", "medium": "Medium Weapon", "mediumweapon": "Medium Weapon",
    "heavy": "Heavy Weapon", "heavyweapon": "Heavy Weapon", "hvy": "Heavy Weapon",
}

CANONICAL_STATS = sorted(set(STAT_ALIASES.values()))


def normalize_stat(s: str):
    if not s:
        return None
    key = s.lower().replace(" ", "")
    if key in STAT_ALIASES:
        return STAT_ALIASES[key]
    m = fuzz.extractOne(s, CANONICAL_STATS, score_cutoff=60)
    return m[0] if m else None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_talents():
    if _cache["talents"]:
        return _cache["talents"]
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            _cache["talents"] = json.load(f)
        print(f"[Talents] Loaded {len(_cache['talents'])} talents from {DATA_PATH}")
    except FileNotFoundError:
        print(f"[Talents] ERROR: {DATA_PATH} not found. Place talents.json next to talents.py.")
        _cache["talents"] = []
    except Exception as e:
        print(f"[Talents] ERROR loading {DATA_PATH}: {e}")
        _cache["talents"] = []
    return _cache["talents"]


def get_talents():
    return load_talents()


def refresh_cache():
    _cache["talents"] = []
    load_talents()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_by_name(query: str):
    """
    Look up a talent by name. Tries:
      1. Exact case-insensitive match
      2. Starts-with match (shortest name wins, e.g. 'kick' -> 'Kick Off' not 'Kickstart')
      3. Substring match (shortest name wins)
      4. Fuzzy match for typos, with a high cutoff to avoid spurious matches
         like 'kick off' -> 'Water off a Duck's Back'.
    Returns the talent dict or None.
    """
    talents = get_talents()
    if not talents:
        return None

    q = query.strip().lower()
    if not q:
        return None

    for t in talents:
        if t["name"].lower() == q:
            return t

    starts = [t for t in talents if t["name"].lower().startswith(q)]
    if starts:
        return min(starts, key=lambda t: len(t["name"]))

    contains = [t for t in talents if q in t["name"].lower()]
    if contains:
        return min(contains, key=lambda t: len(t["name"]))

    names = [t["name"] for t in talents]
    match = fuzz.extractOne(query, names, score_cutoff=70)
    if not match:
        return None
    return next((t for t in talents if t["name"] == match[0]), None)


def search_by_stat(stat: str, level: int):
    canonical = normalize_stat(stat)
    if not canonical:
        return []

    results = []
    for t in get_talents():
        reqs = t.get("requirements") or {}
        stats = reqs.get("stats") or {}
        if not isinstance(stats, dict):
            continue
        if stats.get(canonical) == level:
            results.append(t)
    return results


def parse_stat_query(query: str):
    query = query.strip()
    m = re.match(r"^(\d+)\s+(.+)$", query)
    if m:
        return int(m.group(1)), m.group(2)
    m = re.match(r"^(.+?)\s+(\d+)$", query)
    if m:
        return int(m.group(2)), m.group(1)
    return None


# ---------------------------------------------------------------------------
# Embed formatting
# ---------------------------------------------------------------------------

def _format_requirements(reqs: dict) -> str:
    if not isinstance(reqs, dict) or not reqs:
        return ""
    lines = []

    stats = reqs.get("stats") or {}
    if isinstance(stats, dict) and stats:
        lines.append("**Stats:** " + ", ".join(f"{v} {k}" for k, v in stats.items()))

    if reqs.get("talents"):
        lines.append("**Talents:** " + ", ".join(reqs["talents"]))
    if reqs.get("mantras"):
        lines.append("**Mantras:** " + ", ".join(reqs["mantras"]))
    if reqs.get("weapon"):
        w = reqs["weapon"]
        lines.append("**Weapon:** " + (", ".join(w) if isinstance(w, list) else str(w)))
    if reqs.get("weaponType"):
        wt = reqs["weaponType"]
        lines.append("**Weapon Type:** " + (", ".join(wt) if isinstance(wt, list) else str(wt)))
    if reqs.get("equipment"):
        eq = reqs["equipment"]
        lines.append("**Equipment:** " + (", ".join(eq) if isinstance(eq, list) else str(eq)))
    if reqs.get("outfit"):
        o = reqs["outfit"]
        lines.append("**Outfit:** " + (", ".join(o) if isinstance(o, list) else str(o)))
    if reqs.get("set"):
        lines.append(f"**Set:** {reqs['set']}")
    if reqs.get("aspect"):
        a = reqs["aspect"]
        lines.append("**Aspect:** " + (", ".join(a) if isinstance(a, list) else str(a)))
    if reqs.get("origin"):
        lines.append(f"**Origin:** {reqs['origin']}")
    if reqs.get("memento"):
        lines.append(f"**Memento:** {reqs['memento']}")
    if reqs.get("murmur"):
        lines.append(f"**Murmur:** {reqs['murmur']}")
    if reqs.get("quests"):
        q = reqs["quests"]
        lines.append("**Quest:** " + (", ".join(q) if isinstance(q, list) else str(q)))
    if reqs.get("objectives"):
        obj = reqs["objectives"]
        lines.append("**Objectives:** " + (", ".join(obj) if isinstance(obj, list) else str(obj)))
    if reqs.get("slay"):
        s = reqs["slay"]
        lines.append("**Slay:** " + (", ".join(s) if isinstance(s, list) else str(s)))
    if reqs.get("or"):
        lines.append(f"**Or:** {reqs['or']}")
    if reqs.get("add"):
        lines.append(f"**Additional:** {reqs['add']}")

    return "\n".join(lines)


def _format_stat_bonuses(stats) -> str:
    if not isinstance(stats, dict) or not stats:
        return ""
    return ", ".join(f"+{v} {k}" for k, v in stats.items())


def build_talent_embed(talent: dict) -> discord.Embed:
    color = RARITY_COLORS.get(talent.get("rarity", ""), 0x95a5a6)
    title = talent["name"]
    if talent.get("VOI"):
        title += " 🛡️"
    if talent.get("vaulted"):
        title += " (Vaulted)"

    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Category", value=talent.get("category") or "General", inline=True)
    embed.add_field(name="Rarity", value=talent.get("rarity") or "—", inline=True)

    bonuses = _format_stat_bonuses(talent.get("stats"))
    if bonuses:
        embed.add_field(name="Bonuses", value=bonuses, inline=True)

    desc = (talent.get("description") or "").strip()
    if desc:
        embed.add_field(name="Description", value=desc[:1024], inline=False)

    reqs_text = _format_requirements(talent.get("requirements"))
    if reqs_text:
        embed.add_field(name="Requirements", value=reqs_text[:1024], inline=False)

    me = talent.get("mutualExclusives") or []
    if me:
        embed.add_field(name="Mutually Exclusive", value=", ".join(me)[:1024], inline=False)

    info = (talent.get("additionalInfo") or "").strip()
    if info:
        embed.add_field(name="Notes", value=info[:1024], inline=False)

    footer = "Deepwoken Talent"
    if talent.get("VOI"):
        footer += " · Vow of Iron exclusive"
    embed.set_footer(text=footer)

    return embed


def build_stat_results_embeds(stat: str, level: int, results: list) -> list:
    """Render each matching talent as a full embed (Discord allows up to 10 per message)."""
    canonical = normalize_stat(stat) or stat

    if not results:
        empty = discord.Embed(
            title=f"Talents requiring exactly {level} {canonical}",
            description=f"No talents found requiring **{level} {canonical}**.",
            color=0x2ecc71,
        )
        return [empty]

    embeds = [build_talent_embed(t) for t in results[:10]]

    embeds[0].title = (
        f"{embeds[0].title}  —  {len(results)} match"
        f"{'es' if len(results) != 1 else ''} for {level} {canonical}"
    )

    if len(results) > 10:
        overflow = discord.Embed(
            title=f"+ {len(results) - 10} more",
            description="\n".join(f"• {t['name']}" for t in results[10:]),
            color=0x95a5a6,
        )
        embeds.append(overflow)

    return embeds
