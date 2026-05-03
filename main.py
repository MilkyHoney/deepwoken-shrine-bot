import discord
from discord import app_commands, ui
import os

from shrine import shrine_of_order, count_points_spent, TOTAL_POINTS, RACIAL_STATS, ALL_STATS, ATTUNEMENTS
from keep_alive import keep_alive

STAT_ALIASES = {
    "str":          "Strength",
    "strength":     "Strength",
    "fort":         "Fortitude",
    "fortitude":    "Fortitude",
    "agi":          "Agility",
    "agility":      "Agility",
    "int":          "Intelligence",
    "intelligence": "Intelligence",
    "will":         "Willpower",
    "willpower":    "Willpower",
    "cha":          "Charisma",
    "charisma":     "Charisma",
    "flame":        "Flamecharm",
    "flamecharm":   "Flamecharm",
    "frost":        "Frostdraw",
    "frostdraw":    "Frostdraw",
    "thunder":      "Thundercall",
    "thundercall":  "Thundercall",
    "gale":         "Galebreathe",
    "galebreathe":  "Galebreathe",
    "shadow":       "Shadowcast",
    "shadowcast":   "Shadowcast",
    "iron":         "Ironsing",
    "ironsing":     "Ironsing",
    "blood":        "Bloodrend",
    "bloodrend":    "Bloodrend",
    "light":        "LightWeapon",
    "lightweapon":  "LightWeapon",
    "med":          "MediumWeapon",
    "mediumweapon": "MediumWeapon",
    "heavy":        "HeavyWeapon",
    "heavyweapon":  "HeavyWeapon",
}

VALID_RACES = ", ".join(f"`{r}`" for r in RACIAL_STATS.keys())


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_base_stats(s: str) -> dict:
    """
    Parses base stats from either:
    - positional: "40 50 25 0 40 55"  (str fort agi int will cha)
    - named:      "str=40 fort=50 agi=25"
    """
    result = {}
    base_order = ["Strength", "Fortitude", "Agility", "Intelligence", "Willpower", "Charisma"]
    s = s.strip()

    if "=" in s:
        for pair in s.split():
            key, val = pair.split("=", 1)
            key = key.strip().lower()
            if key not in STAT_ALIASES:
                raise ValueError(f"Unknown stat: `{key}`")
            stat = STAT_ALIASES[key]
            if stat not in base_order:
                raise ValueError(f"`{key}` is not a base stat — put it in attunements or weapon field")
            result[stat] = int(val)
    else:
        values = s.split()
        if len(values) != 6:
            raise ValueError("Base stats need exactly 6 numbers: `str fort agi int will cha`\nExample: `40 50 25 0 40 55`")
        for stat, val in zip(base_order, values):
            result[stat] = int(val)

    return result


def parse_kv_stats(s: str, allowed: list) -> dict:
    """Parses key=value pairs, only allowing stats in the allowed list."""
    result = {}
    if not s.strip():
        return result
    for pair in s.strip().split():
        if "=" not in pair:
            raise ValueError(f"Invalid format: `{pair}` — use `stat=value` (e.g. `flame=80`)")
        key, val = pair.split("=", 1)
        key = key.strip().lower()
        if key not in STAT_ALIASES:
            raise ValueError(f"Unknown stat: `{key}`")
        stat = STAT_ALIASES[key]
        if stat not in allowed:
            raise ValueError(f"`{key}` doesn't belong in this field")
        result[stat] = int(val)
    return result


def build_embed(race: str, before: dict, after: dict, spare: int, points_left_before: int) -> discord.Embed:
    embed = discord.Embed(title="🏛️ Shrine of Order", color=0x9B59B6)

    racial_bonuses = RACIAL_STATS.get(race, {})
    racial_str = ", ".join(f"+{v} {k}" for k, v in racial_bonuses.items()) if racial_bonuses else "None"
    embed.add_field(name="Race", value=f"{race.capitalize()} ({racial_str})", inline=False)
    embed.add_field(name="Points Left Before", value=str(points_left_before), inline=True)
    embed.add_field(name="Points Left After", value=str(spare), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    base_lines, attunement_lines, weapon_lines = [], [], []

    for stat in ALL_STATS:
        b = before.get(stat, 0)
        a = after.get(stat, 0)
        if b == 0 and a == 0:
            continue
        change = a - b
        arrow = "🟢" if change > 0 else ("🔴" if change < 0 else "⚪")
        sign = "+" if change >= 0 else ""
        row = f"{arrow} **{stat}**: {b} → **{a}** ({sign}{change})"
        if stat in ATTUNEMENTS:
            attunement_lines.append(row)
        elif "Weapon" in stat:
            weapon_lines.append(row)
        else:
            base_lines.append(row)

    if base_lines:
        embed.add_field(name="Base Stats", value="\n".join(base_lines), inline=False)
    if attunement_lines:
        embed.add_field(name="Attunements", value="\n".join(attunement_lines), inline=False)
    if weapon_lines:
        embed.add_field(name="Weapons", value="\n".join(weapon_lines), inline=False)

    embed.set_footer(text="Attunements are exempt from the -25 reduction cap")
    return embed


# ---------------------------------------------------------------------------
# Modal
# ---------------------------------------------------------------------------

class ShrineModal(ui.Modal, title="Shrine of Order"):
    race_input = ui.TextInput(
        label="Race",
        placeholder="e.g. khan, etrean, capra, none",
        required=True,
        max_length=20,
    )
    base_stats = ui.TextInput(
        label="Base Stats (str fort agi int will cha)",
        placeholder="e.g. 40 50 25 0 40 55  OR  str=40 fort=50 ...",
        required=True,
        max_length=100,
    )
    attunements = ui.TextInput(
        label="Attunements (optional)",
        placeholder="e.g. flame=80 frost=40",
        required=False,
        max_length=100,
    )
    weapon = ui.TextInput(
        label="Weapon (optional)",
        placeholder="e.g. med=85  or  light=60",
        required=False,
        max_length=30,
    )
    points_left = ui.TextInput(
        label="Unspent points before shrine (optional)",
        placeholder="e.g. 19  (default: 0)",
        required=False,
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction):
        race = self.race_input.value.strip().lower()
        if race not in RACIAL_STATS:
            await interaction.response.send_message(
                f"❌ Unknown race: `{race}`\nValid races: {VALID_RACES}", ephemeral=True
            )
            return

        try:
            build = {stat: 0 for stat in ALL_STATS}

            # Parse base stats
            base = parse_base_stats(self.base_stats.value)
            build.update(base)

            # Parse attunements
            if self.attunements.value.strip():
                atts = parse_kv_stats(self.attunements.value, list(ATTUNEMENTS))
                build.update(atts)

            # Parse weapon
            if self.weapon.value.strip():
                weapons = parse_kv_stats(self.weapon.value, ["LightWeapon", "MediumWeapon", "HeavyWeapon"])
                build.update(weapons)

            # Parse points left
            points_left = 0
            if self.points_left.value.strip():
                points_left = int(self.points_left.value.strip())

        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        invested = count_points_spent({k: v for k, v in build.items() if v > 0})
        points_left_before = TOTAL_POINTS - invested + points_left

        if points_left_before < 0:
            await interaction.response.send_message(
                f"❌ Your stats total **{invested}** points, which exceeds the 330 point budget.",
                ephemeral=True,
            )
            return

        before = build.copy()

        try:
            after, spare = shrine_of_order(build, race)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        embed = build_embed(race, before, after, spare + points_left_before, points_left_before)
        await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


@tree.command(name="shrine", description="Simulate Shrine of Order on your Deepwoken build")
async def shrine_command(interaction: discord.Interaction):
    await interaction.response.send_modal(ShrineModal())


@tree.command(name="races", description="List all races and their stat bonuses")
async def races_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🧬 Deepwoken Races", color=0x2ECC71)
    for race, bonuses in RACIAL_STATS.items():
        bonus_str = ", ".join(f"+{v} {k}" for k, v in bonuses.items()) if bonuses else "No bonuses"
        embed.add_field(name=race.capitalize(), value=bonus_str, inline=True)
    await interaction.response.send_message(embed=embed)


@tree.command(name="help", description="How to use the Deepwoken shrine bot")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Shrine Bot Help", color=0x3498DB)
    embed.add_field(
        name="/shrine",
        value=(
            "Opens a form where you fill in your build.\n\n"
            "**Base stats** — 6 numbers in order: `str fort agi int will cha`\n"
            "e.g. `40 50 25 0 40 55`\n\n"
            "Or use named format: `str=40 fort=50 agi=25 int=0 will=40 cha=55`\n\n"
            "**Attunements** — `flame=80 frost=40` *(optional)*\n"
            "**Weapon** — `med=85` *(optional)*\n"
            "**Points left** — unspent points before shrine *(optional)*"
        ),
        inline=False,
    )
    embed.add_field(
        name="Stat shortcuts",
        value=(
            "`str` `fort` `agi` `int` `will` `cha`\n"
            "`flame` `frost` `thunder` `gale` `shadow` `iron` `blood`\n"
            "`light` `med` `heavy`"
        ),
        inline=False,
    )
    embed.add_field(name="/races", value="List all races and their bonuses.", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user} — slash commands synced.")


keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
