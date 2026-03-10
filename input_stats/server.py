#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlparse


ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"


@dataclass(frozen=True)
class Event:
    epoch: int
    iso: str
    chars: int
    schema: str
    text: str


class EventStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._mtime_ns = -1
        self._events: list[Event] = []

    def get_events(self) -> list[Event]:
        try:
            mtime_ns = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            mtime_ns = -1

        if mtime_ns != self._mtime_ns:
            self._events = self._load_events()
            self._mtime_ns = mtime_ns

        return self._events

    def _load_events(self) -> list[Event]:
        if not self.path.exists():
            return []

        events: list[Event] = []
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                epoch_raw = (row.get("epoch") or "").strip()
                chars_raw = (row.get("chars") or "").strip()
                if not epoch_raw or not chars_raw:
                    continue

                try:
                    epoch = int(epoch_raw)
                    chars = int(chars_raw)
                except ValueError:
                    continue

                iso = (row.get("iso") or "").strip()
                if not iso:
                    iso = datetime.fromtimestamp(epoch).strftime("%Y-%m-%dT%H:%M:%S")

                events.append(
                    Event(
                        epoch=epoch,
                        iso=iso,
                        chars=max(0, chars),
                        schema=(row.get("schema") or "").strip(),
                        text=(row.get("text") or "").strip(),
                    )
                )

        events.sort(key=lambda event: event.epoch)
        return events


def unique_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for item in paths:
        expanded = item.expanduser()
        key = str(expanded)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(expanded)
    return deduped


def data_path_candidates() -> list[Path]:
    home = Path.home()
    appdata = os.getenv("APPDATA")

    candidates: list[Path] = []

    env_path = os.getenv("RIME_STATS_DATA")
    if env_path:
        candidates.append(Path(env_path))

    candidates.extend(
        [
            home / "Library" / "Rime" / "input_stats" / "events.csv",
            home / ".local" / "share" / "fcitx5" / "rime" / "input_stats" / "events.csv",
            home / ".config" / "ibus" / "rime" / "input_stats" / "events.csv",
            home / ".local" / "share" / "ibus" / "rime" / "input_stats" / "events.csv",
        ]
    )

    if appdata:
        candidates.append(Path(appdata) / "Rime" / "input_stats" / "events.csv")

    candidates.append(ROOT_DIR / "data" / "events.csv")
    return unique_paths(candidates)


def detect_data_path(explicit_path: Path | None) -> Path:
    if explicit_path is not None:
        return explicit_path.expanduser().resolve()

    candidates = data_path_candidates()
    for path in candidates:
        if path.exists():
            return path.resolve()

    home = Path.home()
    if sys.platform == "darwin":
        return (home / "Library" / "Rime" / "input_stats" / "events.csv").resolve()
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        if appdata:
            return (Path(appdata) / "Rime" / "input_stats" / "events.csv").resolve()
    return (home / ".local" / "share" / "fcitx5" / "rime" / "input_stats" / "events.csv").resolve()


def parse_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, min(parsed, maximum))


def filter_recent(events: Iterable[Event], days: int) -> list[Event]:
    if days <= 0:
        return list(events)

    cutoff = int(time.time()) - days * 86400
    return [event for event in events if event.epoch >= cutoff]


def split_sessions(events: list[Event], idle_gap_seconds: int) -> list[list[Event]]:
    if not events:
        return []

    sessions: list[list[Event]] = []
    current: list[Event] = []

    for event in events:
        if not current:
            current.append(event)
            continue

        previous = current[-1]
        if event.epoch - previous.epoch > idle_gap_seconds:
            sessions.append(current)
            current = [event]
        else:
            current.append(event)

    if current:
        sessions.append(current)

    return sessions


def summarize(events: list[Event], idle_gap_seconds: int) -> dict[str, float | int]:
    total_chars = sum(event.chars for event in events)
    total_commits = len(events)
    sessions = split_sessions(events, idle_gap_seconds)

    active_seconds = 0
    for session in sessions:
        duration = max(1, session[-1].epoch - session[0].epoch + 1)
        active_seconds += duration

    cpm = 0.0
    if active_seconds > 0:
        cpm = round(total_chars * 60.0 / active_seconds, 2)

    return {
        "total_chars": total_chars,
        "total_commits": total_commits,
        "session_count": len(sessions),
        "active_seconds": active_seconds,
        "cpm": cpm,
    }


def build_daily(events: list[Event], days: int, idle_gap_seconds: int) -> list[dict[str, int | float | str]]:
    today = datetime.now().date()
    start_day = today - timedelta(days=max(0, days - 1))

    day_buckets: dict[str, list[Event]] = {}
    for day_index in range(days):
        day = start_day + timedelta(days=day_index)
        day_buckets[day.isoformat()] = []

    for event in events:
        event_day = datetime.fromtimestamp(event.epoch).date().isoformat()
        if event_day in day_buckets:
            day_buckets[event_day].append(event)

    rows: list[dict[str, int | float | str]] = []
    for day in sorted(day_buckets.keys()):
        metrics = summarize(day_buckets[day], idle_gap_seconds)
        rows.append({"date": day, **metrics})

    return rows


def build_sessions(events: list[Event], idle_gap_seconds: int, limit: int) -> list[dict[str, int | float | str]]:
    sessions = split_sessions(events, idle_gap_seconds)
    rows: list[dict[str, int | float | str]] = []

    for session in reversed(sessions[-limit:]):
        first = session[0]
        last = session[-1]
        duration = max(1, last.epoch - first.epoch + 1)
        chars = sum(event.chars for event in session)
        cpm = round(chars * 60.0 / duration, 2)

        schemas = sorted({event.schema for event in session if event.schema})
        schema = ", ".join(schemas)

        rows.append(
            {
                "start_iso": first.iso,
                "end_iso": last.iso,
                "duration_seconds": duration,
                "chars": chars,
                "commits": len(session),
                "cpm": cpm,
                "schema": schema,
            }
        )

    return rows


def build_events(events: list[Event], limit: int) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    for event in reversed(events[-limit:]):
        rows.append(
            {
                "iso": event.iso,
                "epoch": event.epoch,
                "chars": event.chars,
                "schema": event.schema,
                "text": event.text,
            }
        )
    return rows


def build_handler(store: EventStore, default_idle_gap_seconds: int):
    class StatsHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                self.handle_api(parsed)
                return

            if parsed.path == "/":
                self.path = "/index.html"
            else:
                self.path = parsed.path
            super().do_GET()

        def handle_api(self, parsed) -> None:
            query = parse_qs(parsed.query)
            days = parse_int(query.get("days", [None])[0], default=7, minimum=1, maximum=365)
            idle_gap = parse_int(
                query.get("idle_gap", [None])[0],
                default=default_idle_gap_seconds,
                minimum=3,
                maximum=120,
            )

            all_events = store.get_events()
            scoped_events = filter_recent(all_events, days)

            if parsed.path == "/api/meta":
                payload = {
                    "data_file": str(store.path),
                    "event_count": len(all_events),
                    "idle_gap": idle_gap,
                }
                self.send_json(payload)
                return

            if parsed.path == "/api/summary":
                payload = {
                    "days": days,
                    "idle_gap": idle_gap,
                    **summarize(scoped_events, idle_gap),
                }
                self.send_json(payload)
                return

            if parsed.path == "/api/daily":
                daily_days = parse_int(query.get("days", [None])[0], default=30, minimum=1, maximum=365)
                daily_events = filter_recent(all_events, daily_days)
                payload = {
                    "days": daily_days,
                    "idle_gap": idle_gap,
                    "rows": build_daily(daily_events, daily_days, idle_gap),
                }
                self.send_json(payload)
                return

            if parsed.path == "/api/sessions":
                limit = parse_int(query.get("limit", [None])[0], default=25, minimum=1, maximum=500)
                payload = {
                    "days": days,
                    "idle_gap": idle_gap,
                    "rows": build_sessions(scoped_events, idle_gap, limit),
                }
                self.send_json(payload)
                return

            if parsed.path == "/api/events":
                limit = parse_int(query.get("limit", [None])[0], default=120, minimum=1, maximum=1000)
                payload = {
                    "days": days,
                    "rows": build_events(scoped_events, limit),
                }
                self.send_json(payload)
                return

            self.send_json({"error": "not_found"}, status=404)

        def send_json(self, payload: dict, status: int = 200) -> None:
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

    return StatsHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local Rime stats web dashboard")
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help="CSV path generated by the Rime Lua processor (auto-detected if omitted)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8765, help="Bind port")
    parser.add_argument(
        "--idle-gap",
        type=int,
        default=10,
        help="Session split gap in seconds",
    )
    args = parser.parse_args()

    data_path = detect_data_path(args.data)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    if not data_path.exists():
        data_path.write_text("epoch,iso,chars,schema,text\n", encoding="utf-8")

    store = EventStore(path=data_path)
    handler = build_handler(store=store, default_idle_gap_seconds=args.idle_gap)
    server = ThreadingHTTPServer((args.host, args.port), handler)

    print(f"Serving dashboard on http://{args.host}:{args.port}")
    print(f"Reading data from: {data_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
