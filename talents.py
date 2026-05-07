"""
Deepwoken talent lookup backed by a local talents.json file.
"""

import json
import os
import re

import discord
from rapidfuzz import process as fuzz

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "talents.json")

_cache = {"talents": []}

# ---------------------------------------------------------------------------
# Rarity colors and valid values
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

# Rarities present in the data, in roughly logical display order
ALL_RARITIES = [
    "Common", "Rare", "Advanced", "Oath", "Innate",
    "Quest", "Murmur", "Spec", "Faction", "Origin",
    "Equipment", "Outfit", "Memento", "Weapon",
]

# Sort priority for stat-search results: Advanced first, then Rare, then Common,
# then everything else. Oath is excluded by default (see search_by_stat).
RARITY_SORT_ORDER = {
    "Advanced": 0,
    "Rare": 1,
    "Common": 2,
    "Innate": 3,
    "Spec": 4,
    "Murmur": 5,
    "Quest": 6,
    "Faction": 7,
    "Origin": 8,
    "Equipment": 9,
    "Outfit": 10,
    "Memento": 11,
    "Weapon": 12,
    "Oath": 99,
}


def _is_mantra_unlock(talent: dict) -> bool:
    """Detect 'Adept/Expert/Master Xer' talents whose only effect is unlocking
    higher-star mantras — these clutter low-stat searches."""
    desc = (talent.get("description") or "").lower()
    return "you can now obtain" in desc and "leveled" in desc and "mantras" in desc

# ---------------------------------------------------------------------------
# Stat aliases — match the keys actually used in talents.json
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
    Look up a talent by name. Tries exact → starts-with → substring → fuzzy (cutoff 70).
    Returns (talent_dict, was_fuzzy_guess) or (None, False).
    """
    talents = get_talents()
    if not talents:
        return None, False

    q = query.strip().lower()
    if not q:
        return None, False

    for t in talents:
        if t["name"].lower() == q:
            return t, False

    starts = [t for t in talents if t["name"].lower().startswith(q)]
    if starts:
        return min(starts, key=lambda t: len(t["name"])), False

    contains = [t for t in talents if q in t["name"].lower()]
    if contains:
        return min(contains, key=lambda t: len(t["name"])), False

    names = [t["name"] for t in talents]
    match = fuzz.extractOne(query, names, score_cutoff=70)
    if not match:
        return None, False
    return next((t for t in talents if t["name"] == match[0]), None), True


def search_by_stat(stat: str, level: int, mode: str = "exact",
                   include_oaths: bool = False,
                   include_mantra_unlocks: bool = False):
    """
    Find talents by stat requirement.
    mode='exact' → stat == level
    mode='gte'   → stat >= level

    By default, Oath-rarity talents and 'You can now obtain X-Star Leveled
    Mantras' talents are excluded since they clutter low-stat searches.
    """
    canonical = normalize_stat(stat)
    if not canonical:
        return []

    results = []
    for t in get_talents():
        if not include_oaths and (t.get("rarity") or "") == "Oath":
            continue
        if not include_mantra_unlocks and _is_mantra_unlock(t):
            continue

        reqs = t.get("requirements") or {}
        stats = reqs.get("stats") or {}
        if not isinstance(stats, dict):
            continue
        v = stats.get(canonical)
        if v is None:
            continue
        if mode == "gte" and v >= level:
            results.append(t)
        elif mode == "exact" and v == level:
            results.append(t)

    # Sort alphabetically by name
    results.sort(key=lambda t: t["name"].lower())
    return results


def parse_stat_query(query: str):
    """
    Parse '40 Agility', '40+ Agility', 'Agility 40', 'Agility 40+' into
    (level, stat_name, mode) where mode is 'exact' or 'gte'.
    Returns None if not a stat query.
    """
    query = query.strip()
    # number first: "40 Agility" or "40+ Agility"
    m = re.match(r"^(\d+)(\+?)\s+(.+)$", query)
    if m:
        mode = "gte" if m.group(2) == "+" else "exact"
        return int(m.group(1)), m.group(3).strip(), mode
    # stat first: "Agility 40" or "Agility 40+"
    m = re.match(r"^(.+?)\s+(\d+)(\+?)$", query)
    if m:
        mode = "gte" if m.group(3) == "+" else "exact"
        return int(m.group(2)), m.group(1).strip(), mode
    return None


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def filter_results(results, rarity=None, category=None):
    """Apply optional rarity and category filters to a list of talents."""
    out = results
    if rarity:
        rarity_l = rarity.lower()
        out = [t for t in out if (t.get("rarity") or "").lower() == rarity_l]
    if category:
        cat_l = category.lower()
        out = [t for t in out if cat_l in (t.get("category") or "").lower()]
    return out


# ---------------------------------------------------------------------------
# Autocomplete helpers
# ---------------------------------------------------------------------------

def autocomplete_names(prefix: str, limit: int = 25):
    """Return up to `limit` talent names matching prefix (case-insensitive)."""
    p = (prefix or "").strip().lower()
    talents = get_talents()
    if not talents:
        return []
    if not p:
        return [t["name"] for t in talents[:limit]]
    # Prefer prefix matches first, then substring
    starts = [t["name"] for t in talents if t["name"].lower().startswith(p)]
    contains = [t["name"] for t in talents if p in t["name"].lower() and not t["name"].lower().startswith(p)]
    return (starts + contains)[:limit]


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


def build_talent_embed(talent: dict, did_you_mean: bool = False) -> discord.Embed:
    color = RARITY_COLORS.get(talent.get("rarity", ""), 0x95a5a6)
    title = talent["name"]
    if talent.get("VOI"):
        title += " 🛡️"
    if talent.get("vaulted"):
        title += " (Vaulted)"

    embed = discord.Embed(title=title, color=color)
    if talent.get("wiki"):
        embed.url = talent["wiki"]

    if did_you_mean:
        embed.set_author(name=f'💡 Did you mean "{talent["name"]}"?')

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


def build_stat_results_embeds(stat: str, level: int, results: list,
                              mode: str = "exact",
                              rarity: str = None,
                              category: str = None) -> list:
    """
    Render matching talents as full embeds. Discord caps at 10 embeds per message,
    so we ship up to 9 full cards plus 1 overflow card when there are more.
    """
    canonical = normalize_stat(stat) or stat
    op = "≥" if mode == "gte" else "="

    filter_bits = []
    if rarity:
        filter_bits.append(f"rarity={rarity}")
    if category:
        filter_bits.append(f"category={category}")
    filter_str = f" ({', '.join(filter_bits)})" if filter_bits else ""

    if not results:
        empty = discord.Embed(
            title=f"Talents requiring {canonical} {op} {level}{filter_str}",
            description="No talents found.",
            color=0x2ecc71,
        )
        return [empty]

    has_overflow = len(results) > 10
    show = results[:9] if has_overflow else results[:10]

    embeds = [build_talent_embed(t) for t in show]

    plural = "es" if len(results) != 1 else ""
    embeds[0].title = (
        f"{embeds[0].title}  —  {len(results)} match{plural} "
        f"for {canonical} {op} {level}{filter_str}"
    )

    if has_overflow:
        remaining = sorted(results[9:], key=lambda t: t["name"].lower())
        # Cap description to stay under Discord's 4096-char limit.
        # Use newlines between names so each one renders on its own line.
        lines = [f"• {t['name']}" for t in remaining]
        shown_lines = lines[:40]
        desc = "\n".join(shown_lines)
        if len(lines) > 40:
            desc += f"\n…and {len(lines) - 40} more"
        overflow = discord.Embed(
            title=f"+ {len(remaining)} more",
            description=desc,
            color=0x95a5a6,
        )
        embeds.append(overflow)

    return embeds


# ---------------------------------------------------------------------------
# Slash command registration
# ---------------------------------------------------------------------------

import random
from discord import app_commands


async def _autocomplete(interaction, current: str):
    stripped = (current or "").strip()
    # Don't autocomplete when the user is typing a stat query like "40 Agility"
    if re.match(r"^\d+\+?(\s+|$)", stripped):
        return []
    names = autocomplete_names(stripped, limit=25)
    return [app_commands.Choice(name=n[:100], value=n[:100]) for n in names]


def register(tree: app_commands.CommandTree):
    """Register /talents and /talent_random commands on the given tree."""
    rarity_choices = [app_commands.Choice(name=r, value=r) for r in ALL_RARITIES]

    @tree.command(name="talents", description="Look up Deepwoken talents by name or stat requirement")
    @app_commands.describe(
        query='Talent name (e.g. "Ghost") or stat requirement ("40 Agility", "40+ Agility")',
        rarity="Filter by rarity (only applies to stat searches)",
        category="Filter by category text (e.g. 'Butterfly', 'Tactician') — only for stat searches",
    )
    @app_commands.autocomplete(query=_autocomplete)
    @app_commands.choices(rarity=rarity_choices)
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)
    async def talents_command(
        interaction: discord.Interaction,
        query: str,
        rarity: app_commands.Choice[str] = None,
        category: str = None,
    ):
        await interaction.response.defer()
        rarity_str = rarity.value if rarity else None
        stat_query = parse_stat_query(query)

        if stat_query:
            level, stat, mode = stat_query
            include_oaths = (rarity_str == "Oath")
            results = search_by_stat(stat, level, mode=mode, include_oaths=include_oaths)
            if rarity_str or category:
                results = filter_results(results, rarity=rarity_str, category=category)
            embeds = build_stat_results_embeds(
                stat, level, results, mode=mode, rarity=rarity_str, category=category
            )
            await interaction.followup.send(embeds=embeds)
        else:
            talent, was_fuzzy = search_by_name(query)
            if not talent:
                await interaction.followup.send(
                    f"❌ No talent found matching `{query}`. Check your spelling and try again."
                )
                return
            embed = build_talent_embed(talent, did_you_mean=was_fuzzy)
            await interaction.followup.send(embed=embed)

    @talents_command.error
    async def _talents_err(interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            try:
                await interaction.response.send_message(
                    f"⏳ Slow down — try again in {error.retry_after:.1f}s.",
                    ephemeral=True,
                )
            except Exception:
                pass
        else:
            print(f"[Talents] Command error: {error}")

    @tree.command(name="talent_random", description="Pull a random Deepwoken talent")
    @app_commands.describe(
        rarity="Optional: filter by rarity",
    )
    @app_commands.choices(rarity=rarity_choices)
    @app_commands.checks.cooldown(1, 2.0, key=lambda i: i.user.id)
    async def talent_random_command(
        interaction: discord.Interaction,
        rarity: app_commands.Choice[str] = None,
    ):
        await interaction.response.defer()
        pool = get_talents()
        if rarity:
            pool = [t for t in pool if (t.get("rarity") or "") == rarity.value]
        if not pool:
            await interaction.followup.send("❌ No talents matched that filter.")
            return
        pick = random.choice(pool)
        embed = build_talent_embed(pick)
        await interaction.followup.send(embed=embed)

    @talent_random_command.error
    async def _random_err(interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            try:
                await interaction.response.send_message(
                    f"⏳ Slow down — try again in {error.retry_after:.1f}s.",
                    ephemeral=True,
                )
            except Exception:
                pass
        else:
            print(f"[TalentRandom] Command error: {error}")
