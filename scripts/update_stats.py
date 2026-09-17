"""Refresh the profile's public repository snapshot using GitHub's REST API."""

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- github-stats:start -->"
END = "<!-- github-stats:end -->"


def fetch_repositories(username):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-stats"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    repositories = []
    page = 1
    while True:
        request = Request(
            f"https://api.github.com/users/{username}/repos?type=owner&per_page=100&page={page}",
            headers=headers,
        )
        with urlopen(request, timeout=30) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise ValueError("Unexpected GitHub API response")
        repositories.extend(batch)
        if len(batch) < 100:
            return repositories
        page += 1


def escape(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(
        ">", "&gt;"
    ).replace("|", "&#124;").replace("[", "&#91;").replace(
        "]", "&#93;"
    ).replace("\n", " ").replace("\r", " ")


def render(repositories, username, now):
    owned = [r for r in repositories if not r["fork"] and not r.get("private", False)]
    languages = Counter(r["language"] for r in owned if r.get("language"))
    # Exclude this profile so the scheduled snapshot commit cannot rank itself first.
    recent = sorted(
        [r for r in owned if r["name"].lower() != username.lower()
         and not r["archived"] and r.get("pushed_at") and r.get("size", 0) > 0],
        key=lambda r: r["pushed_at"], reverse=True,
    )[:5]
    lines = [
        START,
        f"Updated: **{now:%Y-%m-%d %H:%M UTC}** · [Update status](https://github.com/{username}/{username}/actions/workflows/update-stats.yml)",
        "",
        "| Public original repositories | Stars received | Forks received |",
        "| ---: | ---: | ---: |",
        f"| {len(owned)} | {sum(r['stargazers_count'] for r in owned)} | {sum(r['forks_count'] for r in owned)} |",
        "",
        "Public, owned, non-fork repositories only; archived repositories are included in totals.",
        "",
        "**Primary languages** (repository count, not code volume or commit share)",
        "",
        " · ".join(f"{escape(language)} **{count}**" for language, count in
                   sorted(languages.items(), key=lambda item: (-item[1], item[0]))) or "No language data available.",
        "",
        "**Recently pushed projects**",
        "",
        "| Repository | Primary language | Last push (UTC) |",
        "| --- | --- | --- |",
    ]
    for repo in recent:
        lines.append(
            f"| [{escape(repo['name'])}]({repo['html_url']}) | "
            f"{escape(repo.get('language') or 'Not detected')} | {repo['pushed_at'][:10]} |"
        )
    if not recent:
        lines.append("| No public projects available | - | - |")
    lines.extend([
        "", "Last push is a repository timestamp, not a personal contribution count.", "",
        f"[Contribution history](https://github.com/{username}?tab=overview) · "
        f"[All repositories](https://github.com/{username}?tab=repositories)",
        END,
    ])
    return "\n".join(lines)


def main():
    username = "Bamb0oChen"
    readme = ROOT / "README.md"
    original = readme.read_text(encoding="utf-8")
    if original.count(START) != 1 or original.count(END) != 1:
        raise ValueError("README must contain exactly one stats marker pair")
    start, end = original.index(START), original.index(END)
    if end < start:
        raise ValueError("Stats markers are out of order")
    snapshot = render(fetch_repositories(username), username, datetime.now(timezone.utc))
    updated = original[:start] + snapshot + original[end + len(END):]
    readme.write_text(updated, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
