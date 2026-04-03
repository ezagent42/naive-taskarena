from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from pprint import pprint

from .channel import main as channel_main
from .config import Config
from .feishu import list_tasklists, search_users
from .log import get_logger

log = get_logger("__main__")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taskarena")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("channel", help="Start the MCP channel server")

    init_parser = subparsers.add_parser("init", help="Initialize TaskArena local config")
    init_parser.add_argument("--app-id")
    init_parser.add_argument("--app-secret")

    subparsers.add_parser("status", help="Show current TaskArena configuration")

    users_parser = subparsers.add_parser("users", help="Show cached TaskArena users")
    users_parser.add_argument("--query", help="Filter cached users by substring")

    tasklists_parser = subparsers.add_parser("tasklists", help="List tasklists")
    tasklists_parser.add_argument("--refresh", action="store_true", help="Refresh tasklists from Feishu")

    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "channel":
        channel_main()
        return

    if args.command == "init":
        _cmd_init(args.app_id, args.app_secret)
        return

    if args.command == "status":
        _cmd_status()
        return

    if args.command == "users":
        _cmd_users(args.query)
        return

    if args.command == "tasklists":
        asyncio.run(_cmd_tasklists(refresh=args.refresh))
        return


def _cmd_init(app_id: str | None, app_secret: str | None) -> None:
    app_id = app_id or input("FEISHU_APP_ID: ").strip()
    app_secret = app_secret or input("FEISHU_APP_SECRET: ").strip()

    if not app_id or not app_secret:
        raise ValueError("Both FEISHU_APP_ID and FEISHU_APP_SECRET are required.")

    _write_env_file(app_id, app_secret)
    taskarena_dir = Path(".taskarena")
    taskarena_dir.mkdir(parents=True, exist_ok=True)

    users_path = taskarena_dir / "users.json"
    if not users_path.exists():
        users_path.write_text("{}\n", encoding="utf-8")

    tasklists_path = taskarena_dir / "tasklists.json"
    if not tasklists_path.exists():
        tasklists_path.write_text("[]\n", encoding="utf-8")

    config_path = taskarena_dir / "config.yaml"
    if not config_path.exists():
        config_path.write_text(
            "tasklists: []\naccess:\n  allowed_users: []\nschedules: []\n",
            encoding="utf-8",
        )

    print("TaskArena initialized.")


def _cmd_status() -> None:
    config = Config.load()
    data = {
        "tasklists": config.tasklists,
        "allowed_users": config.allowed_users,
        "schedules": config.schedules,
        "users_count": len(config.users),
        "log_level": config.log_level,
    }
    pprint(data)


def _cmd_users(query: str | None) -> None:
    config = Config.load()
    users = config.users
    if query:
        result = asyncio.run(search_users(query))
        pprint(result["users"])
        return

    pprint(
        [{"open_id": open_id, "name": name} for open_id, name in sorted(users.items(), key=lambda item: item[1])]
    )


async def _cmd_tasklists(refresh: bool) -> None:
    if refresh:
        result = await list_tasklists()
        _write_json(Path(".taskarena/tasklists.json"), result["tasklists"])
        pprint(result["tasklists"])
        return

    path = Path(".taskarena/tasklists.json")
    if path.exists():
        pprint(json.loads(path.read_text(encoding="utf-8")))
        return

    print([])


def _write_env_file(app_id: str, app_secret: str) -> None:
    env_path = Path(".env")
    lines = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                lines[key] = value

    lines["FEISHU_APP_ID"] = app_id
    lines["FEISHU_APP_SECRET"] = app_secret

    env_path.write_text(
        "\n".join(f"{key}={value}" for key, value in lines.items()) + "\n",
        encoding="utf-8",
    )
    os.environ["FEISHU_APP_ID"] = app_id
    os.environ["FEISHU_APP_SECRET"] = app_secret


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
