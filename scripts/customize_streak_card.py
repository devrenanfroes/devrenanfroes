from __future__ import annotations

import datetime as dt
import json
import os
import re
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo


CARD_PATH = Path("profile/streak.svg")
REPOSITORY_COUNT_OVERRIDE = os.getenv("TOTAL_REPOSITORIES", "").strip()
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


def format_activity_date(value: str) -> str:
    timestamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    try:
        timezone = ZoneInfo(PROFILE_TIMEZONE)
    except Exception:
        timezone = dt.timezone(dt.timedelta(hours=-3))

    local_time = timestamp.astimezone(timezone)
    return f"Last activity · {local_time.strftime('%b')} {local_time.day}"


def fetch_profile_summary(username: str, token: str) -> tuple[str, str]:
    today = dt.date.today()
    start = today - dt.timedelta(days=370)

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        repositories(first: 1, ownerAffiliations: OWNER) {
          totalCount
        }
        contributionsCollection(from: $from, to: $to) {
          commitContributionsByRepository(maxRepositories: 100) {
            contributions(
              first: 1
              orderBy: {field: OCCURRED_AT, direction: DESC}
            ) {
              nodes {
                occurredAt
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

    repository_count = str(user["repositories"]["totalCount"])

    latest_timestamp: str | None = None
    groups = user["contributionsCollection"]["commitContributionsByRepository"]
    for group in groups:
        nodes = group.get("contributions", {}).get("nodes", [])
        if not nodes:
            continue

        occurred_at = nodes[0].get("occurredAt")
        if occurred_at and (latest_timestamp is None or occurred_at > latest_timestamp):
            latest_timestamp = occurred_at

    if latest_timestamp is None:
        last_activity = "Last activity · no recent contributions"
    else:
        last_activity = format_activity_date(latest_timestamp)

    return repository_count, last_activity


def fetch_public_fallback(username: str, token: str) -> tuple[str, str]:
    repositories = github_json(
        f"https://api.github.com/users/{username}/repos?per_page=100&type=owner",
        token=token,
    )
    repository_count = str(len(repositories)) if isinstance(repositories, list) else "—"

    events = github_json(
        f"https://api.github.com/users/{username}/events/public?per_page=1",
        token=token,
    )
    if isinstance(events, list) and events and events[0].get("created_at"):
        last_activity = format_activity_date(events[0]["created_at"])
    else:
        last_activity = "Last activity · unavailable"

    return repository_count, last_activity


def fetch_profile_data() -> tuple[str, str]:
    username = os.getenv("GITHUB_REPOSITORY_OWNER", "devrenanfroes").strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()

    try:
        repository_count, last_activity = fetch_profile_summary(username, token)
    except Exception:
        repository_count, last_activity = fetch_public_fallback(username, token)

    if REPOSITORY_COUNT_OVERRIDE:
        repository_count = REPOSITORY_COUNT_OVERRIDE

    return repository_count, last_activity


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
    repository_count, last_activity = fetch_profile_data()

    current_streak = extract_value(svg, "Current Streak big number")
    current_range = extract_value(svg, "Current Streak range")

    svg = set_marker_translate(svg, "Total Contributions label", LEFT_X, LABEL_Y)
    svg = set_marker_translate(svg, "Total Contributions range", LEFT_X, DETAIL_Y)

    svg = replace_value(svg, "Current Streak big number", repository_count)
    svg = replace_value(svg, "Current Streak label", "Repositories")
    svg = replace_value(svg, "Current Streak range", last_activity)
    svg = set_marker_translate(svg, "Current Streak label", CENTER_X, LABEL_Y)
    svg = set_marker_translate(svg, "Current Streak range", CENTER_X, DETAIL_Y)
    svg = replace_marker_block(svg, "Current Streak range", "y='21'", "y='32'")
    svg = replace_marker_block(svg, "Current Streak range", "fill='#737373'", "fill='#a3a3a3'")

    svg = svg.replace("cx='380' cy='32'", f"cx='{RIGHT_X}' cy='32'", 1)
    svg = svg.replace("cx='380' cy='68.5'", f"cx='{RIGHT_X}' cy='68.5'", 1)
    svg = svg.replace("translate(380, 17)", f"translate({RIGHT_X}, 17)", 1)

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
