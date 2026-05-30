"""
Traffic logger — writes decoded Morse sessions to JSON Lines files.

One file per day: logs/2026-05-30.jsonl
Each line is a self-contained JSON object representing one message burst.

Why JSON Lines?
  - Human readable (you can just cat the file)
  - Easy to parse with any language
  - Each record is independent (no wrapping array to maintain)
  - Easy to tail -f for live monitoring
  - Home Assistant can read these directly via file sensor

Format:
  {"timestamp":"2026-05-30T14:32:11","direction":"RX",
   "text":"CQ CQ DE W4ABC","wpm":18,"tone_hz":750.1}
"""

import json
import os
from datetime import datetime
from pathlib import Path


class MorseLogger:
    """
    Accumulates decoded characters into messages, then flushes to disk.

    A "message" is a burst of characters followed by silence.
    Flushing happens:
      - When main.py calls flush() every 5 seconds
      - When silence exceeds a threshold (handled by calling flush() frequently)
    """

    def __init__(self, log_dir: str = 'logs'):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._buffer:   list  = []     # accumulated characters
        self._start_ts: datetime = None
        self._last_char: float  = None  # time.time() of last character

    # ── Called by decoder callback ─────────────────────────────

    def on_character(self, char: str):
        """Receive one decoded character."""
        import time
        now = time.time()

        if not self._buffer:
            self._start_ts = datetime.now()

        self._buffer.append(char)
        self._last_char = now

    # ── Periodic flush (called by main loop) ───────────────────

    def flush(self, direction: str = 'RX', wpm: int = 0, frequency: float = 0.0) -> dict | None:
        """
        Write accumulated buffer to disk as one log entry.
        Returns the entry dict, or None if nothing to flush.
        """
        if not self._buffer:
            return None

        import time
        # Don't flush if a character arrived in the last 2 seconds
        # (message is probably still in progress)
        if self._last_char and (time.time() - self._last_char) < 2.0:
            return None

        text = ''.join(self._buffer).strip()
        self._buffer = []

        if not text:
            return None

        entry = {
            'timestamp': self._start_ts.isoformat(timespec='seconds'),
            'direction': direction,
            'text':      text,
            'wpm':       wpm,
            'tone_hz':   round(frequency, 1),
        }

        self._write(entry)
        return entry

    def force_flush(self, direction: str = 'RX', wpm: int = 0, frequency: float = 0.0) -> dict | None:
        """Flush regardless of the 2-second cooldown. Used on shutdown."""
        self._last_char = None
        return self.flush(direction=direction, wpm=wpm, frequency=frequency)

    # ── Reading for the web UI ─────────────────────────────────

    def get_recent(self, n: int = 100) -> list:
        """Return the n most recent log entries from today's file."""
        log_file = self._log_path()
        if not log_file.exists():
            return []

        entries = []
        with open(log_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        return entries[-n:]

    def get_all_dates(self) -> list:
        """Return list of dates for which log files exist."""
        return sorted(
            p.stem for p in self.log_dir.glob('????-??-??.jsonl')
        )

    # ── Internal ───────────────────────────────────────────────

    def _log_path(self) -> Path:
        date = datetime.now().strftime('%Y-%m-%d')
        return self.log_dir / f'{date}.jsonl'

    def _write(self, entry: dict):
        with open(self._log_path(), 'a') as f:
            f.write(json.dumps(entry) + '\n')
