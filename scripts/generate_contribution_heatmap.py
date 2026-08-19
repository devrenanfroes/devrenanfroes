#!/usr/bin/env python3

import datetime as dt
import json
import os
import sys
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


def fetch_calendar(username: str, token: str):
    today = dt.date.today()
    start = today - dt.timedelta(days=370)

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks {
              firstDay
              contributionDays {
                date
                contributionCount
                color
              }
            }
          }
        }
      }
    }
    """

    payload = {
        "query": query,
        "variables": {
            "login": username,
            "from": f"{start.isoformat()}T00:00:00Z",
            "to": f"{today.isoformat()}T23:59:59Z",
        },
    }

    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "devrenanfroes-profile-heatmap",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)

    if data.get("errors"):
        raise RuntimeError(json.dumps(data["errors"], ensure_ascii=False))

    user = data.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user not found: {username}")

    return user["contributionsCollection"]["contributionCalendar"]["weeks"][-MAX_WEEKS:]


def month_labels(weeks):
    labels = []
    previous_month = None

    for index, week in enumerate(weeks):
        days = week.get("contributionDays", [])
        if not days:
            continue
        first_date = dt.date.fromisoformat(days[0]["date"])
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

    for week_index, week in enumerate(weeks):
        for day in week.get("contributionDays", []):
            date = dt.date.fromisoformat(day["date"])
            row = (date.weekday() + 1) % 7
            x = GRID_X + week_index * (CELL + GAP)
            y = GRID_Y + row * (CELL + GAP)
            count = int(day.get("contributionCount", 0))
            fill = ACTIVE if count > 0 else INACTIVE
            lines.append(
                f'  <rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{fill}"><title>{date.isoformat()}: {count} contributions</title></rect>'
            )

    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def main():
    username = os.getenv("GITHUB_REPOSITORY_OWNER", "devrenanfroes")
    token = os.getenv("GITHUB_TOKEN")

    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")

    try:
        weeks = fetch_calendar(username, token)
        if not weeks:
            raise RuntimeError("Contribution calendar returned no weeks")

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
