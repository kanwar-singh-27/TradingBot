"""Validated paper-session controls for the local dashboard."""

import json
from pathlib import Path
import subprocess
import sys

from .paths import existing_outputs, resolve_output
from .models import Config, is_public_source


class PaperSessionController:
    def __init__(self, workspace_root):
        self.workspace_root = Path(workspace_root)
        self.script = (self.workspace_root / 'paper.py').resolve()
        self.output_overrides = {}

    def output_root(self, source):
        return resolve_output(self.workspace_root, source, self.output_overrides.get(source))

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
        result = self._json_result(completed)
        alternates = []
        selected = self.output_root(source)
        for output in existing_outputs(self.workspace_root, source):
            if output == selected:
                continue
            other = self._json_result(self._run_cli([sys.executable, '-I', str(self.script), 'status', '--source', source, '--output', str(output)]))
            alternates.append({'output': str(output), 'worker_lock_held': bool(other.get('worker_lock_held')),
                               'unresolved_position': bool(other.get('state', {}).get('position'))})
        result['alternate_books'] = alternates
        result['alternate_book_blocked'] = any(book['worker_lock_held'] or book['unresolved_position'] for book in alternates)
        return result

    def start(self, source, duration_minutes, capital, diagnostic=False):
        Config(source=source, duration_minutes=duration_minutes,
             poll_seconds=60 if is_public_source(source) else 1, capital=capital, diagnostic=diagnostic)
        current = self.status(source)
        if current.get('alternate_book_blocked'):
            raise RuntimeError('An alternate journal has an active worker or unresolved position; inspect that book before starting')
        if current.get('worker_lock_held'):
            raise RuntimeError('A paper session is already active for this source')
        completed = self._run_cli(self._argv(
            'start', source,
            '--duration-minutes', str(duration_minutes),
            '--capital', str(capital),
            *(['--diagnostic'] if diagnostic else []),
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