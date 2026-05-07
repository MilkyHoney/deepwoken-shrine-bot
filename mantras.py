"""
Deepwoken mantra lookup backed by a local mantras.json file.
"""

import json
import os
import re

import discord
from rapidfuzz import process as fuzz

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mantras.json")

_cache = {"mantras": []}

# ---------------------------------------------------------------------------
# Color & display
# ---------------------------------------------------------------------------

CATEGORY_COLORS = {
    "Combat":   0xe74c3c,
    "Support":  0x2ecc71,
    "Mobility": 0x3498db,
    "Wisp":     0x9b59b6,
}

TYPE_COLORS = {
    "Normal":  None,  # falls back to category
    "Oath":    0xe67e22,
    "Origin":  0x34495e,
    "Monster": 0x8e44ad,
    "Event":   0xf1c40f,
}

# Stat aliases — match the keys used in mantras.json
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
    "gale": "Galebreath", "galebreath": "Galebreath", "galebreathe": "Galebreath",
    "shadow": "Shadowcast", "shadowcast": "Shadowcast",
    "iron": "Ironsing", "ironsing": "Ironsing",
    "blood": "Bloodrend", "bloodrend": "Bloodrend",
    "light": "Light Weapon", "lightweapon": "Light Weapon",
    "med": "Medium Weapon", "medium": "Medium Weapon", "mediumweapon": "Medium Weapon",
    "heavy": "Heavy Weapon", "heavyweapon": "Heavy Weapon",
}

CANONICAL_STATS = sorted(set(STAT_ALIASES.values()))

CATEGORY_CHOICES = ["Combat", "Support", "Mobility", "Wisp"]


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

def load_mantras():
    if _cache["mantras"]:
        return _cache["mantras"]
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            _cache["mantras"] = json.load(f)
        print(f"[Mantras] Loaded {len(_cache['mantras'])} mantras from {DATA_PATH}")
    except FileNotFoundError:
        print(f"[Mantras] ERROR: {DATA_PATH} not found.")
        _cache["mantras"] = []
    except Exception as e:
        print(f"[Mantras] ERROR loading {DATA_PATH}: {e}")
        _cache["mantras"] = []
    return _cache["mantras"]


def get_mantras():
    return load_mantras()


def refresh_cache():
    _cache["mantras"] = []
    load_mantras()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_by_name(query: str):
    """Returns (mantra_dict, was_fuzzy_guess) or (None, False)."""
    mantras = get_mantras()
    if not mantras:
        return None, False
    q = query.strip().lower()
    if not q:
        return None, False

    for m in mantras:
        if m["name"].lower() == q:
            return m, False

    starts = [m for m in mantras if m["name"].lower().startswith(q)]
    if starts:
        return min(starts, key=lambda m: len(m["name"])), False

    contains = [m for m in mantras if q in m["name"].lower()]
    if contains:
        return min(contains, key=lambda m: len(m["name"])), False

    names = [m["name"] for m in mantras]
    match = fuzz.extractOne(query, names, score_cutoff=70)
    if not match:
        return None, False
    return next((m for m in mantras if m["name"] == match[0]), None), True


def search_by_attribute(attribute: str):
    """Find all mantras with a given attribute (e.g. 'Flamecharm')."""
    canonical = normalize_stat(attribute)
    if not canonical:
        # Maybe it's an oath name like "Arcwarder" — try a substring match too
        attr_lower = attribute.lower()
        return [
            m for m in get_mantras()
            if any(attr_lower in (a or "").lower() for a in (m.get("attributes") or []))
        ]
    return [
        m for m in get_mantras()
        if canonical in (m.get("attributes") or [])
    ]


def filter_results(results, category=None, mantra_type=None, max_stars=None):
    out = results
    if category:
        cat_l = category.lower()
        out = [m for m in out if (m.get("category") or "").lower() == cat_l]
    if mantra_type:
        t_l = mantra_type.lower()
        out = [m for m in out if (m.get("type") or "").lower() == t_l]
    if max_stars is not None:
        out = [m for m in out if (m.get("stars") or 0) <= max_stars]
    return out


def autocomplete_names(prefix: str, limit: int = 25):
    p = (prefix or "").strip().lower()
    mantras = get_mantras()
    if not mantras:
        return []
    if not p:
        return [m["name"] for m in mantras[:limit]]
    starts = [m["name"] for m in mantras if m["name"].lower().startswith(p)]
    contains = [m["name"] for m in mantras if p in m["name"].lower() and not m["name"].lower().startswith(p)]
    return (starts + contains)[:limit]


# ---------------------------------------------------------------------------
# Embed formatting
# ---------------------------------------------------------------------------

def _stars_to_str(stars):
    if not stars:
        return "Base"
    return "★" * stars + f" ({stars}-star)"


def _format_damage(damage_blocks):
    """Render the damage table. Mantras can have multiple variants."""
    if not damage_blocks:
        return ""
    lines = []
    for block in damage_blocks:
        variant = block.get("variant")
        levels = block.get("levels") or []
        if variant:
            lines.append(f"**Variant: {variant}**")
        # Compact: L1: 44 | L5: 61.6 | GB: 0
        cells = []
        for lvl in levels:
            name = lvl.get("level")
            dmg = lvl.get("damage")
            if dmg is None or dmg == 0:
                continue
            cells.append(f"{name}: {dmg}")
        if cells:
            lines.append(" · ".join(cells))
    return "\n".join(lines)


def _format_requirements(reqs):
    if not isinstance(reqs, dict) or not reqs:
        return ""
    lines = []
    stats = reqs.get("stats") or {}
    if isinstance(stats, dict) and stats:
        lines.append("**Stats:** " + ", ".join(f"{v} {k}" for k, v in stats.items()))
    if reqs.get("talents"):
        lines.append("**Talents:** " + ", ".join(reqs["talents"]))
    if reqs.get("origin"):
        lines.append(f"**Origin:** {reqs['origin']}")
    if reqs.get("memento"):
        lines.append(f"**Memento:** {reqs['memento']}")
    if reqs.get("weaponType"):
        wt = reqs["weaponType"]
        lines.append("**Weapon Type:** " + (", ".join(wt) if isinstance(wt, list) else str(wt)))
    if reqs.get("objectives"):
        obj = reqs["objectives"]
        lines.append("**Objectives:** " + (", ".join(obj) if isinstance(obj, list) else str(obj)))
    if reqs.get("slay"):
        s = reqs["slay"]
        lines.append("**Slay:** " + (", ".join(s) if isinstance(s, list) else str(s)))
    if reqs.get("or"):
        lines.append(f"**Or:** {reqs['or']}")
    return "\n".join(lines)


def build_mantra_embed(mantra: dict, did_you_mean: bool = False) -> discord.Embed:
    # Color: type takes priority, then category
    color = TYPE_COLORS.get(mantra.get("type"))
    if color is None:
        color = CATEGORY_COLORS.get(mantra.get("category"), 0x95a5a6)

    title = mantra["name"]
    if mantra.get("VOI"):
        title += " 🛡️"
    if mantra.get("vaulted"):
        title += " (Vaulted)"

    embed = discord.Embed(title=title, color=color)
    if mantra.get("wiki"):
        embed.url = mantra["wiki"]
    if did_you_mean:
        embed.set_author(name=f'💡 Did you mean "{mantra["name"]}"?')

    embed.add_field(name="Type", value=mantra.get("type") or "Normal", inline=True)
    embed.add_field(name="Category", value=mantra.get("category") or "—", inline=True)
    embed.add_field(name="Stars", value=_stars_to_str(mantra.get("stars")), inline=True)

    attrs = mantra.get("attributes") or []
    if attrs:
        embed.add_field(name="Attributes", value=", ".join(attrs), inline=False)

    desc = (mantra.get("description") or "").strip()
    if desc:
        embed.add_field(name="Description", value=desc[:1024], inline=False)

    misc = (mantra.get("miscellaneous") or "").strip()
    if misc:
        embed.add_field(name="Effect", value=misc[:1024], inline=False)

    reqs_text = _format_requirements(mantra.get("requirements"))
    if reqs_text:
        embed.add_field(name="Requirements", value=reqs_text[:1024], inline=False)

    dmg_text = _format_damage(mantra.get("damage"))
    if dmg_text:
        embed.add_field(name="Damage", value=dmg_text[:1024], inline=False)

    scaling = mantra.get("scaling") or {}
    if isinstance(scaling, dict) and scaling:
        embed.add_field(
            name="Scaling",
            value=", ".join(f"{v}x {k}" for k, v in scaling.items()),
            inline=True,
        )

    modifiers = mantra.get("modifiers") or []
    if modifiers:
        embed.add_field(name="Modifiers", value=", ".join(modifiers)[:1024], inline=False)

    sparks = mantra.get("sparks") or []
    if sparks:
        embed.add_field(name="Sparks", value=", ".join(sparks)[:1024], inline=True)

    related = mantra.get("relatedTalents") or []
    if related:
        embed.add_field(name="Related Talents", value=", ".join(related)[:1024], inline=False)

    footer = "Deepwoken Mantra"
    if mantra.get("VOI"):
        footer += " · Vow of Iron exclusive"
    embed.set_footer(text=footer)

    return embed


def build_attribute_results_embeds(attribute: str, results: list,
                                   category: str = None,
                                   mantra_type: str = None,
                                   max_stars: int = None) -> list:
    """Render attribute search results as full embeds (max 9 + overflow)."""
    canonical = normalize_stat(attribute) or attribute

    filter_bits = []
    if category:
        filter_bits.append(f"category={category}")
    if mantra_type:
        filter_bits.append(f"type={mantra_type}")
    if max_stars is not None:
        filter_bits.append(f"max_stars={max_stars}")
    filter_str = f" ({', '.join(filter_bits)})" if filter_bits else ""

    if not results:
        empty = discord.Embed(
            title=f"Mantras for {canonical}{filter_str}",
            description="No mantras found.",
            color=0x2ecc71,
        )
        return [empty]

    has_overflow = len(results) > 10
    show = results[:9] if has_overflow else results[:10]

    embeds = [build_mantra_embed(m) for m in show]

    plural = "es" if len(results) != 1 else ""
    embeds[0].title = (
        f"{embeds[0].title}  —  {len(results)} match{plural} "
        f"for {canonical}{filter_str}"
    )

    if has_overflow:
        remaining = sorted(results[9:], key=lambda m: m["name"].lower())
        lines = [f"• {m['name']}" for m in remaining]
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
    names = autocomplete_names((current or "").strip(), limit=25)
    return [app_commands.Choice(name=n[:100], value=n[:100]) for n in names]


def register(tree: app_commands.CommandTree):
    """Register /mantras and /mantra_random commands on the given tree."""
    category_choices = [app_commands.Choice(name=c, value=c) for c in CATEGORY_CHOICES]
    type_choices = [
        app_commands.Choice(name="Normal", value="Normal"),
        app_commands.Choice(name="Oath", value="Oath"),
        app_commands.Choice(name="Origin", value="Origin"),
        app_commands.Choice(name="Monster", value="Monster"),
        app_commands.Choice(name="Event", value="Event"),
    ]
    star_choices = [
        app_commands.Choice(name="Base (no stars)", value=0),
        app_commands.Choice(name="1-star or below", value=1),
        app_commands.Choice(name="2-star or below", value=2),
        app_commands.Choice(name="3-star or below", value=3),
    ]

    @tree.command(name="mantras", description="Look up Deepwoken mantras by name or attribute")
    @app_commands.describe(
        query='Mantra name (e.g. "Burning Servants") or attribute (e.g. "Flamecharm")',
        category="Filter by category",
        type="Filter by type",
        max_stars="Filter by max star level",
    )
    @app_commands.autocomplete(query=_autocomplete)
    @app_commands.choices(category=category_choices, type=type_choices, max_stars=star_choices)
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)
    async def mantras_command(
        interaction: discord.Interaction,
        query: str,
        category: app_commands.Choice[str] = None,
        type: app_commands.Choice[str] = None,
        max_stars: app_commands.Choice[int] = None,
    ):
        await interaction.response.defer()
        cat_str = category.value if category else None
        type_str = type.value if type else None
        stars_int = max_stars.value if max_stars is not None else None

        # Try as attribute first (e.g. "Flamecharm")
        canonical = normalize_stat(query)
        if canonical:
            results = search_by_attribute(canonical)
            if cat_str or type_str or stars_int is not None:
                results = filter_results(results, category=cat_str,
                                         mantra_type=type_str, max_stars=stars_int)
            results.sort(key=lambda m: m["name"].lower())
            embeds = build_attribute_results_embeds(
                canonical, results,
                category=cat_str, mantra_type=type_str, max_stars=stars_int,
            )
            await interaction.followup.send(embeds=embeds)
            return

        # Otherwise look up by name
        mantra, was_fuzzy = search_by_name(query)
        if not mantra:
            await interaction.followup.send(
                f"❌ No mantra found matching `{query}`. Check your spelling and try again."
            )
            return
        embed = build_mantra_embed(mantra, did_you_mean=was_fuzzy)
        await interaction.followup.send(embed=embed)

    @mantras_command.error
    async def _mantras_err(interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            try:
                await interaction.response.send_message(
                    f"⏳ Slow down — try again in {error.retry_after:.1f}s.",
                    ephemeral=True,
                )
            except Exception:
                pass
        else:
            print(f"[Mantras] Command error: {error}")

    @tree.command(name="mantra_random", description="Pull a random Deepwoken mantra")
    @app_commands.describe(
        category="Optional: filter by category",
        type="Optional: filter by type",
    )
    @app_commands.choices(category=category_choices, type=type_choices)
    @app_commands.checks.cooldown(1, 2.0, key=lambda i: i.user.id)
    async def mantra_random_command(
        interaction: discord.Interaction,
        category: app_commands.Choice[str] = None,
        type: app_commands.Choice[str] = None,
    ):
        await interaction.response.defer()
        pool = get_mantras()
        if category:
            pool = [m for m in pool if (m.get("category") or "") == category.value]
        if type:
            pool = [m for m in pool if (m.get("type") or "") == type.value]
        if not pool:
            await interaction.followup.send("❌ No mantras matched that filter.")
            return
        pick = random.choice(pool)
        embed = build_mantra_embed(pick)
        await interaction.followup.send(embed=embed)

    @mantra_random_command.error
    async def _mr_err(interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            try:
                await interaction.response.send_message(
                    f"⏳ Slow down — try again in {error.retry_after:.1f}s.",
                    ephemeral=True,
                )
            except Exception:
                pass
        else:
            print(f"[MantraRandom] Command error: {error}")
