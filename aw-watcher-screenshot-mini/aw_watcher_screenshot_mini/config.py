import argparse


DEFAULT_INTERVAL_MINUTES = 5.0
DEFAULT_EVENT_TYPE = "os.desktop.screenshot"
DEFAULT_CLIENT_NAME = "aw-watcher-screenshot-mini"
DEFAULT_PULSE_TIME = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture screenshots periodically and enqueue ActivityWatch heartbeat events."
    )
    parser.add_argument("--host", default=None, help="aw-server host")
    parser.add_argument("--port", type=int, default=None, help="aw-server port")
    parser.add_argument(
        "--testing",
        action="store_true",
        help="Use ActivityWatch testing mode (default test server port 5666)",
    )
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=DEFAULT_INTERVAL_MINUTES,
        help="Capture interval in minutes",
    )
    parser.add_argument(
        "--output-dir",
        default="~/.local/share/activitywatch/screenshots-mini",
        help="Directory where screenshots are stored",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    args.interval_seconds = max(args.interval_minutes * 60.0, 1.0)
    return args
