"""Deepwoken talent lookup."""

import random
import re

import discord
from discord import app_commands
from rapidfuzz import process as fuzz

from lookup_base import BaseLookup, cooldown_error_handler, truncate

RARITY_COLORS = {
    "Common": 0x95a5a6, "Rare": 0x3498db, "Advanced": 0x9b59b6,
    "Oath": 0xe74c3c, "Innate": 0x2ecc71, "Quest": 0xf39c12,
    "Murmur": 0x1abc9c, "Spec": 0x1abc9c, "Faction": 0xe67e22,
    "Origin": 0x34495e, "Equipment": 0x7f8c8d, "Outfit": 0x7f8c8d,
    "Memento": 0x8e44ad, "Weapon": 0xf1c40f,
}

ALL_RARITIES = [
    "Common", "Rare", "Advanced", "Oath", "Innate",
    "Quest", "Murmur", "Spec", "Faction", "Origin",
    "Equipment", "Outfit", "Memento", "Weapon",
]

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
    "light": "Light Weapon", "lightweapon": "Light Weapon",
    "med": "Medium Weapon", "medium": "Medium Weapon", "mediumweapon": "Medium Weapon",
    "heavy": "Heavy Weapon", "heavyweapon": "Heavy Weapon",
}

CANONICAL_STATS = sorted(set(STAT_ALIASES.values()))

_REQ_LABELS = {
    "stats": "Stats", "talents": "Talents", "mantras": "Mantras",
    "weapon": "Weapon", "weaponType": "Weapon Type", "equipment": "Equipment",
    "outfit": "Outfit", "set": "Set", "aspect": "Aspect",
    "origin": "Origin", "memento": "Memento", "murmur": "Murmur",
    "quests": "Quest", "objectives": "Objectives", "slay": "Slay",
    "or": "Or", "add": "Additional",
}


def normalize_stat(s):
    if not s:
        return None
    key = s.lower().replace(" ", "")
    if key in STAT_ALIASES:
        return STAT_ALIASES[key]
    m = fuzz.extractOne(s, CANONICAL_STATS, score_cutoff=60)
    return m[0] if m else None


class TalentLookup(BaseLookup):
    DATA_FILE = "talents.json"
    LOG_TAG = "Talents"

    def search_by_stat(self, stat, level, mode="exact",
                       include_oaths=False, include_mantra_unlocks=False):
        canonical = normalize_stat(stat)
        if not canonical:
            return []

        results = []
        for t in self.get():
            if not include_oaths and (t.get("rarity") or "") == "Oath":
                continue
            if not include_mantra_unlocks and _is_mantra_unlock(t):
                continue
            stats = ((t.get("requirements") or {}).get("stats") or {})
            if not isinstance(stats, dict):
                continue
            v = stats.get(canonical)
            if v is None:
                continue
            if (mode == "gte" and v >= level) or (mode == "exact" and v == level):
                results.append(t)

        results.sort(key=lambda t: t["name"].lower())
        return results

    @staticmethod
    def filter_results(results, rarity=None, category=None):
        out = results
        if rarity:
            r = rarity.lower()
            out = [t for t in out if (t.get("rarity") or "").lower() == r]
        if category:
            c = category.lower()
            out = [t for t in out if c in (t.get("category") or "").lower()]
        return out


def _is_mantra_unlock(talent):
    desc = (talent.get("description") or "").lower()
    return "you can now obtain" in desc and "leveled" in desc and "mantras" in desc


def parse_stat_query(query):
    """'40 Agility' / '40+ Agility' / 'Agility 40' → (level, stat, mode) or None."""
    query = (query or "").strip()
    m = re.match(r"^(\d+)(\+?)\s+(.+)$", query)
    if m:
        return int(m.group(1)), m.group(3).strip(), ("gte" if m.group(2) else "exact")
    m = re.match(r"^(.+?)\s+(\d+)(\+?)$", query)
    if m:
        return int(m.group(2)), m.group(1).strip(), ("gte" if m.group(3) else "exact")
    return None


def _format_requirements(reqs):
    if not isinstance(reqs, dict) or not reqs:
        return ""
    lines = []
    for key, label in _REQ_LABELS.items():
        if key not in reqs:
            continue
        v = reqs[key]
        if not v:
            continue
        if key == "stats" and isinstance(v, dict):
            text = ", ".join(f"{n} {k}" for k, n in v.items())
        elif isinstance(v, list):
            text = ", ".join(v)
        else:
            text = str(v)
        if text:
            lines.append(f"**{label}:** {text}")
    return "\n".join(lines)


def build_talent_embed(talent, did_you_mean=False):
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

    bonuses = talent.get("stats")
    if isinstance(bonuses, dict) and bonuses:
        embed.add_field(
            name="Bonuses",
            value=", ".join(f"+{v} {k}" for k, v in bonuses.items()),
            inline=True,
        )

    if talent.get("description"):
        embed.add_field(name="Description",
                        value=truncate(talent["description"].strip(), 1024),
                        inline=False)

    reqs_text = _format_requirements(talent.get("requirements"))
    if reqs_text:
        embed.add_field(name="Requirements", value=truncate(reqs_text, 1024), inline=False)

    me = talent.get("mutualExclusives") or []
    if me:
        embed.add_field(name="Mutually Exclusive",
                        value=truncate(", ".join(me), 1024), inline=False)

    if talent.get("additionalInfo"):
        embed.add_field(name="Notes",
                        value=truncate(talent["additionalInfo"].strip(), 1024),
                        inline=False)

    footer = "Deepwoken Talent"
    if talent.get("VOI"):
        footer += " · Vow of Iron exclusive"
    embed.set_footer(text=footer)
    return embed


def build_stat_results_embeds(stat, level, results, mode="exact",
                              rarity=None, category=None):
    canonical = normalize_stat(stat) or stat
    op = "≥" if mode == "gte" else "="

    bits = []
    if rarity: bits.append(f"rarity={rarity}")
    if category: bits.append(f"category={category}")
    filter_str = f" ({', '.join(bits)})" if bits else ""

    if not results:
        return [discord.Embed(
            title=f"Talents requiring {canonical} {op} {level}{filter_str}",
            description="No talents found.",
            color=0x2ecc71,
        )]

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
        lines = [f"• {t['name']}" for t in remaining]
        desc = "\n".join(lines[:40])
        if len(lines) > 40:
            desc += f"\n…and {len(lines) - 40} more"
        embeds.append(discord.Embed(
            title=f"+ {len(remaining)} more",
            description=desc,
            color=0x95a5a6,
        ))
    return embeds


# ---------------------------------------------------------------------------
# Module singleton + slash registration
# ---------------------------------------------------------------------------

_lookup = TalentLookup()


def refresh_cache():
    _lookup.refresh_cache()


async def _autocomplete(interaction, current):
    stripped = (current or "").strip()
    if re.match(r"^\d+\+?(\s+|$)", stripped):
        return []
    names = _lookup.autocomplete_names(stripped, limit=25)
    return [app_commands.Choice(name=n[:100], value=n[:100]) for n in names]


def register(tree):
    rarity_choices = [app_commands.Choice(name=r, value=r) for r in ALL_RARITIES]

    @tree.command(name="talents", description="Look up Deepwoken talents by name or stat requirement")
    @app_commands.describe(
        query='Talent name or stat requirement ("40 Agility", "40+ Agility")',
        rarity="Filter by rarity (stat searches only)",
        category="Filter by category text (stat searches only)",
    )
    @app_commands.autocomplete(query=_autocomplete)
    @app_commands.choices(rarity=rarity_choices)
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)
    async def talents_cmd(interaction, query: str,
                          rarity: app_commands.Choice[str] = None,
                          category: str = None):
        await interaction.response.defer()
        rarity_str = rarity.value if rarity else None
        sq = parse_stat_query(query)

        if sq:
            level, stat, mode = sq
            include_oaths = (rarity_str == "Oath")
            results = _lookup.search_by_stat(stat, level, mode=mode, include_oaths=include_oaths)
            if rarity_str or category:
                results = _lookup.filter_results(results, rarity=rarity_str, category=category)
            embeds = build_stat_results_embeds(stat, level, results,
                                               mode=mode, rarity=rarity_str, category=category)
            await interaction.followup.send(embeds=embeds)
            return

        talent, was_fuzzy = _lookup.search_by_name(query)
        if not talent:
            await interaction.followup.send(
                f"❌ No talent found matching `{query}`. Check your spelling and try again."
            )
            return
        await interaction.followup.send(embed=build_talent_embed(talent, did_you_mean=was_fuzzy))

    @talents_cmd.error
    async def _err(interaction, error):
        await cooldown_error_handler(interaction, error, "Talents")

    @tree.command(name="talent_random", description="Pull a random Deepwoken talent")
    @app_commands.describe(rarity="Optional: filter by rarity")
    @app_commands.choices(rarity=rarity_choices)
    @app_commands.checks.cooldown(1, 2.0, key=lambda i: i.user.id)
    async def random_cmd(interaction, rarity: app_commands.Choice[str] = None):
        await interaction.response.defer()
        pool = _lookup.get()
        if rarity:
            pool = [t for t in pool if (t.get("rarity") or "") == rarity.value]
        if not pool:
            await interaction.followup.send("❌ No talents matched that filter.")
            return
        await interaction.followup.send(embed=build_talent_embed(random.choice(pool)))

    @random_cmd.error
    async def _r_err(interaction, error):
        await cooldown_error_handler(interaction, error, "TalentRandom")

    race_choices = [app_commands.Choice(name=r.capitalize(), value=r) for r in [
        "adret", "canor", "capra", "celtor", "chrysid", "drakkard", "etrean",
        "felinor", "ganymede", "gremor", "khan", "kiron", "lightborn",
        "tiran", "vesperian", "none",
    ]]

    @tree.command(name="required",
                  description="List the minimum stats needed for a set of talents")
    @app_commands.describe(
        talents='Comma-separated talent names (e.g. "Ghost, Kick Off, Adept Flamecharmer")',
        race="Optional: subtract racial bonuses from required investment",
    )
    @app_commands.choices(race=race_choices)
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)
    async def required_cmd(interaction, talents: str,
                           race: app_commands.Choice[str] = None):
        await interaction.response.defer()
        race_key = race.value if race else None
        embed = build_required_embed(talents, race_key)
        await interaction.followup.send(embed=embed)

    @required_cmd.error
    async def _req_err(interaction, error):
        await cooldown_error_handler(interaction, error, "Required")


# ---------------------------------------------------------------------------
# /required — minimum stats for a set of talents
# ---------------------------------------------------------------------------

RACIAL_BONUSES = {
    "adret":     {"Charisma": 3, "Willpower": 2},
    "canor":     {"Strength": 3, "Charisma": 2},
    "capra":     {"Intelligence": 3, "Willpower": 2},
    "celtor":    {"Charisma": 3, "Intelligence": 2},
    "chrysid":   {"Charisma": 3, "Agility": 2},
    "drakkard":  {"Agility": 3, "Fortitude": 2},
    "etrean":    {"Intelligence": 3, "Agility": 2},
    "felinor":   {"Agility": 3, "Charisma": 2},
    "ganymede":  {"Willpower": 3, "Intelligence": 2},
    "gremor":    {"Fortitude": 3, "Strength": 2},
    "khan":      {"Strength": 3, "Agility": 2},
    "kiron":     {"Agility": 3, "Intelligence": 2},
    "lightborn": {"Strength": 2, "Fortitude": 2, "Agility": 2,
                  "Intelligence": 2, "Willpower": 2, "Charisma": 2},
    "tiran":     {"Agility": 3, "Willpower": 2},
    "vesperian": {"Fortitude": 3, "Willpower": 2},
    "none":      {},
}

TOTAL_POINTS = 330


def build_required_embed(query: str, race: str = None) -> discord.Embed:
    # Parse comma-separated list
    names = [n.strip() for n in query.split(",") if n.strip()]
    if not names:
        return discord.Embed(
            title="❌ Required Stats",
            description="Provide at least one talent name (comma-separated).",
            color=0xe74c3c,
        )

    resolved = []   # list of (input_name, talent_dict | None, was_fuzzy)
    for name in names:
        t, was_fuzzy = _lookup.search_by_name(name)
        resolved.append((name, t, was_fuzzy))

    # Aggregate: max per stat across all matched talents
    aggregated = {}      # stat -> max required
    or_clauses = []      # list of (talent_name, or_list)
    talent_prereqs = []  # list of (talent_name, [required talent names])
    other_reqs = []      # list of (talent_name, label, value) for non-stat reqs
    not_found = []
    fuzzy_hits = []      # list of (input, matched)

    for name, t, was_fuzzy in resolved:
        if not t:
            not_found.append(name)
            continue
        if was_fuzzy:
            fuzzy_hits.append((name, t["name"]))

        reqs = t.get("requirements") or {}
        if not isinstance(reqs, dict):
            continue

        stats = reqs.get("stats") or {}
        if isinstance(stats, dict):
            for stat, value in stats.items():
                aggregated[stat] = max(aggregated.get(stat, 0), value)

        if reqs.get("or"):
            or_clauses.append((t["name"], reqs["or"]))
        if reqs.get("talents"):
            talent_prereqs.append((t["name"], reqs["talents"]))

        # Note any other meaningful prerequisites
        for key, label in [
            ("origin", "Origin"), ("memento", "Memento"), ("murmur", "Murmur"),
            ("equipment", "Equipment"), ("outfit", "Outfit"),
        ]:
            if reqs.get(key):
                v = reqs[key]
                v_str = ", ".join(v) if isinstance(v, list) else str(v)
                other_reqs.append((t["name"], label, v_str))

    # Build the embed
    embed = discord.Embed(title="📊 Required Stats", color=0x3498db)

    # Show matched talents
    matched_lines = []
    for name, t, was_fuzzy in resolved:
        if not t:
            continue
        reqs = t.get("requirements") or {}
        stats = (reqs.get("stats") or {}) if isinstance(reqs, dict) else {}
        stat_str = ", ".join(f"{v} {k}" for k, v in stats.items()) if stats else "no stat req"
        marker = " 🔁" if was_fuzzy else ""
        matched_lines.append(f"• **{t['name']}**{marker} — {stat_str}")

    if matched_lines:
        embed.add_field(name="Talents", value=truncate("\n".join(matched_lines), 1024), inline=False)

    if not_found:
        embed.add_field(name="❌ Not found",
                        value=truncate(", ".join(f"`{n}`" for n in not_found), 1024),
                        inline=False)

    # Aggregated requirements
    if aggregated:
        # Calculate investment cost (after subtracting racial bonuses if race given)
        race_bonuses = RACIAL_BONUSES.get(race or "", {})
        rows = []
        total_required = 0     # raw stat values needed
        total_invested = 0     # actual point cost (after racials)
        for stat in sorted(aggregated):
            need = aggregated[stat]
            racial = race_bonuses.get(stat, 0)
            invest = max(0, need - racial)
            total_required += need
            total_invested += invest
            if racial:
                rows.append(f"**{stat}:** {need} _(invest {invest}, race gives +{racial})_")
            else:
                rows.append(f"**{stat}:** {need}")

        # Cap warnings
        warnings = []
        for stat, val in aggregated.items():
            invest = max(0, val - race_bonuses.get(stat, 0))
            if invest > 100:
                warnings.append(f"⚠️ {stat} requires {invest} invested points — exceeds the 100 cap!")

        embed.add_field(name="Minimum stats", value=truncate("\n".join(rows), 1024), inline=False)

        if race:
            embed.add_field(
                name=f"Points used (as {race.capitalize()})",
                value=f"**{total_invested} / {TOTAL_POINTS}** — **{TOTAL_POINTS - total_invested}** left",
                inline=False,
            )
        else:
            embed.add_field(
                name="Points used",
                value=f"**{total_invested} / {TOTAL_POINTS}** — **{TOTAL_POINTS - total_invested}** left\n"
                      "_Pass a `race` to subtract racial bonuses._",
                inline=False,
            )

        if total_invested > TOTAL_POINTS:
            warnings.append(f"⚠️ Over budget by {total_invested - TOTAL_POINTS} points.")
        if warnings:
            embed.add_field(name="Warnings", value="\n".join(warnings), inline=False)

    # Show OR clauses as alternatives
    if or_clauses:
        or_lines = []
        for tname, clauses in or_clauses:
            opts = []
            for clause in clauses:
                if isinstance(clause, dict):
                    s = clause.get("stats") or {}
                    if s:
                        opts.append(", ".join(f"{v} {k}" for k, v in s.items()))
            if opts:
                or_lines.append(f"• **{tname}**: requires ONE of — {' OR '.join(opts)}")
        if or_lines:
            embed.add_field(name="OR clauses (pick one option each)",
                            value=truncate("\n".join(or_lines), 1024),
                            inline=False)

    # Show talent prereqs
    if talent_prereqs:
        lines = [f"• **{tname}**: needs one of — {', '.join(reqs)}"
                 for tname, reqs in talent_prereqs]
        embed.add_field(name="Prerequisite talents",
                        value=truncate("\n".join(lines), 1024),
                        inline=False)

    if other_reqs:
        grouped = {}
        for tname, label, val in other_reqs:
            grouped.setdefault(tname, []).append(f"{label}: {val}")
        lines = [f"• **{tname}**: {' · '.join(items)}" for tname, items in grouped.items()]
        embed.add_field(name="Other requirements",
                        value=truncate("\n".join(lines), 1024),
                        inline=False)

    if fuzzy_hits:
        hint = ", ".join(f'`{inp}` → "{m}"' for inp, m in fuzzy_hits)
        embed.set_footer(text=f"🔁 fuzzy-matched: {hint}")
    elif not_found:
        embed.set_footer(text="❌ markers mean the name didn't match any talent")

    return embed
