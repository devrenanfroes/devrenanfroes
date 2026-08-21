#!/usr/bin/env python3

import datetime as dt
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

OUTPUT = Path("profile/contributions.svg")
WIDTH = 760
HEIGHT = 140
CELL = 10
GAP = 3
MAX_WEEKS = 53
GRID_WIDTH = MAX_WEEKS * CELL + (MAX_WEEKS - 1) * GAP
GRID_X = (WIDTH - GRID_WIDTH) // 2
GRID_Y = 38

INACTIVE = "#161B22"
ACTIVE = "#C7CDD3"
MUTED = "#737373"
BACKGROUND = "#0D1117"
BORDER = "#2A2A2A"


def fetch_days(username: str) -> dict[dt.date, int]:
    url = f"https://github.com/users/{username}/contributions"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "devrenanfroes-profile-heatmap",
        },
    )

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                source = response.read().decode("utf-8", errors="replace")
            break
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2)
    else:
        raise RuntimeError(f"Could not fetch contribution calendar: {last_error}")

    days: dict[dt.date, int] = {}
    tag_pattern = re.compile(
        r"<(?:td|rect)\b[^>]*\bdata-date=['\"](\d{4}-\d{2}-\d{2})['\"][^>]*>",
        re.IGNORECASE,
    )

    for match in tag_pattern.finditer(source):
        tag = match.group(0)
        date = dt.date.fromisoformat(match.group(1))

        count_match = re.search(r"\bdata-count=['\"](\d+)['\"]", tag, re.IGNORECASE)
        if count_match:
            count = int(count_match.group(1))
        else:
            level_match = re.search(r"\bdata-level=['\"](\d+)['\"]", tag, re.IGNORECASE)
            count = 1 if level_match and int(level_match.group(1)) > 0 else 0

        days[date] = count

    if not days:
        raise RuntimeError("Contribution calendar contained no contribution days")

    return days


def build_weeks(days: dict[dt.date, int]):
    today = dt.date.today()
    start = today - dt.timedelta(days=370)

    visible = {date: count for date, count in days.items() if start <= date <= today}
    if not visible:
        raise RuntimeError("No recent contribution days were returned")

    first_date = min(visible)
    first_sunday = first_date - dt.timedelta(days=(first_date.weekday() + 1) % 7)

    weeks = []
    week_start = first_sunday
    while week_start <= today:
        week_days = []
        for offset in range(7):
            date = week_start + dt.timedelta(days=offset)
            if start <= date <= today:
                week_days.append((date, visible.get(date, 0)))
        weeks.append((week_start, week_days))
        week_start += dt.timedelta(days=7)

    return weeks[-MAX_WEEKS:]


def month_labels(weeks):
    labels = []
    previous_month = None

    for index, (_, week_days) in enumerate(weeks):
        if not week_days:
            continue
        first_date = week_days[0][0]
        month = first_date.month
        if month != previous_month:
            labels.append((index, first_date.strftime("%b")))
            previous_month = month

    return labels


def render_svg(username: str, weeks):
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" role="img" aria-labelledby="title desc">',
        f'  <title id="title">{username} GitHub contribution heatmap</title>',
        '  <desc id="desc">Contribution activity over the last twelve months.</desc>',
        f'  <rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="8" fill="{BACKGROUND}" stroke="{BORDER}"/>',
    ]

    for week_index, label in month_labels(weeks):
        x = GRID_X + week_index * (CELL + GAP)
        lines.append(
            f'  <text x="{x}" y="22" fill="{MUTED}" font-family="Segoe UI, Ubuntu, sans-serif" font-size="11">{label}</text>'
        )

    for week_index in range(MAX_WEEKS):
        for row in range(7):
            x = GRID_X + week_index * (CELL + GAP)
            y = GRID_Y + row * (CELL + GAP)
            lines.append(
                f'  <rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{INACTIVE}"/>'
            )

    offset = MAX_WEEKS - len(weeks)
    for source_week_index, (_, week_days) in enumerate(weeks):
        week_index = offset + source_week_index
        for date, count in week_days:
            row = (date.weekday() + 1) % 7
            x = GRID_X + week_index * (CELL + GAP)
            y = GRID_Y + row * (CELL + GAP)
            fill = ACTIVE if count > 0 else INACTIVE
            noun = "contribution" if count == 1 else "contributions"
            lines.append(
                f'  <rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{fill}"><title>{date.isoformat()}: {count} {noun}</title></rect>'
            )

    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def main():
    username = os.getenv("GITHUB_REPOSITORY_OWNER", "devrenanfroes")

    try:
        days = fetch_days(username)
        weeks = build_weeks(days)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(render_svg(username, weeks), encoding="utf-8")
        print(f"Updated {OUTPUT}")
    except Exception as exc:
        if OUTPUT.exists():
            print(f"Warning: heatmap update failed; preserving existing SVG: {exc}", file=sys.stderr)
            return
        raise


if __name__ == "__main__":
    main()
