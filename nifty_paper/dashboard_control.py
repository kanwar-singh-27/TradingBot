"""Validated paper-session controls for the local dashboard."""

import json
from pathlib import Path
import subprocess
import sys

from .dashboard_data import SOURCE_OUTPUTS
from .models import Config, is_public_source


class PaperSessionController:
    def __init__(self, workspace_root):
        self.workspace_root = Path(workspace_root)
        self.script = (self.workspace_root / 'paper.py').resolve()

    def output_root(self, source):
        try:
            return (self.workspace_root / SOURCE_OUTPUTS[source]).resolve()
        except KeyError as exc:
            raise ValueError('Unsupported paper source') from exc

    def _run_cli(self, argv):
        return subprocess.run(argv, cwd=self.workspace_root, capture_output=True, text=True, timeout=30)

    def _argv(self, command, source, *extra):
        return [
            sys.executable,
            '-I',
            str(self.script),
            command,
            '--source',
            source,
            '--output',
            str(self.output_root(source)),
            *extra,
        ]

    def _json_result(self, completed):
        body = (completed.stdout or completed.stderr).strip()
        if not body:
            raise RuntimeError('Paper CLI returned no JSON payload')
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(body) from exc
        if completed.returncode != 0:
            raise RuntimeError(payload.get('error', payload.get('status', body)))
        return payload

    def status(self, source):
        completed = self._run_cli(self._argv('status', source))
        return self._json_result(completed)

    def start(self, source, duration_minutes, capital):
        Config(source=source, duration_minutes=duration_minutes,
             poll_seconds=60 if is_public_source(source) else 1, capital=capital)
        current = self.status(source)
        if current.get('worker_lock_held'):
            raise RuntimeError('A paper session is already active for this source')
        completed = self._run_cli(self._argv(
            'start', source,
            '--duration-minutes', str(duration_minutes),
            '--capital', str(capital),
        ))
        return self._json_result(completed)

    def stop(self, source, expected_session_id):
        current = self.status(source)
        if current.get('id') != expected_session_id:
            raise RuntimeError('Refusing stop request for a different session than the one selected in the dashboard')
        if not current.get('worker_lock_held'):
            raise RuntimeError('No active paper worker is holding this source journal')
        completed = self._run_cli(self._argv('stop', source))
        return self._json_result(completed)

    def check(self, source):
        completed = self._run_cli(self._argv('check', source))
        return self._json_result(completed)