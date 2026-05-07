import discord
from discord import app_commands
import os
import re
import asyncio
from rapidfuzz import process as fuzz

from shrine import (
    shrine_of_order, count_points_spent, TOTAL_POINTS, RACIAL_STATS,
    ALL_STATS, ATTUNEMENTS, get_racial_bonus, MAX_STAT_INVESTMENT,
)
import talents as talent_cache
from keep_alive import keep_alive

# ---------------------------------------------------------------------------
# Stat aliases — for /shrine input parsing.
# These map to shrine.py's no-space form (e.g. "LightWeapon"), which is
# different from talents.py (which uses "Light Weapon" to match the JSON).
# This is intentional — the two contexts are isolated.
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

VALID_RACES = ", ".join(f"`{r}`" for r in RACIAL_STATS.keys())
FUZZY_CUTOFF = 55

CONTROL_HINT = "_Type `cancel`, `restart`, or `back` at any time._"

# Tracks users currently inside a /shrine flow so they can't double-run it
_active_shrine_users = set()


def match_race(text):
    text = text.lower().strip()
    if text in RACIAL_STATS:
        return text
    m = fuzz.extractOne(text, RACIAL_STATS.keys(), score_cutoff=FUZZY_CUTOFF)
    return m[0] if m else None


def _safe_int(val: str, label: str = "value"):
    try:
        return int(val)
    except ValueError:
        raise ValueError(f"`{val}` is not a valid number for {label}")


def parse_base_stats(s, require_all=False):
    """
    Parse '40 50 25 0 40 55' or 'str=40 fort=50 ...'
    If require_all is True (kv mode), all 6 base stats must be present.
    """
    result = {}
    base_order = ["Strength", "Fortitude", "Agility", "Intelligence", "Willpower", "Charisma"]
    s = re.sub(r"\s*=\s*", "=", s.strip())
    if "=" in s:
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
            if stat not in base_order:
                raise ValueError(f"`{key}` is not a base stat")
            if stat in result:
                raise ValueError(f"Duplicate stat: `{stat}` set twice")
            v = _safe_int(val, stat)
            if v < 0:
                raise ValueError(f"`{stat}` cannot be negative")
            result[stat] = v
        if require_all:
            missing = [s for s in base_order if s not in result]
            if missing:
                raise ValueError(
                    "Missing base stats: " + ", ".join(missing) +
                    "\nEither include all 6 (e.g. `str=40 fort=50 agi=25 int=0 will=40 cha=55`) "
                    "or use the space-delimited form: `40 50 25 0 40 55`"
                )
    else:
        values = s.split()
        if len(values) != 6:
            raise ValueError("Need exactly 6 numbers in order: `str fort agi int will cha`\nExample: `40 50 25 0 40 55`")
        for stat, val in zip(base_order, values):
            v = _safe_int(val, stat)
            if v < 0:
                raise ValueError(f"`{stat}` cannot be negative")
            result[stat] = v
    return result


def parse_kv_stats(s, allowed):
    result = {}
    s = re.sub(r"\s*=\s*", "=", s.strip())
    if not s:
        return result
    for pair in s.split():
        if "=" not in pair:
            raise ValueError(f"Invalid format: `{pair}` — use `stat=value` (e.g. `flame=80`)")
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


def check_caps(build, race, step="base"):
    retry_hints = {
        "base": "Try again: `str  fort  agi  int  will  cha`",
        "attunement": "Try again: `flame=80 thunder=35 frost=40`",
        "weapon": "Try again: `med=85` or `light=60` or `heavy=70`",
    }
    for stat, value in build.items():
        if value <= 0:
            continue
        racial = get_racial_bonus(race, stat)
        if racial > 0 and value < racial:
            return (
                f"❌ **{stat}** can't be below the racial bonus of +{racial}. "
                f"You entered {value}.\n{retry_hints.get(step, '')}"
            )
        if value - racial > MAX_STAT_INVESTMENT:
            invested = value - racial
            msg = f"❌ **{stat}** has {invested} points invested, exceeding the 100 point cap"
            msg += f" (you entered {value}, racial bonus is +{racial})" if racial else f" (you entered {value})"
            msg += f"\n{retry_hints.get(step, '')}"
            return msg
    return None


def races_embed():
    embed = discord.Embed(title="What's your race?", color=0x9B59B6)
    lines = []
    for race, bonuses in RACIAL_STATS.items():
        bonus_str = ", ".join(f"+{v} {k}" for k, v in bonuses.items()) if bonuses else "No bonuses"
        lines.append(f"**{race.capitalize()}** — {bonus_str}")
    embed.description = "\n".join(lines) + f"\n\n{CONTROL_HINT}"
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


def build_summary_embed(race, build):
    """A summary embed showing the build before running shrine — for the confirmation step."""
    invested = count_points_spent({k: v for k, v in build.items() if v > 0})
    racial_total = sum(get_racial_bonus(race, s) for s, v in build.items() if v > 0)
    spent = invested - racial_total

    racial_bonuses = RACIAL_STATS.get(race, {})
    racial_str = ", ".join(f"+{v} {k}" for k, v in racial_bonuses.items()) if racial_bonuses else "None"

    embed = discord.Embed(title="📋 Build summary — confirm to run shrine", color=0xF1C40F)
    embed.add_field(name="Race", value=f"{race.capitalize()} ({racial_str})", inline=False)
    embed.add_field(name="Points spent", value=f"**{spent} / {TOTAL_POINTS}**", inline=True)

    base_lines, attune_lines, weapon_lines = [], [], []
    for stat in ALL_STATS:
        v = build.get(stat, 0)
        if v == 0:
            continue
        if stat in ATTUNEMENTS:
            attune_lines.append(f"{stat}: **{v}**")
        elif "Weapon" in stat:
            weapon_lines.append(f"{stat}: **{v}**")
        else:
            base_lines.append(f"{stat}: **{v}**")
    if base_lines:
        embed.add_field(name="Base", value="\n".join(base_lines), inline=True)
    if attune_lines:
        embed.add_field(name="Attunements", value="\n".join(attune_lines), inline=True)
    if weapon_lines:
        embed.add_field(name="Weapons", value="\n".join(weapon_lines), inline=True)
    return embed


def build_shrine_embed(race, before, after, points_after, points_before):
    embed = discord.Embed(title="🏛️ Shrine of Order", color=0x9B59B6)
    racial_bonuses = RACIAL_STATS.get(race, {})
    racial_str = ", ".join(f"+{v} {k}" for k, v in racial_bonuses.items()) if racial_bonuses else "None"
    embed.add_field(name="Race", value=f"{race.capitalize()} ({racial_str})", inline=False)
    embed.add_field(name="Points before shrine", value=str(points_before), inline=True)
    embed.add_field(name="Points after shrine", value=str(points_after), inline=True)
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


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class StepView(discord.ui.View):
    """Skip + Cancel + Back buttons for in-flow steps."""
    def __init__(self, allow_skip=False, allow_back=False):
        super().__init__(timeout=180)
        self.action = None  # 'skip' | 'cancel' | 'back'
        self._used = False

        if allow_skip:
            btn = discord.ui.Button(label="Skip", style=discord.ButtonStyle.secondary)
            btn.callback = self._make_handler(btn, "skip")
            self.add_item(btn)

        if allow_back:
            btn = discord.ui.Button(label="◀ Back", style=discord.ButtonStyle.secondary)
            btn.callback = self._make_handler(btn, "back")
            self.add_item(btn)

        cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel_btn.callback = self._make_handler(cancel_btn, "cancel")
        self.add_item(cancel_btn)

    def _make_handler(self, button, action):
        async def handler(interaction: discord.Interaction):
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
        return handler


class ConfirmView(discord.ui.View):
    """Confirm / Restart / Cancel for the final summary step."""
    def __init__(self):
        super().__init__(timeout=180)
        self.action = None
        self._used = False

        confirm = discord.ui.Button(label="✅ Run Shrine", style=discord.ButtonStyle.success)
        confirm.callback = self._make_handler(confirm, "confirm")
        self.add_item(confirm)

        restart = discord.ui.Button(label="🔄 Restart", style=discord.ButtonStyle.primary)
        restart.callback = self._make_handler(restart, "restart")
        self.add_item(restart)

        cancel = discord.ui.Button(label="✖ Cancel", style=discord.ButtonStyle.danger)
        cancel.callback = self._make_handler(cancel, "cancel")
        self.add_item(cancel)

    def _make_handler(self, button, action):
        async def handler(interaction: discord.Interaction):
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
        return handler


# ---------------------------------------------------------------------------
# Discord setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


async def safe_send(channel, *args, **kwargs):
    try:
        return await channel.send(*args, **kwargs)
    except discord.Forbidden:
        print(f"[SafeSend] Forbidden in channel {getattr(channel, 'id', '?')}")
        return None
    except discord.HTTPException as e:
        print(f"[SafeSend] HTTPException: {e}")
        return None


CONTROL_WORDS = {
    "cancel": "cancel", "stop": "cancel", "quit": "cancel", "exit": "cancel",
    "restart": "restart", "reset": "restart",
    "back": "back",
}


async def wait_for_input(channel, user, view=None, timeout=180):
    """
    Wait for either a text message from the user OR a button click on `view`.
    Returns one of:
        ('text',     content)
        ('skip',     None)
        ('cancel',   None)
        ('restart',  None)
        ('back',     None)
        ('timeout',  None)
    """
    def check(m):
        return m.author == user and m.channel == channel

    msg_task = asyncio.ensure_future(bot.wait_for("message", check=check, timeout=timeout))
    tasks = [msg_task]
    view_task = None
    if view is not None:
        view_task = asyncio.ensure_future(view.wait())
        tasks.append(view_task)

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except Exception as e:
        print(f"[wait_for_input] error: {e}")
        for t in tasks:
            t.cancel()
        return ("timeout", None)

    for p in pending:
        p.cancel()

    if view_task in done and view is not None and view.action is not None:
        return (view.action, None)

    if msg_task in done and not msg_task.cancelled():
        try:
            msg = msg_task.result()
        except asyncio.TimeoutError:
            return ("timeout", None)
        except Exception:
            return ("timeout", None)
        content = msg.content.strip()
        low = content.lower()
        if low in CONTROL_WORDS:
            return (CONTROL_WORDS[low], None)
        return ("text", content)

    return ("timeout", None)


# ---------------------------------------------------------------------------
# Talent refresh background task
# ---------------------------------------------------------------------------

async def talent_refresh_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            talent_cache.refresh_cache()
        except Exception as e:
            print(f"[Talents] Refresh failed: {e}")
        await asyncio.sleep(6 * 3600)


# ---------------------------------------------------------------------------
# /shrine — state-machine flow with cancel/restart/back support
# ---------------------------------------------------------------------------

@tree.command(name="shrine", description="Simulate Shrine of Order on your Deepwoken build")
@app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
async def shrine_command(interaction: discord.Interaction):
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
        await _run_shrine_flow(interaction, user, channel)
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


@shrine_command.error
async def shrine_on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
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


async def _step_base(channel, user, race, build):
    while True:
        view = StepView(allow_back=True)
        await safe_send(channel, "Enter your **base stats** in order: `str fort agi int will cha`", view=view)
        action, content = await wait_for_input(channel, user, view=view)
        if action in ("timeout", "cancel", "restart", "back"):
            return (action, race, build)
        if action != "text":
            continue

        # Single-word non-digit on the base step is treated as a race switch
        if len(content.split()) == 1 and not content.lstrip('-').isdigit():
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
        err = check_caps(new_build, race, step="base")
        if err:
            await safe_send(channel, err)
            continue
        spent = count_points_spent({k: v for k, v in new_build.items() if v > 0})
        racial_total = sum(get_racial_bonus(race, s) for s, v in new_build.items() if v > 0)
        invested = spent - racial_total
        if invested > TOTAL_POINTS:
            await safe_send(channel, f"❌ That's **{invested}** points invested, exceeding the {TOTAL_POINTS} budget. Try again:")
            continue
        await safe_send(channel, f"Base stats set — **{invested}/{TOTAL_POINTS}** points spent, **{TOTAL_POINTS - invested}** left")
        return ("continue", race, new_build)


async def _step_kv(channel, user, race, build, allowed_stats, prompt_text, step_name):
    while True:
        view = StepView(allow_skip=True, allow_back=True)
        await safe_send(channel, prompt_text, view=view)
        action, content = await wait_for_input(channel, user, view=view)
        if action in ("timeout", "cancel", "restart", "back"):
            return (action, build)
        if action == "skip":
            return ("continue", build)
        if action != "text":
            continue

        # Work on a copy so a bad input doesn't corrupt earlier state
        new_build = dict(build)
        try:
            new_build.update(parse_kv_stats(content, allowed_stats))
        except ValueError as e:
            await safe_send(channel, f"❌ {e}\nTry again:")
            continue
        err = check_caps(new_build, race, step=step_name)
        if err:
            await safe_send(channel, err)
            continue
        spent = count_points_spent({k: v for k, v in new_build.items() if v > 0})
        racial_total = sum(get_racial_bonus(race, s) for s, v in new_build.items() if v > 0)
        invested = spent - racial_total
        if invested > TOTAL_POINTS:
            await safe_send(channel, f"❌ That's **{invested}** points invested, exceeding the {TOTAL_POINTS} budget. Try again:")
            continue
        await safe_send(
            channel,
            f"{step_name.capitalize()} set — **{invested}/{TOTAL_POINTS}** points spent, **{TOTAL_POINTS - invested}** left"
        )
        return ("continue", new_build)


async def _step_confirm(channel, user, race, build):
    while True:
        view = ConfirmView()
        await safe_send(channel, embed=build_summary_embed(race, build), view=view)
        action, _ = await wait_for_input(channel, user, view=view)
        if action == "timeout":
            return "timeout"
        if action in ("confirm", "restart", "cancel", "back"):
            return action


async def _run_shrine_flow(interaction, user, channel):
    # Send the initial race prompt
    await interaction.response.send_message(embed=races_embed())

    while True:  # restart loop
        race = None
        build = {stat: 0 for stat in ALL_STATS}
        snapshots = []  # (race, build) saved before each step

        # Step 1: race
        view = StepView(allow_back=False)
        prompt = await safe_send(channel, "_(Type a race name, or use the buttons.)_", view=view)
        while race is None:
            action, content = await wait_for_input(channel, user, view=view)
            if action == "timeout":
                await safe_send(channel, "❌ Timed out. Run `/shrine` again.")
                return
            if action == "cancel":
                await safe_send(channel, "✖ Cancelled.")
                return
            if action == "back":
                await safe_send(channel, "_(You're on the first step — nothing to go back to.)_")
                view = StepView(allow_back=False)
                await safe_send(channel, "_(Type a race name, or use the buttons.)_", view=view)
                continue
            if action == "restart":
                break
            if action == "text":
                matched = match_race(content)
                if not matched:
                    await safe_send(channel, f"❌ Unknown race: `{content}`. Try again:\nValid races: {VALID_RACES}")
                    view = StepView(allow_back=False)
                    await safe_send(channel, "_(Type a race name, or use the buttons.)_", view=view)
                    continue
                race = matched
                await safe_send(channel, race_confirmed_msg(race))
                break
            view = StepView(allow_back=False)
            await safe_send(channel, "_(Type a race name, or use the buttons.)_", view=view)

        if race is None:
            continue  # restart

        # Step 2: base stats
        snapshots.append((race, build.copy()))
        action, race, build = await _step_base(channel, user, race, build)
        if action == "timeout":
            await safe_send(channel, "❌ Timed out. Run `/shrine` again.")
            return
        if action == "cancel":
            await safe_send(channel, "✖ Cancelled.")
            return
        if action == "restart":
            continue
        if action == "back":
            continue  # restart (only step before this is race)

        # Step 3: attunements
        snapshots.append((race, build.copy()))
        action, build = await _step_kv(
            channel, user, race, build, list(ATTUNEMENTS),
            "Any **attunements**? Enter all separated by spaces:\n`flame=80 thunder=35 frost=40`",
            "attunement",
        )
        if action == "timeout":
            await safe_send(channel, "❌ Timed out. Run `/shrine` again.")
            return
        if action == "cancel":
            await safe_send(channel, "✖ Cancelled.")
            return
        if action == "restart":
            continue
        if action == "back":
            race, build = snapshots[-1]
            snapshots = snapshots[:-1]
            # Re-run base step
            action, race, build = await _step_base(channel, user, race, build)
            if action == "cancel":
                await safe_send(channel, "✖ Cancelled.")
                return
            if action == "restart" or action == "back" or action == "timeout":
                if action == "timeout":
                    await safe_send(channel, "❌ Timed out. Run `/shrine` again.")
                    return
                continue
            # Then re-run attunements once
            snapshots.append((race, build.copy()))
            action, build = await _step_kv(
                channel, user, race, build, list(ATTUNEMENTS),
                "Any **attunements**? Enter all separated by spaces:\n`flame=80 thunder=35 frost=40`",
                "attunement",
            )
            if action in ("cancel", "restart", "back", "timeout"):
                if action == "timeout":
                    await safe_send(channel, "❌ Timed out. Run `/shrine` again.")
                    return
                if action == "cancel":
                    await safe_send(channel, "✖ Cancelled.")
                    return
                continue

        # Steps 4 & 5: weapon + confirm in an inner loop so "back" from
        # confirm reruns just the weapon step.
        weapon_snapshot_pushed = False
        while True:
            # Step 4: weapon
            if not weapon_snapshot_pushed:
                snapshots.append((race, build.copy()))
                weapon_snapshot_pushed = True
            action, build = await _step_kv(
                channel, user, race, build, ["LightWeapon", "MediumWeapon", "HeavyWeapon"],
                "Any **weapon**? e.g. `med=85` or `light=60` or `heavy=70`",
                "weapon",
            )
            if action == "timeout":
                await safe_send(channel, "❌ Timed out. Run `/shrine` again.")
                return
            if action == "cancel":
                await safe_send(channel, "✖ Cancelled.")
                return
            if action == "restart":
                break  # break inner, outer 'continue' below
            if action == "back":
                race, build = snapshots[-1]
                snapshots = snapshots[:-1]
                # Re-run attunements step
                action, build = await _step_kv(
                    channel, user, race, build, list(ATTUNEMENTS),
                    "Any **attunements**? Enter all separated by spaces:\n`flame=80 thunder=35 frost=40`",
                    "attunement",
                )
                if action in ("cancel", "restart", "timeout", "back"):
                    if action == "timeout":
                        await safe_send(channel, "❌ Timed out. Run `/shrine` again.")
                        return
                    if action == "cancel":
                        await safe_send(channel, "✖ Cancelled.")
                        return
                    break  # break inner, outer continue
                # Loop and rerun weapon step
                weapon_snapshot_pushed = False
                continue

            # Step 5: confirm
            confirm_action = await _step_confirm(channel, user, race, build)
            if confirm_action == "timeout":
                await safe_send(channel, "❌ Timed out. Run `/shrine` again.")
                return
            if confirm_action == "cancel":
                await safe_send(channel, "✖ Cancelled.")
                return
            if confirm_action == "restart":
                break  # break inner, outer continue
            if confirm_action == "back":
                # Pop weapon snapshot and rerun weapon step
                race, build = snapshots[-1]
                snapshots = snapshots[:-1]
                weapon_snapshot_pushed = False
                continue
            # confirmed
            break

        # If we broke out due to restart/timeout/cancel, the action vars
        # already returned. We only fall through here on confirm.
        if action == "restart" or confirm_action == "restart":
            continue

        # Run shrine
        invested = count_points_spent({k: v for k, v in build.items() if v > 0})
        racial_total = sum(get_racial_bonus(race, s) for s, v in build.items() if v > 0)
        points_before = TOTAL_POINTS - (invested - racial_total)
        before = build.copy()
        try:
            after, spare = shrine_of_order(build, race)
        except ValueError as e:
            await safe_send(channel, f"❌ {e}\nRun `/shrine` again.")
            return

        await safe_send(channel, embed=build_shrine_embed(race, before, after, spare + points_before, points_before))
        return


# ---------------------------------------------------------------------------
# /talents — with autocomplete, rarity & category filters, exact/gte search
# ---------------------------------------------------------------------------

async def talent_query_autocomplete(interaction: discord.Interaction, current: str):
    # Don't autocomplete when the user is typing a stat query like "40 Agility"
    stripped = (current or "").strip()
    if re.match(r"^\d+\+?(\s+|$)", stripped):
        return []
    names = talent_cache.autocomplete_names(stripped, limit=25)
    return [app_commands.Choice(name=n[:100], value=n[:100]) for n in names]


RARITY_CHOICES = [app_commands.Choice(name=r, value=r) for r in talent_cache.ALL_RARITIES]


@tree.command(name="talents", description="Look up Deepwoken talents by name or stat requirement")
@app_commands.describe(
    query='Talent name (e.g. "Ghost") or stat requirement ("40 Agility", "40+ Agility")',
    rarity="Filter by rarity (only applies to stat searches)",
    category="Filter by category text (e.g. 'Butterfly', 'Tactician') — only for stat searches",
)
@app_commands.autocomplete(query=talent_query_autocomplete)
@app_commands.choices(rarity=RARITY_CHOICES)
@app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)
async def talents_command(
    interaction: discord.Interaction,
    query: str,
    rarity: app_commands.Choice[str] = None,
    category: str = None,
):
    await interaction.response.defer()

    rarity_str = rarity.value if rarity else None

    stat_query = talent_cache.parse_stat_query(query)

    if stat_query:
        level, stat, mode = stat_query
        # If the user explicitly picked rarity:Oath, let oaths through;
        # otherwise the search excludes them by default.
        include_oaths = (rarity_str == "Oath")
        results = talent_cache.search_by_stat(stat, level, mode=mode, include_oaths=include_oaths)
        if rarity_str or category:
            results = talent_cache.filter_results(results, rarity=rarity_str, category=category)
        embeds = talent_cache.build_stat_results_embeds(
            stat, level, results, mode=mode, rarity=rarity_str, category=category
        )
        await interaction.followup.send(embeds=embeds)
    else:
        talent, was_fuzzy = talent_cache.search_by_name(query)
        if not talent:
            await interaction.followup.send(
                f"❌ No talent found matching `{query}`. Check your spelling and try again."
            )
            return
        embed = talent_cache.build_talent_embed(talent, did_you_mean=was_fuzzy)
        await interaction.followup.send(embed=embed)


@talents_command.error
async def talents_on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
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


# ---------------------------------------------------------------------------
# /races and /help
# ---------------------------------------------------------------------------

@tree.command(name="races", description="List all races and their stat bonuses")
async def races_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🧬 Deepwoken Races", color=0x2ECC71)
    lines = []
    for race, bonuses in RACIAL_STATS.items():
        bonus_str = ", ".join(f"+{v} {k}" for k, v in bonuses.items()) if bonuses else "No bonuses"
        lines.append(f"**{race.capitalize()}** — {bonus_str}")
    embed.description = "\n".join(lines)
    await interaction.response.send_message(embed=embed)


@tree.command(name="help", description="How to use the Deepwoken shrine bot")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Shrine Bot — Help", color=0x3498DB)
    embed.add_field(name="Commands", value=(
        "`/shrine` — start the shrine flow\n"
        "`/talents` — look up a talent by name or stat\n"
        "`/races` — list all races & bonuses\n"
        "`/help` — this message"
    ), inline=False)
    embed.add_field(name="During /shrine", value=(
        "Type `cancel`, `restart`, or `back` at any time, or use the buttons."
    ), inline=False)
    embed.add_field(name="How /shrine works", value=(
        "1. Pick your race\n"
        "2. Enter base stats: `str fort agi int will cha`\n"
        "3. Enter attunements (or skip): `flame=80 thunder=35`\n"
        "4. Enter weapon (or skip): `med=85`\n"
        "5. Confirm to run shrine"
    ), inline=False)
    embed.add_field(name="How /talents works", value=(
        "Search by name: `/talents Kick Off` (autocomplete enabled)\n"
        "Stat exact: `/talents 40 Agility`\n"
        "Stat or higher: `/talents 40+ Agility`\n"
        "Filter by rarity: pick the optional `rarity` field\n"
        "Filter by category: type into the optional `category` field"
    ), inline=False)
    embed.add_field(name="Stat shortcuts", value=(
        "`str` `fort` `agi` `int` `will` `cha`\n"
        "`flame` `frost` `thunder` `gale` `shadow` `iron` `blood`\n"
        "`light` `med` `heavy`"
    ), inline=False)
    embed.set_footer(text="330 total investment points · attunements exempt from −25 cap")
    await interaction.response.send_message(embed=embed)


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
        bot.loop.create_task(talent_refresh_loop())
    print(f"✅ Logged in as {bot.user}")


TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("❌ DISCORD_TOKEN environment variable is not set. Add it in Replit Secrets.")

keep_alive()
bot.run(TOKEN)
