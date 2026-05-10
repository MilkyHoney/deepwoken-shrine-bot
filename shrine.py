MAXIMUM_REDUCTION = 25
TOTAL_POINTS = 330
MAX_STAT_INVESTMENT = 100

RACIAL_STATS = {
    "adret":     {"Charisma": 3, "Willpower": 2},
    "canor":     {"Strength": 3, "Charisma": 2},
    "capra":     {"Intelligence": 3, "Willpower": 2},
    "celtor":    {"Charisma": 3, "Intelligence": 2},
    "chrysid":   {"Charisma": 3, "Agility": 2},
    "etrean":    {"Intelligence": 3, "Agility": 2},
    "felinor":   {"Agility": 3, "Charisma": 2},
    "ganymede":  {"Willpower": 3, "Intelligence": 2},
    "gremor":    {"Fortitude": 3, "Strength": 2},
    "khan":      {"Strength": 3, "Agility": 2},
    "kiron":     {"Agility": 3, "Intelligence": 2},
    "tiran":     {"Agility": 3, "Willpower": 2},
    "vesperian": {"Fortitude": 3, "Willpower": 2},
    "lightborn": {"Strength": 2, "Fortitude": 2, "Agility": 2, "Intelligence": 2, "Willpower": 2, "Charisma": 2},
    "drakkard":  {"Agility": 3, "Fortitude": 2},
    "none":      {},
}

ATTUNEMENTS = {"Flamecharm", "Frostdraw", "Thundercall", "Galebreathe", "Shadowcast", "Ironsing", "Bloodrend"}

ALL_STATS = [
    "Strength", "Fortitude", "Agility", "Intelligence", "Willpower", "Charisma",
    "Flamecharm", "Frostdraw", "Thundercall", "Galebreathe", "Shadowcast", "Ironsing", "Bloodrend",
    "LightWeapon", "MediumWeapon", "HeavyWeapon",
]


def get_racial_bonus(race: str, stat: str) -> int:
    return RACIAL_STATS.get(race, {}).get(stat, 0)


def count_points_spent(stats: dict) -> int:
    """Returns total stat points used, including racial bonuses (they count toward the 330 budget)."""
    return sum(stats.values())


def shrine_of_order(stats: dict, race: str) -> tuple[dict, int]:
    race = race.lower()
    if race not in RACIAL_STATS:
        raise ValueError(f"Unknown race: '{race}'")

    # Validate stats
    for stat, value in stats.items():
        if stat not in ALL_STATS:
            raise ValueError(f"Unknown stat: '{stat}'")
        racial = get_racial_bonus(race, stat)
        invested = value - racial
        if invested < 0:
            raise ValueError(f"{stat} cannot be below its racial bonus of {racial}")
        if invested > MAX_STAT_INVESTMENT:
            raise ValueError(f"{stat} exceeds the 100 point investment cap (you have {invested} invested)")

    # Work on a copy so we don't mutate the original
    stats = {k: v for k, v in stats.items()}

    points_spent = count_points_spent(stats)
    preshrine = stats.copy()

    # Find stats the player has actually invested in (excluding pure racial stats)
    # Track pure racial points separately so they aren't included in redistribution
    affected_stats = []
    pure_racial_points = 0
    for stat, value in stats.items():
        if value <= 0:
            continue
        racial = get_racial_bonus(race, stat)
        if value - racial == 0:
            pure_racial_points += value
            continue  # Only racial points here, not invested
        affected_stats.append(stat)

    if not affected_stats:
        return stats, 0

    # Effective pool excludes pure racial points since shrine can't redistribute them
    effective_pool = points_spent - pure_racial_points

    # Initial even split across all affected stats
    base_value = effective_pool / len(affected_stats)
    for stat in affected_stats:
        stats[stat] = base_value

    # Bottlenecking loop: cap non-attunement stat reductions at 25
    bottlenecked = []
    divide_by = len(affected_stats)
    previous = stats.copy()

    while True:
        bottlenecked_points = 0
        new_bottleneck_found = False

        for stat in affected_stats:
            if stat in ATTUNEMENTS or stat in bottlenecked:
                continue
            reduction = preshrine[stat] - stats[stat]
            if reduction > MAXIMUM_REDUCTION:
                capped_value = preshrine[stat] - MAXIMUM_REDUCTION
                bottlenecked_points += capped_value - previous[stat]
                stats[stat] = capped_value
                bottlenecked.append(stat)
                divide_by -= 1
                new_bottleneck_found = True

        if not new_bottleneck_found:
            break

        # Redistribute the excess from bottlenecked stats
        for stat in affected_stats:
            if stat in bottlenecked:
                continue
            stats[stat] -= bottlenecked_points / divide_by

        previous = stats.copy()

    # Floor all stats with epsilon to fix float precision
    # (e.g. 25.9999999996 should be 26, but 48.571 should be 48)
    import math
    for stat in affected_stats:
        stats[stat] = math.floor(stats[stat] + 1e-9)

    # Calculate spare points after flooring
    points_after = count_points_spent(stats)
    spare = points_spent - points_after

    # If spare >= number of affected stats, give everyone +1
    if spare >= len(affected_stats):
        for stat in affected_stats:
            stats[stat] += 1
        spare -= len(affected_stats)

    return stats, spare


def format_build(before: dict, after: dict, spare: int, race: str) -> str:
    lines = [f"{'Stat':<14} {'Before':>7} {'After':>7} {'Change':>7}"]
    lines.append("-" * 40)
    for stat in ALL_STATS:
        b = before.get(stat, 0)
        a = after.get(stat, 0)
        if b == 0 and a == 0:
            continue
        change = a - b
        sign = "+" if change > 0 else ""
        lines.append(f"{stat:<14} {b:>7} {a:>7} {sign + str(change):>7}")
    lines.append("-" * 40)
    lines.append(f"Spare points: {spare}")
    return "\n".join(lines)


# --- Test with the verified build ---
if __name__ == "__main__":
    test_build = {
        "Strength":    40,
        "Fortitude":   50,
        "Agility":     25,
        "Intelligence": 0,
        "Willpower":   40,
        "Charisma":    55,
        "LightWeapon":  1,
        "Flamecharm":  100,
    }

    before = test_build.copy()
    after, spare = shrine_of_order(test_build, "khan")
    print(format_build(before, after, spare, "khan"))
