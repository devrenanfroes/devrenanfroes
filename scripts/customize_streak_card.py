from __future__ import annotations

import datetime as dt
import os
import re
import time
import urllib.request
from pathlib import Path


CARD_PATH = Path("profile/streak.svg")
RAW_CARD_PATH = Path(os.getenv("RAW_STREAK_PATH", str(CARD_PATH)))

LEFT_X = "126.66666666667"
CENTER_X = "380"
RIGHT_X = "633.33333333333"
LABEL_Y = "95.5"
DETAIL_Y = "125.5"


def fetch_contribution_days(username: str) -> dict[dt.date, bool]:
    url = f"https://github.com/users/{username}/contributions"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "devrenanfroes-profile-stats",
        },
    )

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                html = response.read().decode("utf-8", errors="replace")
            break
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2)
    else:
        raise RuntimeError(f"Could not fetch contribution calendar: {last_error}")

    days: dict[dt.date, bool] = {}
    tag_pattern = re.compile(
        r"<(?:td|rect)\b[^>]*\bdata-date=['\"](\d{4}-\d{2}-\d{2})['\"][^>]*>",
        re.IGNORECASE,
    )

    for match in tag_pattern.finditer(html):
        tag = match.group(0)
        date = dt.date.fromisoformat(match.group(1))

        count_match = re.search(r"\bdata-count=['\"](\d+)['\"]", tag, re.IGNORECASE)
        level_match = re.search(r"\bdata-level=['\"](\d+)['\"]", tag, re.IGNORECASE)

        if count_match:
            active = int(count_match.group(1)) > 0
        elif level_match:
            active = int(level_match.group(1)) > 0
        else:
            active = False

        days[date] = active

    if not days:
        raise RuntimeError("Contribution calendar contained no contribution days")

    return days


def profile_activity_summary(username: str) -> tuple[str, str]:
    days = fetch_contribution_days(username)
    today = dt.date.today()
    start = today - dt.timedelta(days=370)
    recent = {date: active for date, active in days.items() if start <= date <= today}

    active_dates = sorted(date for date, active in recent.items() if active)
    active_days = str(len(active_dates))

    if active_dates:
        latest = active_dates[-1]
        last_activity = f"Last activity · {latest.strftime('%b')} {latest.day}"
    else:
        last_activity = "Last activity · unavailable"

    return active_days, last_activity


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
    svg = RAW_CARD_PATH.read_text(encoding="utf-8")
    username = os.getenv("GITHUB_REPOSITORY_OWNER", "devrenanfroes").strip()
    active_days, last_activity = profile_activity_summary(username)

    current_streak = extract_value(svg, "Current Streak big number")
    current_range = extract_value(svg, "Current Streak range")

    svg = set_marker_translate(svg, "Total Contributions label", LEFT_X, LABEL_Y)
    svg = set_marker_translate(svg, "Total Contributions range", LEFT_X, DETAIL_Y)

    # Center column: a fully automatic metric from the same contribution calendar.
    svg = replace_value(svg, "Current Streak big number", active_days)
    svg = replace_value(svg, "Current Streak label", "Active Days")
    svg = replace_value(svg, "Current Streak range", last_activity)
    svg = set_marker_translate(svg, "Current Streak label", CENTER_X, LABEL_Y)
    svg = set_marker_translate(svg, "Current Streak range", CENTER_X, DETAIL_Y)
    svg = replace_marker_block(svg, "Current Streak range", "y='21'", "y='32'")
    svg = replace_marker_block(svg, "Current Streak range", "fill='#737373'", "fill='#a3a3a3'")

    # Move the streak ring/fire to the right column.
    svg = svg.replace("cx='380' cy='32'", f"cx='{RIGHT_X}' cy='32'", 1)
    svg = svg.replace("cx='380' cy='68.5'", f"cx='{RIGHT_X}' cy='68.5'", 1)
    svg = svg.replace("translate(380, 17)", f"translate({RIGHT_X}, 17)", 1)

    # Right column: current streak from the streak-stats generator.
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

    CARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    CARD_PATH.write_text(svg, encoding="utf-8")


if __name__ == "__main__":
    main()
