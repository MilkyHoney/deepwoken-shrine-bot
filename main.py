"""
Deepwoken Discord bot.
"""

import asyncio
import os
import re

import discord
from discord import app_commands
from rapidfuzz import process as fuzz

import talents
import mantras
import weapons
from keep_alive import keep_alive
from shrine import (
    shrine_of_order, count_points_spent, TOTAL_POINTS, RACIAL_STATS,
    ALL_STATS, ATTUNEMENTS, get_racial_bonus, MAX_STAT_INVESTMENT,
)

# ---------------------------------------------------------------------------
# Constants
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
    "light": "LightWeapon", "lightweapon": "LightWeapon",
    "med": "MediumWeapon", "mediumweapon": "MediumWeapon",
    "heavy": "HeavyWeapon", "heavyweapon": "HeavyWeapon",
}

BASE_STATS = ["Strength", "Fortitude", "Agility", "Intelligence", "Willpower", "Charisma"]
WEAPON_STATS = ["LightWeapon", "MediumWeapon", "HeavyWeapon"]
VALID_RACES = ", ".join(f"`{r}`" for r in RACIAL_STATS)
RACE_FUZZY_CUTOFF = 55

CONTROL_WORDS = {
    "cancel": "cancel", "stop": "cancel", "quit": "cancel", "exit": "cancel",
    "restart": "restart", "reset": "restart",
    "back": "back",
}

# Tracks users currently inside a /shrine flow
_active_shrine_users = set()


# ---------------------------------------------------------------------------
# Discord client
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def match_race(text):
    text = (text or "").lower().strip()
    if text in RACIAL_STATS:
        return text
    m = fuzz.extractOne(text, RACIAL_STATS.keys(), score_cutoff=RACE_FUZZY_CUTOFF)
    return m[0] if m else None


def _safe_int(val, label="value"):
    try:
        return int(val)
    except ValueError:
        raise ValueError(f"`{val}` is not a valid number for {label}")


def parse_base_stats(s, require_all=False):
    """Parse '40 50 25 0 40 55' or 'str=40 fort=50 ...'"""
    s = re.sub(r"\s*=\s*", "=", s.strip())
    if "=" in s:
        result = _parse_kv(s, allowed=BASE_STATS)
        if require_all:
            missing = [stat for stat in BASE_STATS if stat not in result]
            if missing:
                raise ValueError(
                    f"Missing base stats: {', '.join(missing)}\n"
                    "Either include all 6 (e.g. `str=40 fort=50 agi=25 int=0 will=40 cha=55`) "
                    "or use the space-delimited form: `40 50 25 0 40 55`"
                )
        return result

    values = s.split()
    if len(values) != 6:
        raise ValueError(
            "Need exactly 6 numbers in order: `str fort agi int will cha`\n"
            "Example: `40 50 25 0 40 55`"
        )
    result = {}
    for stat, val in zip(BASE_STATS, values):
        v = _safe_int(val, stat)
        if v < 0:
            raise ValueError(f"`{stat}` cannot be negative")
        result[stat] = v
    return result


def parse_kv_stats(s, allowed):
    return _parse_kv(re.sub(r"\s*=\s*", "=", s.strip()), allowed=allowed)


def _parse_kv(s, allowed):
    """Shared parser for `stat=value stat=value` strings."""
    result = {}
    if not s:
        return result
    for pair in s.split():
        if "=" not in pair:
            raise ValueError(f"Invalid format: `{pair}` — use `stat=value`")
        key, val = pair.split("=", 1)
        key = key.strip().lower()
        if not key:
            raise ValueError(f"Invalid format: `{pair}`")
        if key not in STAT_ALIASES:
            raise ValueError(f"Unknown stat: `{key}`")
        stat = STAT_ALIASES[key]
        if stat not in allowed:
            raise ValueError(f"`{key}` doesn't belong here")
        if stat in result:
            raise ValueError(f"Duplicate stat: `{stat}` set twice")
        v = _safe_int(val, stat)
        if v < 0:
            raise ValueError(f"`{stat}` cannot be negative")
        result[stat] = v
    return result


def check_caps(build, race, hint=""):
    """Validate per-stat caps and racial floor. Returns error message or None."""
    for stat, value in build.items():
        if value <= 0:
            continue
        racial = get_racial_bonus(race, stat)
        if racial > 0 and value < racial:
            return (f"❌ **{stat}** can't be below the racial bonus of +{racial}. "
                    f"You entered {value}.\n{hint}")
        if value - racial > MAX_STAT_INVESTMENT:
            invested = value - racial
            tail = f" (you entered {value}, racial bonus is +{racial})" if racial else f" (you entered {value})"
            return f"❌ **{stat}** has {invested} points invested, exceeding the 100 point cap{tail}\n{hint}"
    return None


def points_spent(build, race):
    """Return (invested, total_with_racials)."""
    nonzero = {k: v for k, v in build.items() if v > 0}
    spent = count_points_spent(nonzero)
    racial_total = sum(get_racial_bonus(race, s) for s in nonzero)
    return spent - racial_total, spent


# ---------------------------------------------------------------------------
# Embeds
# ---------------------------------------------------------------------------

def races_embed():
    e = discord.Embed(title="What's your race?", color=0x9B59B6)
    lines = []
    for race, bonuses in RACIAL_STATS.items():
        bs = ", ".join(f"+{v} {k}" for k, v in bonuses.items()) if bonuses else "No bonuses"
        lines.append(f"**{race.capitalize()}** — {bs}")
    e.description = "\n".join(lines) + "\n\n_Type `cancel`, `restart`, or `back` at any time._"
    return e


def race_confirmed_msg(race):
    bonuses = RACIAL_STATS[race]
    bs = ", ".join(f"+{v} {k}" for k, v in bonuses.items()) if bonuses else "No bonuses"
    return (f"**{race.capitalize()}** ({bs})\n\n"
            f"Now enter your **base stats** in order:\n"
            f"`str  fort  agi  int  will  cha`\n"
            f"Example: `40 50 25 0 40 55`")


def build_summary_embed(race, build):
    invested, _ = points_spent(build, race)
    bonuses = RACIAL_STATS.get(race, {})
    bs = ", ".join(f"+{v} {k}" for k, v in bonuses.items()) if bonuses else "None"

    e = discord.Embed(title="📋 Build summary — confirm to run shrine", color=0xF1C40F)
    e.add_field(name="Race", value=f"{race.capitalize()} ({bs})", inline=False)
    e.add_field(name="Points spent", value=f"**{invested} / {TOTAL_POINTS}**", inline=True)

    groups = {"Base": [], "Attunements": [], "Weapons": []}
    for stat in ALL_STATS:
        v = build.get(stat, 0)
        if v == 0:
            continue
        if stat in ATTUNEMENTS:
            groups["Attunements"].append(f"{stat}: **{v}**")
        elif "Weapon" in stat:
            groups["Weapons"].append(f"{stat}: **{v}**")
        else:
            groups["Base"].append(f"{stat}: **{v}**")
    for name, lines in groups.items():
        if lines:
            e.add_field(name=name, value="\n".join(lines), inline=True)
    return e


def build_shrine_embed(race, before, after, points_after, points_before):
    e = discord.Embed(title="🏛️ Shrine of Order", color=0x9B59B6)
    bonuses = RACIAL_STATS.get(race, {})
    bs = ", ".join(f"+{v} {k}" for k, v in bonuses.items()) if bonuses else "None"
    e.add_field(name="Race", value=f"{race.capitalize()} ({bs})", inline=False)
    e.add_field(name="Points before shrine", value=str(points_before), inline=True)
    e.add_field(name="Points after shrine", value=str(points_after), inline=True)
    e.add_field(name="\u200b", value="\u200b", inline=True)

    groups = {"Base Stats": [], "Attunements": [], "Weapons": []}
    for stat in ALL_STATS:
        b, a = before.get(stat, 0), after.get(stat, 0)
        if b == 0 and a == 0:
            continue
        change = a - b
        arrow = "▲" if change > 0 else ("▼" if change < 0 else "—")
        sign = "+" if change > 0 else ""
        row = f"{arrow} {stat}: {b} → **{a}** ({sign}{change})"
        if stat in ATTUNEMENTS:
            groups["Attunements"].append(row)
        elif "Weapon" in stat:
            groups["Weapons"].append(row)
        else:
            groups["Base Stats"].append(row)
    for name, lines in groups.items():
        if lines:
            e.add_field(name=name, value="\n".join(lines), inline=False)
    e.set_footer(text="Attunements are exempt from the −25 reduction cap")
    return e


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class StepView(discord.ui.View):
    """Skip / Back / Cancel buttons. Returns action via self.action."""

    def __init__(self, *, allow_skip=False, allow_back=False):
        super().__init__(timeout=180)
        self.action = None
        self._used = False
        if allow_skip:
            self._add_button("Skip", discord.ButtonStyle.secondary, "skip")
        if allow_back:
            self._add_button("◀ Back", discord.ButtonStyle.secondary, "back")
        self._add_button("Cancel", discord.ButtonStyle.danger, "cancel")

    def _add_button(self, label, style, action):
        btn = discord.ui.Button(label=label, style=style)

        async def cb(interaction):
            if self._used:
                try:
                    await interaction.response.defer()
                except discord.InteractionResponded:
                    pass
                return
            self._used = True
            self.action = action
            for c in self.children:
                c.disabled = True
            try:
                await interaction.response.edit_message(view=self)
            except Exception:
                try:
                    await interaction.response.defer()
                except Exception:
                    pass
            self.stop()

        btn.callback = cb
        self.add_item(btn)


class ConfirmView(StepView):
    def __init__(self):
        super().__init__()
        # Replace default cancel with confirm/restart/cancel
        self.clear_items()
        self.action = None
        self._used = False
        self._add_button("✅ Run Shrine", discord.ButtonStyle.success, "confirm")
        self._add_button("🔄 Restart", discord.ButtonStyle.primary, "restart")
        self._add_button("✖ Cancel", discord.ButtonStyle.danger, "cancel")


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

async def safe_send(channel, *args, **kwargs):
    try:
        return await channel.send(*args, **kwargs)
    except discord.Forbidden:
        print(f"[SafeSend] Forbidden in channel {getattr(channel, 'id', '?')}")
    except discord.HTTPException as e:
        print(f"[SafeSend] HTTPException: {e}")
    return None


async def wait_for_input(channel, user, view=None, timeout=180):
    """
    Wait for either a text message or a button click.
    Returns one of: ('text', content), ('skip'/'cancel'/'restart'/'back', None), ('timeout', None)
    """
    msg_task = asyncio.ensure_future(
        bot.wait_for("message",
                     check=lambda m: m.author == user and m.channel == channel,
                     timeout=timeout)
    )
    tasks = [msg_task]
    view_task = asyncio.ensure_future(view.wait()) if view else None
    if view_task:
        tasks.append(view_task)

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except Exception as e:
        print(f"[wait_for_input] {e}")
        for t in tasks:
            t.cancel()
        return ("timeout", None)

    for p in pending:
        p.cancel()

    if view and view_task in done and view.action is not None:
        return (view.action, None)

    if msg_task in done and not msg_task.cancelled():
        try:
            msg = msg_task.result()
        except (asyncio.TimeoutError, Exception):
            return ("timeout", None)
        content = msg.content.strip()
        low = content.lower()
        if low in CONTROL_WORDS:
            return (CONTROL_WORDS[low], None)
        return ("text", content)

    return ("timeout", None)


# ---------------------------------------------------------------------------
# Shrine state machine
#
# Each step function takes (channel, user, race, build) and returns
# (action, race, build) where action is one of:
#   "next"     — proceed to next step
#   "back"     — return to previous step
#   "restart"  — restart the whole flow
#   "cancel"   — abort
#   "timeout"  — timed out
#
# The runner drives the state machine using STEP_GRAPH for navigation.
# ---------------------------------------------------------------------------

class ShrineCancelled(Exception):
    pass


async def step_race(channel, user, race, build):
    """Race selection. Loops internally until valid race."""
    while True:
        view = StepView(allow_back=False)
        await safe_send(channel, "_(Type a race name, or use the buttons.)_", view=view)
        action, content = await wait_for_input(channel, user, view=view)

        if action == "timeout":
            return ("timeout", race, build)
        if action == "cancel":
            return ("cancel", race, build)
        if action == "back":
            await safe_send(channel, "_(You're on the first step — nothing to go back to.)_")
            continue
        if action == "restart":
            return ("restart", race, build)
        if action != "text":
            continue

        matched = match_race(content)
        if not matched:
            await safe_send(channel, f"❌ Unknown race: `{content}`. Try again:\nValid races: {VALID_RACES}")
            continue
        await safe_send(channel, race_confirmed_msg(matched))
        return ("next", matched, build)


async def step_base(channel, user, race, build):
    """Base stats. Allows mid-step race switch via single-word input."""
    while True:
        view = StepView(allow_back=True)
        await safe_send(channel,
                        "Enter your **base stats** in order: `str fort agi int will cha`",
                        view=view)
        action, content = await wait_for_input(channel, user, view=view)

        if action in ("timeout", "cancel", "restart", "back"):
            return (action, race, build)
        if action != "text":
            continue

        # Single-word non-digit = race switch
        if len(content.split()) == 1 and not content.lstrip("-").isdigit():
            switched = match_race(content)
            if switched:
                race = switched
                await safe_send(channel, race_confirmed_msg(race))
                continue

        try:
            new_build = {stat: 0 for stat in ALL_STATS}
            new_build.update(parse_base_stats(content, require_all=True))
        except ValueError as e:
            await safe_send(channel, f"❌ {e}\nTry again:")
            continue

        err = check_caps(new_build, race, hint="Try again: `str  fort  agi  int  will  cha`")
        if err:
            await safe_send(channel, err)
            continue

        invested, _ = points_spent(new_build, race)
        if invested > TOTAL_POINTS:
            await safe_send(channel,
                            f"❌ That's **{invested}** points invested, exceeding the {TOTAL_POINTS} budget. Try again:")
            continue

        await safe_send(channel,
                        f"Base stats set — **{invested}/{TOTAL_POINTS}** points spent, **{TOTAL_POINTS - invested}** left")
        return ("next", race, new_build)


def _make_kv_step(allowed_stats, prompt, hint, label):
    """Factory for attunement/weapon steps — they're identical except for the allowed set."""
    async def step(channel, user, race, build):
        while True:
            view = StepView(allow_skip=True, allow_back=True)
            await safe_send(channel, prompt, view=view)
            action, content = await wait_for_input(channel, user, view=view)

            if action in ("timeout", "cancel", "restart", "back"):
                return (action, race, build)
            if action == "skip":
                return ("next", race, build)
            if action != "text":
                continue

            new_build = dict(build)
            try:
                new_build.update(parse_kv_stats(content, allowed_stats))
            except ValueError as e:
                await safe_send(channel, f"❌ {e}\nTry again:")
                continue

            err = check_caps(new_build, race, hint=hint)
            if err:
                await safe_send(channel, err)
                continue

            invested, _ = points_spent(new_build, race)
            if invested > TOTAL_POINTS:
                await safe_send(channel,
                                f"❌ That's **{invested}** points invested, exceeding the {TOTAL_POINTS} budget. Try again:")
                continue

            await safe_send(channel,
                            f"{label} set — **{invested}/{TOTAL_POINTS}** points spent, **{TOTAL_POINTS - invested}** left")
            return ("next", race, new_build)

    return step


step_attunements = _make_kv_step(
    list(ATTUNEMENTS),
    "Any **attunements**? Enter all separated by spaces:\n`flame=80 thunder=35 frost=40`",
    "Try again: `flame=80 thunder=35 frost=40`",
    "Attunements",
)

step_weapon = _make_kv_step(
    WEAPON_STATS,
    "Any **weapon**? e.g. `med=85` or `light=60` or `heavy=70`",
    "Try again: `med=85` or `light=60` or `heavy=70`",
    "Weapon",
)


async def step_confirm(channel, user, race, build):
    while True:
        view = ConfirmView()
        await safe_send(channel, embed=build_summary_embed(race, build), view=view)
        action, _ = await wait_for_input(channel, user, view=view)
        if action in ("timeout", "cancel", "restart", "back", "confirm"):
            return ((action if action != "confirm" else "next"), race, build)


# Step graph: name -> (step_func, prev_step_name, next_step_name)
# `prev` is None for the first step; `next` is None for the last.
STEP_GRAPH = [
    ("race",        step_race,        None,           "base"),
    ("base",        step_base,        "race",         "attunements"),
    ("attunements", step_attunements, "base",         "weapon"),
    ("weapon",      step_weapon,      "attunements",  "confirm"),
    ("confirm",     step_confirm,     "weapon",       None),
]
STEPS = {name: (fn, prev, nxt) for name, fn, prev, nxt in STEP_GRAPH}


async def run_shrine_flow(channel, user):
    """Drive the shrine state machine. Snapshots taken on entry to each step
    so 'back' restores the previous state."""
    while True:  # restart loop
        race = None
        build = {stat: 0 for stat in ALL_STATS}
        # snapshots[step_name] = (race, build) at entry to that step
        snapshots = {}

        current = "race"
        while current is not None:
            snapshots[current] = (race, dict(build))
            step_fn, prev, nxt = STEPS[current]
            action, race, build = await step_fn(channel, user, race, build)

            if action == "timeout":
                await safe_send(channel, "❌ Timed out. Run `/shrine` again.")
                return
            if action == "cancel":
                await safe_send(channel, "✖ Cancelled.")
                return
            if action == "restart":
                break  # break inner, outer loop continues
            if action == "back":
                if prev is None:
                    await safe_send(channel, "_(You're on the first step — nothing to go back to.)_")
                    continue  # re-run current step
                # Restore snapshot of previous step
                race, build = snapshots[prev]
                current = prev
                continue
            if action == "next":
                current = nxt
                continue

        if current is None:
            break  # finished cleanly

    # Run the shrine
    invested, _ = points_spent(build, race)
    points_before = TOTAL_POINTS - invested
    before = dict(build)
    try:
        after, spare = shrine_of_order(build, race)
    except ValueError as e:
        await safe_send(channel, f"❌ {e}\nRun `/shrine` again.")
        return

    await safe_send(channel,
                    embed=build_shrine_embed(race, before, after,
                                             spare + points_before, points_before))


# ---------------------------------------------------------------------------
# /shrine command
# ---------------------------------------------------------------------------

@tree.command(name="shrine", description="Simulate Shrine of Order on your Deepwoken build")
@app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
async def shrine_cmd(interaction):
    user = interaction.user
    channel = interaction.channel

    if user.id in _active_shrine_users:
        try:
            await interaction.response.send_message(
                "❌ You already have an active `/shrine` session. Finish it or wait for it to time out.",
                ephemeral=True,
            )
        except Exception:
            pass
        return

    _active_shrine_users.add(user.id)
    try:
        await interaction.response.send_message(embed=races_embed())
        await run_shrine_flow(channel, user)
    except discord.Forbidden:
        print(f"[Shrine] Forbidden in channel {getattr(channel, 'id', '?')}")
    except discord.HTTPException as e:
        print(f"[Shrine] HTTPException: {e}")
        await safe_send(channel, "❌ Discord rejected a message. Run `/shrine` again.")
    except Exception as e:
        print(f"[Shrine] Unexpected error: {type(e).__name__}: {e}")
        await safe_send(channel, "❌ Something went wrong. Run `/shrine` again.")
    finally:
        _active_shrine_users.discard(user.id)


@shrine_cmd.error
async def shrine_err(interaction, error):
    if isinstance(error, app_commands.CommandOnCooldown):
        try:
            await interaction.response.send_message(
                f"⏳ Slow down — try again in {error.retry_after:.1f}s.",
                ephemeral=True,
            )
        except Exception:
            pass
    else:
        print(f"[Shrine] Command error: {error}")


# ---------------------------------------------------------------------------
# Module-owned commands
# ---------------------------------------------------------------------------

talents.register(tree)
mantras.register(tree)
weapons.register(tree)


# ---------------------------------------------------------------------------
# /races and /help
# ---------------------------------------------------------------------------

@tree.command(name="races", description="List all races and their stat bonuses")
async def races_cmd(interaction):
    e = discord.Embed(title="🧬 Deepwoken Races", color=0x2ECC71)
    lines = []
    for race, bonuses in RACIAL_STATS.items():
        bs = ", ".join(f"+{v} {k}" for k, v in bonuses.items()) if bonuses else "No bonuses"
        lines.append(f"**{race.capitalize()}** — {bs}")
    e.description = "\n".join(lines)
    await interaction.response.send_message(embed=e)


@tree.command(name="help", description="How to use the Deepwoken bot")
async def help_cmd(interaction):
    e = discord.Embed(title="📖 Deepwoken Bot — Help", color=0x3498DB)
    e.add_field(name="Commands", value=(
        "`/shrine` — Shrine of Order build simulator\n"
        "`/talents` — talent lookup (name or stat requirement)\n"
        "`/talent_random` — random talent\n"
        "`/required` — min stats needed for a list of talents\n"
        "`/mantras` — mantra lookup (name or attribute)\n"
        "`/mantra_random` — random mantra\n"
        "`/weapons` — weapon lookup (name or type)\n"
        "`/weapon_random` — random weapon\n"
        "`/races` — race list\n"
        "`/help` — this message"
    ), inline=False)
    e.add_field(name="During /shrine", value=(
        "Type `cancel`, `restart`, or `back` at any time, or use the buttons."
    ), inline=False)
    e.add_field(name="Stat shortcuts", value=(
        "`str` `fort` `agi` `int` `will` `cha` · "
        "`flame` `frost` `thunder` `gale` `shadow` `iron` `blood` · "
        "`light` `med` `heavy`"
    ), inline=False)
    e.set_footer(text="330 total investment points · attunements exempt from −25 cap")
    await interaction.response.send_message(embed=e)


# ---------------------------------------------------------------------------
# Background refresh
# ---------------------------------------------------------------------------

async def refresh_loop():
    """Reload all data files every 6 hours, surviving any module's errors."""
    await bot.wait_until_ready()
    modules = [("Talents", talents), ("Mantras", mantras), ("Weapons", weapons)]
    while not bot.is_closed():
        for tag, mod in modules:
            try:
                mod.refresh_cache()
            except Exception as e:
                print(f"[{tag}] Refresh failed: {e}")
        await asyncio.sleep(6 * 3600)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

_synced = False


@bot.event
async def on_ready():
    global _synced
    if not _synced:
        await tree.sync()
        _synced = True
        bot.loop.create_task(refresh_loop())
    print(f"✅ Logged in as {bot.user}")


TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("❌ DISCORD_TOKEN environment variable is not set. Add it in Replit Secrets.")

keep_alive()
bot.run(TOKEN)
