from __future__ import annotations

import datetime as dt
import json
import os
import re
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo


CARD_PATH = Path("profile/streak.svg")
REPOSITORY_COUNT = os.getenv("TOTAL_REPOSITORIES", "41").strip()
LAST_ACTIVITY_OVERRIDE = os.getenv("LAST_ACTIVITY", "").strip()
PROFILE_TIMEZONE = os.getenv("PROFILE_TIMEZONE", "America/Sao_Paulo").strip()

LEFT_X = "126.66666666667"
CENTER_X = "380"
RIGHT_X = "633.33333333333"
LABEL_Y = "95.5"
DETAIL_Y = "125.5"


def github_json(url: str, *, token: str = "", payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "devrenanfroes-profile-stats",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def format_activity_timestamp(value: str) -> str:
    timestamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    try:
        timezone = ZoneInfo(PROFILE_TIMEZONE)
    except Exception:
        timezone = dt.timezone(dt.timedelta(hours=-3))

    local_time = timestamp.astimezone(timezone)
    time_text = local_time.strftime("%I:%M %p").lstrip("0")
    return f"Last activity · {local_time.strftime('%b')} {local_time.day} · {time_text}"


def fetch_last_contribution_day(username: str, token: str) -> str:
    today = dt.date.today()
    start = today - dt.timedelta(days=370)

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """

    data = github_json(
        "https://api.github.com/graphql",
        token=token,
        payload={
            "query": query,
            "variables": {
                "login": username,
                "from": f"{start.isoformat()}T00:00:00Z",
                "to": f"{today.isoformat()}T23:59:59Z",
            },
        },
    )

    if data.get("errors"):
        raise RuntimeError(json.dumps(data["errors"], ensure_ascii=False))

    user = data.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user not found: {username}")

    latest: dt.date | None = None
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    for week in weeks:
        for day in week.get("contributionDays", []):
            if int(day.get("contributionCount", 0)) <= 0:
                continue
            date = dt.date.fromisoformat(day["date"])
            if latest is None or date > latest:
                latest = date

    if latest is None:
        return "Last activity · no recent contributions"

    return f"Last activity · {latest.strftime('%b')} {latest.day}"


def fetch_last_activity() -> str:
    if LAST_ACTIVITY_OVERRIDE:
        return LAST_ACTIVITY_OVERRIDE

    username = os.getenv("GITHUB_REPOSITORY_OWNER", "devrenanfroes").strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()

    # The events endpoint has an exact timestamp. It represents the user's latest
    # public GitHub event and lets the card show the real clock time instead of
    # inventing one from the daily contribution calendar.
    try:
        events = github_json(
            f"https://api.github.com/users/{username}/events/public?per_page=1",
            token=token,
        )
        if isinstance(events, list) and events:
            created_at = events[0].get("created_at")
            if created_at:
                return format_activity_timestamp(created_at)
    except Exception:
        pass

    # Fallback: if exact event time is unavailable, show the real contribution
    # date rather than a fake or stale clock time.
    if token:
        try:
            return fetch_last_contribution_day(username, token)
        except Exception:
            pass

    return "Last activity · unavailable"


def extract_value(svg: str, marker: str) -> str:
    pattern = rf"(<!-- {re.escape(marker)} -->.*?<text\b[^>]*>)\s*(.*?)\s*(</text>)"
    match = re.search(pattern, svg, flags=re.DOTALL)
    if not match:
        raise RuntimeError(f"Could not find marker: {marker}")
    return match.group(2).strip()


def replace_value(svg: str, marker: str, value: str) -> str:
    pattern = rf"(<!-- {re.escape(marker)} -->.*?<text\b[^>]*>)\s*.*?\s*(</text>)"
    replacement = rf"\1\n                        {value}\n                    \2"
    updated, count = re.subn(pattern, replacement, svg, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"Could not replace marker: {marker}")
    return updated


def replace_marker_block(svg: str, marker: str, old: str, new: str) -> str:
    pattern = rf"(<!-- {re.escape(marker)} -->.*?)(?=<!--|</g>\s*</g>)"
    match = re.search(pattern, svg, flags=re.DOTALL)
    if not match:
        raise RuntimeError(f"Could not find block: {marker}")
    block = match.group(1)
    updated_block = block.replace(old, new, 1)
    if updated_block == block:
        raise RuntimeError(f"Could not update block: {marker}")
    return svg[: match.start(1)] + updated_block + svg[match.end(1) :]


def set_marker_translate(svg: str, marker: str, x: str, y: str) -> str:
    pattern = rf"(<!-- {re.escape(marker)} -->\s*<g transform='translate\()([^,]+),\s*([^)]+)(\)'>)"

    def replacement(match: re.Match[str]) -> str:
        return f"{match.group(1)}{x}, {y}{match.group(4)}"

    updated, count = re.subn(pattern, replacement, svg, count=1)
    if count != 1:
        raise RuntimeError(f"Could not position marker: {marker}")
    return updated


def main() -> None:
    svg = CARD_PATH.read_text(encoding="utf-8")
    last_activity = fetch_last_activity()

    current_streak = extract_value(svg, "Current Streak big number")
    current_range = extract_value(svg, "Current Streak range")

    # Use one shared vertical grid for all three columns. The lower label row
    # leaves enough breathing room below the streak ring instead of letting the
    # text collide with it.
    svg = set_marker_translate(svg, "Total Contributions label", LEFT_X, LABEL_Y)
    svg = set_marker_translate(svg, "Total Contributions range", LEFT_X, DETAIL_Y)

    # Center column: repository count + latest activity.
    svg = replace_value(svg, "Current Streak big number", REPOSITORY_COUNT)
    svg = replace_value(svg, "Current Streak label", "Repositories")
    svg = replace_value(svg, "Current Streak range", last_activity)
    svg = set_marker_translate(svg, "Current Streak label", CENTER_X, LABEL_Y)
    svg = set_marker_translate(svg, "Current Streak range", CENTER_X, DETAIL_Y)
    svg = replace_marker_block(svg, "Current Streak range", "y='21'", "y='32'")
    svg = replace_marker_block(svg, "Current Streak range", "fill='#737373'", "fill='#a3a3a3'")

    # Move the streak ring/fire from the center to the right column.
    svg = svg.replace("cx='380' cy='32'", f"cx='{RIGHT_X}' cy='32'", 1)
    svg = svg.replace("cx='380' cy='68.5'", f"cx='{RIGHT_X}' cy='68.5'", 1)
    svg = svg.replace("translate(380, 17)", f"translate({RIGHT_X}, 17)", 1)

    # Right column: current streak on the same label/detail grid as the other
    # columns, while the number remains centered inside the ring.
    svg = replace_value(svg, "Longest Streak big number", current_streak)
    svg = replace_value(svg, "Longest Streak label", "Current Streak")
    svg = replace_value(svg, "Longest Streak range", current_range)
    svg = set_marker_translate(svg, "Longest Streak label", RIGHT_X, LABEL_Y)
    svg = set_marker_translate(svg, "Longest Streak range", RIGHT_X, DETAIL_Y)
    svg = replace_marker_block(
        svg,
        "Longest Streak label",
        "font-weight='400'",
        "font-weight='700'",
    )

    CARD_PATH.write_text(svg, encoding="utf-8")


if __name__ == "__main__":
    main()
