import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional

import yaml
from dotenv import load_dotenv


@dataclass
class ReminderConfig:
    morning_time: str = "09:00"
    timezone: str = "Asia/Shanghai"
    tasklists: List[str] = field(default_factory=list)


@dataclass
class Config:
    app_id: str
    app_secret: str
    tasklists: List[Dict[str, str]] = field(default_factory=list)
    allowed_users: List[str] = field(default_factory=list)
    schedules: List[Dict[str, Any]] = field(default_factory=list)
    users: Dict[str, str] = field(default_factory=dict)
    log_level: str = "INFO"
    reminders: Optional[ReminderConfig] = None

    @classmethod
    def load(cls) -> "Config":
        # 1. Load .env for credentials
        load_dotenv()
        app_id = os.getenv("FEISHU_APP_ID")
        app_secret = os.getenv("FEISHU_APP_SECRET")
        log_level = os.getenv("TASKARENA_LOG_LEVEL", "INFO")

        if not app_id or not app_secret:
            raise ValueError(
                "FEISHU_APP_ID and FEISHU_APP_SECRET must be set in .env or environment variables. "
                "Run 'uv run taskarena init' first."
            )

        # 2. Load runtime config from .taskarena/config.yaml
        config_path = Path(".taskarena/config.yaml")
        tasklists = []
        allowed_users = []
        schedules = []
        reminders = None

        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                tasklists = data.get("tasklists", [])

                access = data.get("access", {})
                if isinstance(access, dict):
                    allowed_users = access.get("allowed_users", [])

                schedules = data.get("schedules", [])

                reminders_data = data.get("reminders")
                if reminders_data is not None:
                    rd = reminders_data if isinstance(reminders_data, dict) else {}
                    reminders = ReminderConfig(
                        morning_time=rd.get("morning_time", "09:00"),
                        timezone=rd.get("timezone", "Asia/Shanghai"),
                        tasklists=rd.get("tasklists", []),
                    )

        # 3. Load users cache
        users_path = Path(".taskarena/users.json")
        users = {}
        if users_path.exists():
            try:
                with open(users_path, "r", encoding="utf-8") as f:
                    users = json.load(f)
            except json.JSONDecodeError:
                pass

        return cls(
            app_id=app_id,
            app_secret=app_secret,
            tasklists=tasklists,
            allowed_users=allowed_users,
            schedules=schedules,
            users=users,
            log_level=log_level,
            reminders=reminders,
        )