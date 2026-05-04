import discord
from discord import app_commands
import os
from rapidfuzz import process as fuzz

from shrine import shrine_of_order, count_points_spent, TOTAL_POINTS, RACIAL_STATS, ALL_STATS, ATTUNEMENTS, get_racial_bonus, MAX_STAT_INVESTMENT
from keep_alive import keep_alive

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
    "light": "LightWeapon", "lightweapon": "LightWeapon",
    "med": "MediumWeapon", "mediumweapon": "MediumWeapon",
    "heavy": "HeavyWeapon", "heavyweapon": "HeavyWeapon",
}

VALID_RACES = ", ".join(f"`{r}`" for r in RACIAL_STATS.keys())
FUZZY_CUTOFF = 55


def match_race(text):
    text = text.lower().strip()
    if text in RACIAL_STATS:
        return text
    m = fuzz.extractOne(text, RACIAL_STATS.keys(), score_cutoff=FUZZY_CUTOFF)
    return m[0] if m else None


def parse_base_stats(s):
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
                raise ValueError(f"`{key}` is not a base stat")
            v = int(val)
            if v < 0:
                raise ValueError(f"`{stat}` cannot be negative")
            result[stat] = v
    else:
        values = s.split()
        if len(values) != 6:
            raise ValueError("Need exactly 6 numbers in order: `str fort agi int will cha`\nExample: `40 50 25 0 40 55`")
        for stat, val in zip(base_order, values):
            v = int(val)
            if v < 0:
                raise ValueError(f"`{stat}` cannot be negative")
            result[stat] = v
    return result


def parse_kv_stats(s, allowed):
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
            raise ValueError(f"`{key}` doesn't belong here")
        v = int(val)
        if v < 0:
            raise ValueError(f"`{stat}` cannot be negative")
        result[stat] = v
    return result


def check_caps(build, race):
    for stat, value in build.items():
        if value <= 0:
            continue
        racial = get_racial_bonus(race, stat)
        if value - racial > MAX_STAT_INVESTMENT:
            invested = value - racial
            msg = f"❌ **{stat}** has {invested} points invested, exceeding the 100 point cap"
            msg += f" (you entered {value}, racial bonus is +{racial})" if racial else f" (you entered {value})"
            msg += "\nTry again: `str  fort  agi  int  will  cha`"
            return msg
    return None


def races_embed():
    embed = discord.Embed(title="What's your race?", color=0x9B59B6)
    lines = []
    for race, bonuses in RACIAL_STATS.items():
        bonus_str = ", ".join(f"+{v} {k}" for k, v in bonuses.items()) if bonuses else "No bonuses"
        lines.append(f"**{race.capitalize()}** — {bonus_str}")
    embed.description = "\n".join(lines)
    return embed


def race_confirmed_msg(race):
    racial_bonuses = RACIAL_STATS[race]
    racial_str = ", ".join(f"+{v} {k}" for k, v in racial_bonuses.items()) if racial_bonuses else "No bonuses"
    return (
        f"**{race.capitalize()}** ({racial_str})\n\n"
        f"Now enter your **base stats** in order:\n"
        f"`str  fort  agi  int  will  cha`\n"
        f"Example: `40 50 25 0 40 55`"
    )


def build_shrine_embed(race, before, after, spare, points_before):
    embed = discord.Embed(title="🏛️ Shrine of Order", color=0x9B59B6)
    racial_bonuses = RACIAL_STATS.get(race, {})
    racial_str = ", ".join(f"+{v} {k}" for k, v in racial_bonuses.items()) if racial_bonuses else "None"
    embed.add_field(name="Race", value=f"{race.capitalize()} ({racial_str})", inline=False)
    embed.add_field(name="Points before shrine", value=str(points_before), inline=True)
    embed.add_field(name="Points after shrine", value=str(spare), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    base_lines, attunement_lines, weapon_lines = [], [], []
    for stat in ALL_STATS:
        b = before.get(stat, 0)
        a = after.get(stat, 0)
        if b == 0 and a == 0:
            continue
        change = a - b
        arrow = "▲" if change > 0 else ("▼" if change < 0 else "—")
        sign = "+" if change > 0 else ""
        row = f"{arrow} {stat}: {b} → **{a}** ({sign}{change})"
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

    embed.set_footer(text="Attunements are exempt from the −25 reduction cap")
    return embed


class SkipView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.skipped = False

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.skipped = True
        self.stop()
        await interaction.response.defer()


intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


async def wait_for_message(channel, user, timeout=120):
    import asyncio
    def check(m):
        return m.author == user and m.channel == channel
    try:
        msg = await bot.wait_for("message", check=check, timeout=timeout)
        return msg.content.strip()
    except asyncio.TimeoutError:
        return None


@tree.command(name="shrine", description="Simulate Shrine of Order on your Deepwoken build")
async def shrine_command(interaction: discord.Interaction):
    import asyncio
    channel = interaction.channel
    user = interaction.user
    race = None

    await interaction.response.send_message(embed=races_embed())
    while True:
        race_input = await wait_for_message(channel, user)
        if not race_input:
            await channel.send("❌ Timed out. Run `/shrine` again.")
            return
        race = match_race(race_input)
        if not race:
            await channel.send(f"❌ Unknown race: `{race_input}`. Try again:\nValid races: {VALID_RACES}")
            continue
        await channel.send(race_confirmed_msg(race))
        break

    while True:
        base_input = await wait_for_message(channel, user)
        if not base_input:
            await channel.send("❌ Timed out. Run `/shrine` again.")
            return
        if len(base_input.split()) == 1 and not base_input.strip().lstrip('-').isdigit():
            switched = match_race(base_input)
            if switched:
                race = switched
                await channel.send(race_confirmed_msg(race))
                continue
        try:
            build = {stat: 0 for stat in ALL_STATS}
            build.update(parse_base_stats(base_input))
        except ValueError as e:
            await channel.send(f"❌ {e}\nTry again:")
            continue
        err = check_caps(build, race)
        if err:
            await channel.send(err)
            continue
        spent = count_points_spent({k: v for k, v in build.items() if v > 0})
        if spent > TOTAL_POINTS:
            await channel.send(f"❌ That's **{spent}** points, exceeding the {TOTAL_POINTS} budget. Try again:")
            continue
        await channel.send(f"Base stats set — **{spent}/{TOTAL_POINTS}** points spent, **{TOTAL_POINTS - spent}** left")
        break

    while True:
        skip_view = SkipView()
        await channel.send(
            "Any **attunements**? Enter all separated by spaces:\n`flame=80 thunder=35 frost=40`",
            view=skip_view
        )
        msg_task = asyncio.ensure_future(wait_for_message(channel, user))
        done, pending = await asyncio.wait(
            [msg_task, asyncio.ensure_future(skip_view.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )
        for p in pending:
            p.cancel()
        if skip_view.skipped:
            break
        att_input = msg_task.result() if msg_task in done and not msg_task.cancelled() else None
        if not att_input:
            await channel.send("❌ Timed out. Run `/shrine` again.")
            return
        try:
            build.update(parse_kv_stats(att_input, list(ATTUNEMENTS)))
        except ValueError as e:
            await channel.send(f"❌ {e}\nTry again:")
            continue
        err = check_caps(build, race)
        if err:
            await channel.send(err)
            continue
        spent = count_points_spent({k: v for k, v in build.items() if v > 0})
        if spent > TOTAL_POINTS:
            await channel.send(f"❌ That's **{spent}** points, exceeding the {TOTAL_POINTS} budget. Try again:")
            continue
        await channel.send(f"Attunements set — **{spent}/{TOTAL_POINTS}** points spent, **{TOTAL_POINTS - spent}** left")
        break

    while True:
        skip_view2 = SkipView()
        await channel.send(
            "Any **weapon**? e.g. `med=85` or `light=60` or `heavy=70`",
            view=skip_view2
        )
        msg_task = asyncio.ensure_future(wait_for_message(channel, user))
        done, pending = await asyncio.wait(
            [msg_task, asyncio.ensure_future(skip_view2.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )
        for p in pending:
            p.cancel()
        if skip_view2.skipped:
            break
        wep_input = msg_task.result() if msg_task in done and not msg_task.cancelled() else None
        if not wep_input:
            await channel.send("❌ Timed out. Run `/shrine` again.")
            return
        try:
            build.update(parse_kv_stats(wep_input, ["LightWeapon", "MediumWeapon", "HeavyWeapon"]))
        except ValueError as e:
            await channel.send(f"❌ {e}\nTry again:")
            continue
        err = check_caps(build, race)
        if err:
            await channel.send(err)
            continue
        spent = count_points_spent({k: v for k, v in build.items() if v > 0})
        if spent > TOTAL_POINTS:
            await channel.send(f"❌ That's **{spent}** points, exceeding the {TOTAL_POINTS} budget. Try again:")
            continue
        await channel.send(f"Weapon set — **{spent}/{TOTAL_POINTS}** points spent, **{TOTAL_POINTS - spent}** left")
        break

    invested = count_points_spent({k: v for k, v in build.items() if v > 0})
    points_before = TOTAL_POINTS - invested
    before = build.copy()
    try:
        after, spare = shrine_of_order(build, race)
    except ValueError as e:
        await channel.send(f"❌ {e}\nRun `/shrine` again.")
        return

    await channel.send(embed=build_shrine_embed(race, before, after, spare + points_before, points_before))


@tree.command(name="races", description="List all races and their stat bonuses")
async def races_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🧬 Deepwoken Races", color=0x2ECC71)
    for race, bonuses in RACIAL_STATS.items():
        bonus_str = ", ".join(f"+{v} {k}" for k, v in bonuses.items()) if bonuses else "No bonuses"
        embed.add_field(name=race.capitalize(), value=bonus_str, inline=True)
    await interaction.response.send_message(embed=embed)


@tree.command(name="help", description="How to use the Deepwoken shrine bot")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Shrine Bot — Help", color=0x3498DB)
    embed.add_field(name="Commands", value="`/shrine` — start the shrine flow\n`/races` — list all races & bonuses\n`/help` — this message", inline=False)
    embed.add_field(name="How it works", value="1. Pick your race\n2. Enter base stats: `str fort agi int will cha`\n3. Enter attunements (or skip): `flame=80 thunder=35`\n4. Enter weapon (or skip): `med=85`", inline=False)
    embed.add_field(name="Stat shortcuts", value="`str` `fort` `agi` `int` `will` `cha`\n`flame` `frost` `thunder` `gale` `shadow` `iron` `blood`\n`light` `med` `heavy`", inline=False)
    embed.set_footer(text="330 total investment points · attunements exempt from −25 cap")
    await interaction.response.send_message(embed=embed)


@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user} — slash commands synced.")


keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
