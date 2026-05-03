import discord
from discord.ext import commands
import os

from shrine import shrine_of_order, count_points_spent, TOTAL_POINTS, RACIAL_STATS, ALL_STATS, ATTUNEMENTS
from keep_alive import keep_alive

# ---------------------------------------------------------------------------
# Stat aliases — lets users type short names like "str", "fort", "flame" etc.
# ---------------------------------------------------------------------------
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
# Helpers
# ---------------------------------------------------------------------------

def parse_args(args: tuple) -> tuple[str, dict, int]:
    """
    Parses command arguments into (race, stats_dict, points_left).
    Expected format: <race> stat=value stat=value ... [points_left=N]
    Example: khan str=40 fort=50 agi=25 will=40 cha=55 light=1 flame=100 points_left=19
    """
    if not args:
        raise ValueError("No arguments provided. Use `?help` to see usage.")

    race = args[0].strip().lower()
    if race not in RACIAL_STATS:
        raise ValueError(f"Unknown race: `{race}`\nValid races: {VALID_RACES}")

    result = {stat: 0 for stat in ALL_STATS}
    points_left = 0

    for pair in args[1:]:
        if "=" not in pair:
            raise ValueError(f"Invalid format: `{pair}` — use `stat=value` (e.g. `str=40`)")
        key, val = pair.split("=", 1)
        key = key.strip().lower()

        # Handle points_left as a special keyword
        if key in ("points_left", "left", "pl"):
            try:
                points_left = int(val)
            except ValueError:
                raise ValueError(f"Invalid value for `points_left`: `{val}`")
            continue

        if key not in STAT_ALIASES:
            raise ValueError(f"Unknown stat: `{key}`\nUse `?help` to see valid stat names.")
        try:
            result[STAT_ALIASES[key]] = int(val)
        except ValueError:
            raise ValueError(f"Invalid value for `{key}`: `{val}` — must be a whole number")

    return race, result, points_left


def build_embed(race: str, before: dict, after: dict, spare: int, points_left_before: int) -> discord.Embed:
    embed = discord.Embed(title="🏛️ Shrine of Order", color=0x9B59B6)

    racial_bonuses = RACIAL_STATS.get(race, {})
    racial_str = ", ".join(f"+{v} {k}" for k, v in racial_bonuses.items()) if racial_bonuses else "None"
    embed.add_field(name="Race", value=f"{race.capitalize()} ({racial_str})", inline=False)
    embed.add_field(name="Points Left Before", value=str(points_left_before), inline=True)
    embed.add_field(name="Points Left After", value=str(spare), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

    base_lines = []
    attunement_lines = []
    weapon_lines = []

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
# Bot setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="?", intents=intents, help_command=None)


@bot.command(name="shrine")
async def shrine_command(ctx, *args):
    """Simulate Shrine of Order on your Deepwoken build."""
    try:
        race, parsed, points_left = parse_args(args)
    except ValueError as e:
        await ctx.send(f"❌ {e}")
        return

    invested = count_points_spent({k: v for k, v in parsed.items() if v > 0})
    points_left_before = TOTAL_POINTS - invested + points_left

    if points_left_before < 0:
        await ctx.send(f"❌ Your stats total **{invested}** points, which exceeds the 330 point budget.")
        return

    before = parsed.copy()

    try:
        after, spare = shrine_of_order(parsed, race)
    except Exception as e:
        await ctx.send(f"❌ Error running shrine: {e}")
        return

    embed = build_embed(race, before, after, spare + points_left_before, points_left_before)
    await ctx.send(embed=embed)


@bot.command(name="races")
async def races_command(ctx):
    """List all available races and their stat bonuses."""
    embed = discord.Embed(title="🧬 Deepwoken Races", color=0x2ECC71)
    for race, bonuses in RACIAL_STATS.items():
        bonus_str = ", ".join(f"+{v} {k}" for k, v in bonuses.items()) if bonuses else "No bonuses"
        embed.add_field(name=race.capitalize(), value=bonus_str, inline=True)
    await ctx.send(embed=embed)


@bot.command(name="help")
async def help_command(ctx):
    """Show usage instructions."""
    embed = discord.Embed(title="📖 Shrine Bot Help", color=0x3498DB)
    embed.add_field(
        name="?shrine <race> <stats> [points_left=N]",
        value=(
            "Simulate Shrine of Order on your build.\n\n"
            "**Example:**\n"
            "`?shrine khan str=40 fort=50 agi=25 will=40 cha=55 light=1 flame=100 points_left=19`"
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
    embed.add_field(name="?races", value="List all races and their bonuses.", inline=False)
    await ctx.send(embed=embed)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
