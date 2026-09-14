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


def fetch_recent_from_graphql(
    username: str, token: str
) -> tuple[dict[dt.date, int], int, int]:
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(days=364)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks {
              contributionDays { date contributionCount }
            }
          }
        }
      }
      viewer {
        login
        publicRepositories: repositories(
          ownerAffiliations: [OWNER], privacy: PUBLIC, first: 1
        ) { totalCount }
        privateRepositories: repositories(
          ownerAffiliations: [OWNER], privacy: PRIVATE, first: 1
        ) { totalCount }
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
    viewer = data.get("viewer")
    if not viewer or viewer.get("login", "").casefold() != username.casefold():
        raise RuntimeError("PROFILE_TOKEN must belong to the profile owner")

    days: dict[dt.date, int] = {}
    calendar = user["contributionsCollection"]["contributionCalendar"]
    for week in calendar.get("weeks", []):
        for item in week.get("contributionDays", []):
            days[dt.date.fromisoformat(item["date"])] = int(item["contributionCount"])
    if not days:
        raise RuntimeError("GitHub GraphQL returned no contribution days")

    return (
        days,
        int(viewer.get("publicRepositories", {}).get("totalCount", 0)),
        int(viewer.get("privateRepositories", {}).get("totalCount", 0)),
    )


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
            if level_match and int(level_match.group(1)) > 0:
                raise RuntimeError("HTML calendar lacks exact contribution counts")
            count = 0
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


def fetch_public_repository_count(username: str) -> int:
    payload = json.loads(
        fetch_url(
            f"https://api.github.com/users/{username}",
            "application/vnd.github+json",
        ).decode("utf-8")
    )
    return int(payload.get("public_repos", 0))


def fetch_recent_days(username: str) -> tuple[dict[dt.date, int], int, int | None]:
    token = available_github_token()
    errors: list[str] = []
    if token:
        try:
            return fetch_recent_from_graphql(username, token)
        except Exception as exc:
            errors.append(str(exc))

    for loader in (fetch_days_from_github_html, fetch_days_from_contributions_api):
        try:
            return loader(username), fetch_public_repository_count(username), None
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError("; ".join(errors))


def repository_counts(public_count: int, private_count: int | None) -> tuple[int, int]:
    if private_count is not None:
        return public_count, private_count

    if CARD_PATH.exists():
        existing = CARD_PATH.read_text(encoding="utf-8")
        match = re.search(r">(\d+)</text>\s*<text[^>]*>Private</text>", existing)
        if match:
            print("Warning: PROFILE_PAT is unavailable; preserving the previous private count")
            return public_count, int(match.group(1))

    raise RuntimeError(
        "Unable to determine the private repository count. "
        "Ensure PROFILE_PAT is configured with access to the profile owner's repositories."
    )


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


def summarize(
    days: dict[dt.date, int],
    public_repositories: int,
    private_repositories: int,
    total_contributions: int,
):
    today = dt.datetime.now(LOCAL_TZ).date()
    ordered_dates = sorted(date for date in days if date <= today)
    if not ordered_dates:
        raise RuntimeError("Contribution calendar has no dates up to today")

    active_dates = [date for date in ordered_dates if days[date] > 0]
    latest_activity = active_dates[-1] if active_dates else None

    window_start = today - dt.timedelta(days=29)
    recent_contributions = sum(
        count for date, count in days.items() if window_start <= date <= today
    )

    return {
        "total": total_contributions,
        "public_repositories": public_repositories,
        "private_repositories": private_repositories,
        "last_activity": (
            f"Last activity · {month_day(latest_activity)}"
            if latest_activity
            else "Last activity · unavailable"
        ),
        "recent_contributions": recent_contributions,
    }


def render_svg(username: str, stats: dict[str, object]) -> str:
    title = html.escape(f"{username} GitHub contribution activity")
    total = stats["total"]
    public_repositories = stats["public_repositories"]
    private_repositories = stats["private_repositories"]
    last_activity = html.escape(str(stats["last_activity"]))
    recent_contributions = stats["recent_contributions"]

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" role="img" aria-labelledby="title desc">
  <title id="title">{title}</title>
  <desc id="desc">Contribution total, repository count, latest activity and contributions in the last 30 days.</desc>
  <defs>
    <clipPath id="outer"><rect width="{WIDTH}" height="{HEIGHT}" rx="8"/></clipPath>
  </defs>
  <g clip-path="url(#outer)">
    <rect x="0.5" y="0.5" width="759" height="189" rx="8" fill="{BACKGROUND}" stroke="{BORDER}"/>
    <line x1="253.33333333333" y1="26.75" x2="253.33333333333" y2="167.5" stroke="{BORDER}"/>
    <line x1="506.66666666667" y1="26.75" x2="506.66666666667" y2="167.5" stroke="{BORDER}"/>

    <text x="{LEFT_X}" y="77.5" text-anchor="middle" fill="{PRIMARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-weight="700" font-size="28">{total:,}</text>
    <text x="{LEFT_X}" y="127.5" text-anchor="middle" fill="{SECONDARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-size="14">Total Contributions</text>

    <line x1="{CENTER_X}" y1="42" x2="{CENTER_X}" y2="105" stroke="{BORDER}"/>
    <text x="316.66666666667" y="70" text-anchor="middle" fill="{PRIMARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-weight="700" font-size="24">{private_repositories}</text>
    <text x="316.66666666667" y="98" text-anchor="middle" fill="{SECONDARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-size="12">Private</text>
    <text x="443.33333333333" y="70" text-anchor="middle" fill="{PRIMARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-weight="700" font-size="24">{public_repositories}</text>
    <text x="443.33333333333" y="98" text-anchor="middle" fill="{SECONDARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-size="12">Public</text>
    <text x="{CENTER_X}" y="127.5" text-anchor="middle" fill="{SECONDARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-weight="700" font-size="14">Repositories</text>
    <text x="{CENTER_X}" y="157.5" text-anchor="middle" fill="{SECONDARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-size="12">{last_activity}</text>

    <text x="{RIGHT_X}" y="77.5" text-anchor="middle" fill="{PRIMARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-weight="700" font-size="28">{recent_contributions:,}</text>
    <text x="{RIGHT_X}" y="127.5" text-anchor="middle" fill="{SECONDARY}" font-family="Segoe UI, Ubuntu, sans-serif" font-weight="700" font-size="14">Recent Contributions</text>
    <text x="{RIGHT_X}" y="157.5" text-anchor="middle" fill="{MUTED}" font-family="Segoe UI, Ubuntu, sans-serif" font-size="12">Last 30 days</text>
  </g>
</svg>
'''


def main() -> None:
    username = os.getenv("GITHUB_REPOSITORY_OWNER", "devrenanfroes").strip()
    days, public_count, private_count = fetch_recent_days(username)
    public_count, private_count = repository_counts(public_count, private_count)
    total = fetch_all_time_total(username, days)
    stats = summarize(days, public_count, private_count, total)
    CARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    CARD_PATH.write_text(render_svg(username, stats), encoding="utf-8")
    print(f"Updated {CARD_PATH}")


if __name__ == "__main__":
    main()
