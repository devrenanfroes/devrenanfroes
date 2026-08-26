from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

CARD_PATH = Path("profile/streak.svg")
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
DEFAULT_REPOSITORY_COUNT = 42

WIDTH = 760
HEIGHT = 190
LEFT_X = 126.66666666667
CENTER_X = 380
RIGHT_X = 633.33333333333

BACKGROUND = "#0D1117"
BORDER = "#2A2A2A"
PRIMARY = "#F5F5F5"
SECONDARY = "#A3A3A3"
MUTED = "#737373"


def read_request(request: urllib.request.Request) -> bytes:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2)
    raise RuntimeError(f"GitHub/profile request failed: {last_error}")


def available_github_token() -> str:
    return os.getenv("PROFILE_TOKEN", "").strip() or os.getenv("GITHUB_TOKEN", "").strip()


def graphql(query: str, variables: dict, token: str) -> dict:
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "devrenanfroes-profile-stats",
        },
        method="POST",
    )
    payload = json.loads(read_request(request).decode("utf-8"))
    if payload.get("errors"):
        raise RuntimeError(f"GitHub GraphQL returned errors: {payload['errors']}")
    return payload.get("data", {})


def fetch_recent_from_graphql(username: str, token: str) -> tuple[dict[dt.date, int], int]:
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(days=364)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        repositories(ownerAffiliations: [OWNER], first: 1) { totalCount }
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks {
              contributionDays { date contributionCount }
            }
          }
        }
      }
    }
    """
    data = graphql(
        query,
        {
            "login": username,
            "from": start.isoformat().replace("+00:00", "Z"),
            "to": now.isoformat().replace("+00:00", "Z"),
        },
        token,
    )
    user = data.get("user")
    if not user:
        raise RuntimeError("GitHub GraphQL returned no user")

    days: dict[dt.date, int] = {}
    calendar = user["contributionsCollection"]["contributionCalendar"]
    for week in calendar.get("weeks", []):
        for item in week.get("contributionDays", []):
            days[dt.date.fromisoformat(item["date"])] = int(item["contributionCount"])
    if not days:
        raise RuntimeError("GitHub GraphQL returned no contribution days")

    return days, int(user.get("repositories", {}).get("totalCount", 0))


def fetch_url(url: str, accept: str) -> bytes:
    return read_request(
        urllib.request.Request(
            url,
            headers={"Accept": accept, "User-Agent": "devrenanfroes-profile-stats"},
        )
    )


def fetch_days_from_github_html(username: str) -> dict[dt.date, int]:
    source = fetch_url(
        f"https://github.com/users/{username}/contributions",
        "text/html,application/xhtml+xml",
    ).decode("utf-8", errors="replace")

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
        raise RuntimeError("GitHub contribution calendar contained no contribution days")
    return days


def fetch_days_from_contributions_api(username: str) -> dict[dt.date, int]:
    payload = json.loads(
        fetch_url(
            f"https://github-contributions-api.jogruber.de/v4/{username}?y=last",
            "application/json",
        ).decode("utf-8")
    )
    days: dict[dt.date, int] = {}
    for item in payload.get("contributions", []):
        date_text = item.get("date")
        if date_text:
            days[dt.date.fromisoformat(date_text)] = int(item.get("count", 0))
    if not days:
        raise RuntimeError("Contribution API returned no contribution days")
    return days


def fetch_recent_days(username: str) -> tuple[dict[dt.date, int], int]:
    token = available_github_token()
    errors: list[str] = []
    if token:
        try:
            return fetch_recent_from_graphql(username, token)
        except Exception as exc:
            errors.append(str(exc))

    for loader in (fetch_days_from_github_html, fetch_days_from_contributions_api):
        try:
            return loader(username), 0
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError("; ".join(errors))


def repository_count(graphql_count: int) -> int:
    configured = int(
        os.getenv("PROFILE_REPOSITORY_COUNT", str(DEFAULT_REPOSITORY_COUNT)).strip()
    )
    # GITHUB_TOKEN is repository-scoped and can undercount repositories.
    # Only trust the GraphQL count when a broader PROFILE_TOKEN is configured.
    if os.getenv("PROFILE_TOKEN", "").strip() and graphql_count > 0:
        return graphql_count
    return configured


def fetch_all_time_total(username: str, recent_days: dict[dt.date, int]) -> int:
    token = available_github_token()
    if not token:
        return sum(recent_days.values())

    try:
        created_query = """
        query($login: String!) {
          user(login: $login) { createdAt }
        }
        """
        created_data = graphql(created_query, {"login": username}, token)
        created_at = dt.datetime.fromisoformat(
            created_data["user"]["createdAt"].replace("Z", "+00:00")
        )
        now = dt.datetime.now(dt.timezone.utc)

        total = 0
        yearly_query = """
        query($login: String!, $from: DateTime!, $to: DateTime!) {
          user(login: $login) {
            contributionsCollection(from: $from, to: $to) {
              contributionCalendar { totalContributions }
            }
          }
        }
        """

        for year in range(created_at.year, now.year + 1):
            start = max(created_at, dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc))
            end = min(now, dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc))
            if start > end:
                continue
            data = graphql(
                yearly_query,
                {
                    "login": username,
                    "from": start.isoformat().replace("+00:00", "Z"),
                    "to": end.isoformat().replace("+00:00", "Z"),
                },
                token,
            )
            total += int(
                data["user"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]
            )

        return total if total > 0 else sum(recent_days.values())
    except Exception as exc:
        print(f"Warning: all-time contribution lookup failed: {exc}")
        return sum(recent_days.values())


def month_day(date: dt.date) -> str:
    return f"{date.strftime('%b')} {date.day}"


def summarize(days: dict[dt.date, int], repo_count: int, total_contributions: int):
    today = dt.datetime.now(LOCAL_TZ).date()
    ordered_dates = sorted(date for date in days if date <= today)
    if not ordered_dates:
        raise RuntimeError("Contribution calendar has no dates up to today")

    active_dates = [date for date in ordered_dates if days[date] > 0]
    latest_activity = active_dates[-1] if active_dates else None

    if days.get(today, 0) > 0:
        anchor = today
    elif days.get(today - dt.timedelta(days=1), 0) > 0:
        anchor = today - dt.timedelta(days=1)
    else:
        anchor = None

    current_streak = 0
    streak_start = None
    if anchor is not None:
        cursor = anchor
        while days.get(cursor, 0) > 0:
            current_streak += 1
            streak_start = cursor
            cursor -= dt.timedelta(days=1)

    return {
        "total": total_contributions,
        "repositories": repo_count,
        "last_activity": (
            f"Last activity · {month_day(latest_activity)}"
            if latest_activity
            else "Last activity · unavailable"
        ),
        "current_streak": current_streak,
        "streak_range": (
            f"{month_day(streak_start)} - {month_day(anchor)}"
            if current_streak and streak_start and anchor
            else "No active streak"
        ),
    }


def render_svg(username: str, stats: dict[str, object]) -> str:
    title = html.escape(f"{username} GitHub contribution activity")
    total = stats["total"]
    repositories = stats["repositories"]
    last_activity = html.escape(str(stats["last_activity"]))
    current_streak = stats["current_streak"]
    streak_range = html.escape(str(stats["streak_range"]))

    fire_path = (
        "M 1.5 0.67 C 1.5 0.67 2.24 3.32 2.24 5.47 "
        "C 2.24 7.53 0.89 9.2 -1.17 9.2 C -3.23 9.2 -4.79 7.53 -4.79 5.47 "
        "L -4.76 5.11 C -6.78 7.51 -8 10.62 -8 13.99 C -8 18.41 -4.42 22 0 22 "
        "C 4.42 22 8 18.41 8 13.99 C 8 8.6 5.41 3.79 1.5 0.67 Z "
        "M -0.29 19 C -2.07 19 -3.51 17.6 -3.51 15.86 C -3.51 14.24 -2.46 13.1 -0.7 12.74 "
        "C 1.07 12.38 2.9 11.53 3.92 10.16 C 4.31 11.45 4.51 12.81 4.51 14.2 "
        "C 4.51 16.85 2.36 19 -0.29 19 Z"
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" role="img" aria-labelledby="title desc">
  <title id="title">{title}</title>
  <desc id="desc">Contribution total, repository count, latest activity and current streak.</desc>
  <defs>
    <clipPath id="outer"><rect width="{WIDTH}" height="{HEIGHT}" rx="8"/></clipPath>
    <mask id="ring-mask">
      <rect width="{WIDTH}" height="{HEIGHT}" fill="white"/>
      <ellipse cx="{RIGHT_X}" cy="32" rx="11" ry="15" fill="black"/>
    </mask>
  </defs>
  <g clip-path="url(#outer)">
    <rect x="0.5" y="0.5" width="759" height="189" rx="8" fill="{BACKGROUND}" stroke="{BORDER}"/>
    <line x1="253.33333333333" y1="26.75" x2="253.33333333333" y2="167.5" stroke="{BORDER}"/>
    <line x1="506.66666666667" y1="26.75" x2="506.66666666667" y2="167.5" stroke="{BORDER}"/>

    <text x="{LEFT_X}" y="77.5" text-anchor="middle" fill="{PRIMARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-weight="700" font-size="28">{total:,}</text>
    <text x="{LEFT_X}" y="127.5" text-anchor="middle" fill="{SECONDARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-size="14">Total Contributions</text>

    <text x="{CENTER_X}" y="77.5" text-anchor="middle" fill="{PRIMARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-weight="700" font-size="28">{repositories}</text>
    <text x="{CENTER_X}" y="127.5" text-anchor="middle" fill="{SECONDARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-weight="700" font-size="14">Repositories</text>
    <text x="{CENTER_X}" y="157.5" text-anchor="middle" fill="{SECONDARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-size="12">{last_activity}</text>

    <circle cx="{RIGHT_X}" cy="68.5" r="34" fill="none" stroke="{PRIMARY}" stroke-width="4" mask="url(#ring-mask)"/>
    <g transform="translate({RIGHT_X}, 19)"><path d="{fire_path}" fill="{SECONDARY}"/></g>
    <text x="{RIGHT_X}" y="77.5" text-anchor="middle" fill="{PRIMARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-weight="700" font-size="28">{current_streak}</text>
    <text x="{RIGHT_X}" y="127.5" text-anchor="middle" fill="{SECONDARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-weight="700" font-size="14">Current Streak</text>
    <text x="{RIGHT_X}" y="157.5" text-anchor="middle" fill="{MUTED}" font-family="Segoe UI, Ubuntu, sans-serif" font-size="12">{streak_range}</text>
  </g>
</svg>
'''


def main() -> None:
    username = os.getenv("GITHUB_REPOSITORY_OWNER", "devrenanfroes").strip()
    days, graphql_repo_count = fetch_recent_days(username)
    total = fetch_all_time_total(username, days)
    stats = summarize(days, repository_count(graphql_repo_count), total)
    CARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    CARD_PATH.write_text(render_svg(username, stats), encoding="utf-8")
    print(f"Updated {CARD_PATH}")


if __name__ == "__main__":
    main()
