"""
Deepwoken weapon lookup backed by a local weapons.json file.
"""

import json
import os

import discord
from rapidfuzz import process as fuzz

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weapons.json")

_cache = {"weapons": []}

# ---------------------------------------------------------------------------
# Color & display
# ---------------------------------------------------------------------------

RARITY_COLORS = {
    "Common":    0x95a5a6,
    "Uncommon":  0x7f8c8d,
    "Rare":      0x3498db,
    "Legendary": 0xf1c40f,
    "Mythical":  0xe74c3c,
    "Relic":     0x9b59b6,
    "Unique":    0x1abc9c,
    "Named":     0xe67e22,
    "Exclusive": 0x34495e,
    "Unknown":   0x95a5a6,
}

ALL_RARITIES = [
    "Common", "Uncommon", "Rare", "Legendary", "Mythical",
    "Relic", "Unique", "Named", "Exclusive", "Unknown",
]

# All weapon types present in the data
ALL_TYPES = [
    "Dagger", "Fist", "Pistol", "Rapier", "Sword", "Spear", "Staff",
    "Club", "Rifle", "Twinblade", "Bow", "Greataxe", "Greatsword",
    "Greathammer", "Greatcannon", "Shield", "Parrying Dagger", "Exclusive",
]

TYPE_ALIASES = {
    "dagger": "Dagger", "daggers": "Dagger",
    "fist": "Fist", "fists": "Fist",
    "pistol": "Pistol", "pistols": "Pistol",
    "rapier": "Rapier", "rapiers": "Rapier",
    "sword": "Sword", "swords": "Sword",
    "spear": "Spear", "spears": "Spear",
    "staff": "Staff", "staves": "Staff", "staffs": "Staff",
    "club": "Club", "clubs": "Club", "mace": "Club", "maces": "Club",
    "rifle": "Rifle", "rifles": "Rifle",
    "twinblade": "Twinblade", "twinblades": "Twinblade",
    "bow": "Bow", "bows": "Bow",
    "greataxe": "Greataxe", "greataxes": "Greataxe",
    "greatsword": "Greatsword", "greatswords": "Greatsword",
    "greathammer": "Greathammer", "greathammers": "Greathammer",
    "greatcannon": "Greatcannon", "greatcannons": "Greatcannon",
    "shield": "Shield", "shields": "Shield",
    "parrydagger": "Parrying Dagger", "parryingdagger": "Parrying Dagger",
}


def normalize_type(s: str):
    if not s:
        return None
    key = s.lower().replace(" ", "")
    if key in TYPE_ALIASES:
        return TYPE_ALIASES[key]
    m = fuzz.extractOne(s, ALL_TYPES, score_cutoff=60)
    return m[0] if m else None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_weapons():
    if _cache["weapons"]:
        return _cache["weapons"]
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            _cache["weapons"] = json.load(f)
        print(f"[Weapons] Loaded {len(_cache['weapons'])} weapons from {DATA_PATH}")
    except FileNotFoundError:
        print(f"[Weapons] ERROR: {DATA_PATH} not found.")
        _cache["weapons"] = []
    except Exception as e:
        print(f"[Weapons] ERROR loading {DATA_PATH}: {e}")
        _cache["weapons"] = []
    return _cache["weapons"]


def get_weapons():
    return load_weapons()


def refresh_cache():
    _cache["weapons"] = []
    load_weapons()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_by_name(query: str):
    """Returns (weapon_dict, was_fuzzy_guess) or (None, False)."""
    weapons = get_weapons()
    if not weapons:
        return None, False
    q = query.strip().lower()
    if not q:
        return None, False

    for w in weapons:
        if w["name"].lower() == q:
            return w, False

    starts = [w for w in weapons if w["name"].lower().startswith(q)]
    if starts:
        return min(starts, key=lambda w: len(w["name"])), False

    contains = [w for w in weapons if q in w["name"].lower()]
    if contains:
        return min(contains, key=lambda w: len(w["name"])), False

    names = [w["name"] for w in weapons]
    match = fuzz.extractOne(query, names, score_cutoff=70)
    if not match:
        return None, False
    return next((w for w in weapons if w["name"] == match[0]), None), True


def search_by_type(weapon_type: str):
    canonical = normalize_type(weapon_type)
    if not canonical:
        # Substring fallback for combo types like "Sword / Greatsword"
        wt_lower = weapon_type.lower()
        return [w for w in get_weapons() if wt_lower in (w.get("type") or "").lower()]
    return [w for w in get_weapons() if canonical == (w.get("type") or "")
            or canonical in (w.get("type") or "")]


def filter_results(results, rarity=None, damage_type=None):
    out = results
    if rarity:
        rarity_l = rarity.lower()
        out = [w for w in out if (w.get("rarity") or "").lower() == rarity_l]
    if damage_type:
        dt_l = damage_type.lower()
        out = [w for w in out
               if any(dt_l == (d or "").lower() for d in (w.get("damageTypes") or []))]
    return out


def autocomplete_names(prefix: str, limit: int = 25):
    p = (prefix or "").strip().lower()
    weapons = get_weapons()
    if not weapons:
        return []
    if not p:
        return [w["name"] for w in weapons[:limit]]
    starts = [w["name"] for w in weapons if w["name"].lower().startswith(p)]
    contains = [w["name"] for w in weapons if p in w["name"].lower() and not w["name"].lower().startswith(p)]
    return (starts + contains)[:limit]


# ---------------------------------------------------------------------------
# Embed formatting
# ---------------------------------------------------------------------------

def _format_requirements(reqs):
    if not isinstance(reqs, dict) or not reqs:
        return ""
    lines = []
    stats = reqs.get("stats") or {}
    if isinstance(stats, dict) and stats:
        lines.append(", ".join(f"{v} {k}" for k, v in stats.items()))
    if reqs.get("talents"):
        lines.append("Talents: " + ", ".join(reqs["talents"]))
    return "\n".join(lines)


def _format_scaling(scaling):
    if not isinstance(scaling, dict) or not scaling:
        return ""
    return ", ".join(f"{v}× {k}" for k, v in scaling.items())


def build_weapon_embed(weapon: dict, did_you_mean: bool = False) -> discord.Embed:
    color = RARITY_COLORS.get(weapon.get("rarity", ""), 0x95a5a6)
    title = weapon["name"]
    if weapon.get("VOI"):
        title += " 🛡️"

    embed = discord.Embed(title=title, color=color)
    if did_you_mean:
        embed.set_author(name=f'💡 Did you mean "{weapon["name"]}"?')

    embed.add_field(name="Type", value=weapon.get("type") or "—", inline=True)
    embed.add_field(name="Rarity", value=weapon.get("rarity") or "—", inline=True)
    embed.add_field(name="Range Type", value=weapon.get("rangeType") or "—", inline=True)

    # Core combat stats
    dmg = weapon.get("damage")
    if dmg is not None:
        dmg_types = weapon.get("damageTypes") or []
        dmg_str = f"**{dmg}**"
        if dmg_types:
            dmg_str += f" ({', '.join(dmg_types)})"
        embed.add_field(name="Damage", value=dmg_str, inline=True)

    if weapon.get("postureDamage") is not None:
        embed.add_field(name="Posture Damage", value=str(weapon["postureDamage"]), inline=True)
    if weapon.get("range") is not None:
        embed.add_field(name="Range", value=str(weapon["range"]), inline=True)
    if weapon.get("swingSpeed") is not None:
        embed.add_field(name="Swing Speed", value=str(weapon["swingSpeed"]), inline=True)
    if weapon.get("attackDuration"):
        embed.add_field(name="Attack Duration", value=str(weapon["attackDuration"]), inline=True)
    if weapon.get("penetration") is not None:
        embed.add_field(name="Penetration", value=str(weapon["penetration"]), inline=True)
    if weapon.get("bleedDamage") is not None:
        embed.add_field(name="Bleed Damage", value=str(weapon["bleedDamage"]), inline=True)
    if weapon.get("chipDamage") is not None:
        embed.add_field(name="Chip Damage", value=str(weapon["chipDamage"]), inline=True)
    if weapon.get("postureMax") is not None:
        embed.add_field(name="Posture Max", value=str(weapon["postureMax"]), inline=True)
    if weapon.get("postureRestoration") is not None:
        embed.add_field(name="Posture Restore", value=str(weapon["postureRestoration"]), inline=True)
    if weapon.get("endlag") is not None:
        embed.add_field(name="Endlag", value=str(weapon["endlag"]), inline=True)

    reqs = _format_requirements(weapon.get("requirements"))
    if reqs:
        embed.add_field(name="Requirements", value=reqs[:1024], inline=False)

    scaling = _format_scaling(weapon.get("scaling"))
    if scaling:
        embed.add_field(name="Scaling", value=scaling[:1024], inline=False)

    granted = weapon.get("grantedTalents") or []
    if granted:
        embed.add_field(name="Granted Talents", value=", ".join(granted)[:1024], inline=False)

    desc = (weapon.get("description") or "").strip()
    if desc:
        embed.add_field(name="Description", value=desc[:1024], inline=False)

    flags = []
    if weapon.get("enchantable"):
        flags.append("✅ Enchantable")
    else:
        flags.append("❌ Not Enchantable")
    if weapon.get("equipMotifs"):
        flags.append("✅ Equip Motifs")
    if flags:
        embed.add_field(name="Flags", value=" · ".join(flags), inline=False)

    footer = "Deepwoken Weapon"
    if weapon.get("VOI"):
        footer += " · Vow of Iron exclusive"
    embed.set_footer(text=footer)

    return embed


def build_type_results_embeds(weapon_type: str, results: list,
                              rarity: str = None,
                              damage_type: str = None) -> list:
    canonical = normalize_type(weapon_type) or weapon_type

    filter_bits = []
    if rarity:
        filter_bits.append(f"rarity={rarity}")
    if damage_type:
        filter_bits.append(f"damage={damage_type}")
    filter_str = f" ({', '.join(filter_bits)})" if filter_bits else ""

    if not results:
        empty = discord.Embed(
            title=f"{canonical} weapons{filter_str}",
            description="No weapons found.",
            color=0x2ecc71,
        )
        return [empty]

    has_overflow = len(results) > 10
    show = results[:9] if has_overflow else results[:10]

    embeds = [build_weapon_embed(w) for w in show]

    plural = "s" if len(results) != 1 else ""
    embeds[0].title = (
        f"{embeds[0].title}  —  {len(results)} {canonical} weapon{plural}{filter_str}"
    )

    if has_overflow:
        remaining = sorted(results[9:], key=lambda w: w["name"].lower())
        lines = [f"• {w['name']} _({w.get('rarity', '—')})_" for w in remaining]
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

DAMAGE_TYPE_CHOICES = [
    "Slash", "Blunt", "Bleed", "Wither", "Attunement",
    "Flamecharm", "Frostdraw", "Thundercall", "Galebreathe",
    "Shadowcast", "Ironsing", "Bloodrend",
]


async def _autocomplete(interaction, current: str):
    names = autocomplete_names((current or "").strip(), limit=25)
    return [app_commands.Choice(name=n[:100], value=n[:100]) for n in names]


def register(tree: app_commands.CommandTree):
    """Register /weapons and /weapon_random commands on the given tree."""
    rarity_choices = [app_commands.Choice(name=r, value=r) for r in ALL_RARITIES]
    type_choices = [app_commands.Choice(name=t, value=t) for t in ALL_TYPES]
    dmg_choices = [app_commands.Choice(name=d, value=d) for d in DAMAGE_TYPE_CHOICES]

    @tree.command(name="weapons", description="Look up Deepwoken weapons by name or type")
    @app_commands.describe(
        query='Weapon name (e.g. "Sanguine Transfuser") or type (e.g. "Greatsword")',
        rarity="Filter by rarity (only applies to type searches)",
        damage_type="Filter by damage type (only applies to type searches)",
    )
    @app_commands.autocomplete(query=_autocomplete)
    @app_commands.choices(rarity=rarity_choices, damage_type=dmg_choices)
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)
    async def weapons_command(
        interaction: discord.Interaction,
        query: str,
        rarity: app_commands.Choice[str] = None,
        damage_type: app_commands.Choice[str] = None,
    ):
        await interaction.response.defer()
        rarity_str = rarity.value if rarity else None
        dmg_str = damage_type.value if damage_type else None

        # If query matches a weapon type, do a type search
        canonical_type = normalize_type(query)
        if canonical_type:
            results = search_by_type(canonical_type)
            if rarity_str or dmg_str:
                results = filter_results(results, rarity=rarity_str, damage_type=dmg_str)
            results.sort(key=lambda w: w["name"].lower())
            embeds = build_type_results_embeds(
                canonical_type, results, rarity=rarity_str, damage_type=dmg_str,
            )
            await interaction.followup.send(embeds=embeds)
            return

        # Otherwise look up by name
        weapon, was_fuzzy = search_by_name(query)
        if not weapon:
            await interaction.followup.send(
                f"❌ No weapon found matching `{query}`. Check your spelling and try again."
            )
            return
        embed = build_weapon_embed(weapon, did_you_mean=was_fuzzy)
        await interaction.followup.send(embed=embed)

    @weapons_command.error
    async def _w_err(interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            try:
                await interaction.response.send_message(
                    f"⏳ Slow down — try again in {error.retry_after:.1f}s.",
                    ephemeral=True,
                )
            except Exception:
                pass
        else:
            print(f"[Weapons] Command error: {error}")

    @tree.command(name="weapon_random", description="Pull a random Deepwoken weapon")
    @app_commands.describe(
        rarity="Optional: filter by rarity",
        type="Optional: filter by weapon type",
    )
    @app_commands.choices(rarity=rarity_choices, type=type_choices)
    @app_commands.checks.cooldown(1, 2.0, key=lambda i: i.user.id)
    async def weapon_random_command(
        interaction: discord.Interaction,
        rarity: app_commands.Choice[str] = None,
        type: app_commands.Choice[str] = None,
    ):
        await interaction.response.defer()
        pool = get_weapons()
        if rarity:
            pool = [w for w in pool if (w.get("rarity") or "") == rarity.value]
        if type:
            pool = [w for w in pool if type.value in (w.get("type") or "")]
        if not pool:
            await interaction.followup.send("❌ No weapons matched that filter.")
            return
        pick = random.choice(pool)
        embed = build_weapon_embed(pick)
        await interaction.followup.send(embed=embed)

    @weapon_random_command.error
    async def _wr_err(interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            try:
                await interaction.response.send_message(
                    f"⏳ Slow down — try again in {error.retry_after:.1f}s.",
                    ephemeral=True,
                )
            except Exception:
                pass
        else:
            print(f"[WeaponRandom] Command error: {error}")
