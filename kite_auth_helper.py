import argparse
import os
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

CALLBACK_PORT = 8000
CALLBACK_HOST = '127.0.0.1'
CALLBACK_URL = f'http://{CALLBACK_HOST}:{CALLBACK_PORT}'
from nifty_paper.kite_auth import build_login_url, exchange_request_token, load_env, session_environment


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Capture Kite request_token and launch the paper runner with an in-memory access token.')
    parser.add_argument('--command', choices=('check', 'run'), default='check')
    parser.add_argument('--duration-minutes', type=float, default=30)
    parser.add_argument('--poll-seconds', type=float, default=1)
    parser.add_argument('--output', default='runtime/kite')
    parser.add_argument('--request-token', default='')
    return parser.parse_args(argv)


load_env()
ARGS = parse_args()

api_key = os.environ.get('KITE_API_KEY')
api_secret = os.environ.get('KITE_API_SECRET')

if not api_key:
    raise SystemExit('KITE_API_KEY missing in environment or .env')
if not api_secret:
    raise SystemExit('KITE_API_SECRET missing in environment or .env')

REQUEST = {}


def run_live_command(request_token):
    access_token = exchange_request_token(api_key, api_secret, request_token)
    child_env = session_environment(os.environ, access_token)
    child_env.pop('KITE_REQUEST_TOKEN', None)
    print('ACCESS_TOKEN_READY_IN_MEMORY')
    command = [sys.executable, 'paper.py', ARGS.command, '--source', 'kite']
    if ARGS.command == 'run':
        command.extend([
            '--duration-minutes', str(ARGS.duration_minutes),
            '--poll-seconds', str(ARGS.poll_seconds),
            '--output', ARGS.output,
        ])
    return subprocess.run(command, env=child_env, cwd=os.path.dirname(__file__), check=False)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        request_token = params.get('request_token', [None])[0]

        if not request_token:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'Missing request_token in redirect URL.')
            return

        REQUEST['request_token'] = request_token
        try:
            completed = run_live_command(request_token)
            self.send_response(200)
            self.end_headers()
            if completed.returncode == 0:
                self.wfile.write(b'Authorization complete. Live Kite command ran successfully. You can close this tab.')
            else:
                self.wfile.write(b'Authorization complete, but the live Kite command failed. Check the terminal output.')
        except Exception as exc:  # pragma: no cover - depends on live Kite auth
            print(f'KITE_AUTH_ERROR: {type(exc).__name__}: {exc}')
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'Authorization failed. Please retry the flow.')
        finally:
            self.server.auth_complete = True

    def log_message(self, format, *args):
        return


if __name__ == '__main__':
    if ARGS.request_token:
        raise SystemExit(run_live_command(ARGS.request_token).returncode)

    login_url = build_login_url(api_key, CALLBACK_URL)
    print(f'Callback URL: {CALLBACK_URL}')
    print('Opening Kite login in browser...')
    webbrowser.open(login_url, new=2)
    print('Waiting for redirect with request_token...')
    server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), Handler)
    try:
        server.auth_complete = False
        while not server.auth_complete:
            server.handle_request()
    finally:
        server.server_close()
