"""Import work item snapshots from a local Jira JSON file."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from workledger.config import settings
from workledger.db import DatabaseError, init_db
from workledger.services.jira_import import import_issues


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--project-key", default="RW")
    parser.add_argument("--project-name", default="RW")
    parser.add_argument("--jira-base-url", help="Base URL for browse links when the export lacks a URL")
    args = parser.parse_args()

    try:
        payload = json.loads(args.json_path.read_text(encoding="utf-8-sig"))
        issues = payload.get("data", payload)["issues"]
        if not isinstance(issues, list):
            raise TypeError("The JSON file must contain an issues array.")
        counts = import_issues(
            init_db(settings.db_path), issues, project_key=args.project_key,
            project_name=args.project_name, base_url=args.jira_base_url,
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError, DatabaseError) as exc:
        parser.exit(2, f"Jira import failed: {exc}\n")

    print(
        f"Jira import for {args.project_key}: {counts['created']} created, "
        f"{counts['updated']} refreshed, {counts['unchanged']} unchanged."
    )


if __name__ == "__main__":
    main()