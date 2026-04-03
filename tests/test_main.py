from taskarena.__main__ import build_parser


def test_channel_subcommand():
    args = build_parser().parse_args(["channel"])
    assert args.command == "channel"


def test_status_subcommand():
    args = build_parser().parse_args(["status"])
    assert args.command == "status"


def test_users_no_query():
    args = build_parser().parse_args(["users"])
    assert args.command == "users"
    assert args.query is None


def test_users_with_query():
    args = build_parser().parse_args(["users", "--query", "Alice"])
    assert args.query == "Alice"


def test_tasklists_no_refresh():
    args = build_parser().parse_args(["tasklists"])
    assert args.refresh is False


def test_tasklists_refresh():
    args = build_parser().parse_args(["tasklists", "--refresh"])
    assert args.refresh is True


def test_init_no_args():
    args = build_parser().parse_args(["init"])
    assert args.app_id is None
    assert args.app_secret is None


def test_init_with_args():
    args = build_parser().parse_args(["init", "--app-id", "myid", "--app-secret", "mysecret"])
    assert args.app_id == "myid"
    assert args.app_secret == "mysecret"
