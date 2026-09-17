import os
from pathlib import Path
from urllib.parse import urlencode

try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None


def load_env(path=None):
    candidates = [Path(path)] if path else [Path.cwd() / '.env', Path(__file__).resolve().parents[1] / '.env']
    seen = set()
    for env_path in candidates:
        resolved = env_path.resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        for raw in resolved.read_text(encoding='utf-8').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = [part.strip() for part in line.split('=', 1)]
            if key and value and key not in os.environ:
                os.environ[key] = value


def build_login_url(api_key, redirect_uri):
    return 'https://kite.zerodha.com/connect/login?' + urlencode({'v': '3', 'api_key': api_key, 'redirect_uri': redirect_uri})


def exchange_request_token(api_key, api_secret, request_token, kite_class=None):
    connector = kite_class or KiteConnect
    if connector is None:
        raise RuntimeError('kiteconnect not installed; run: pip install kiteconnect')
    session = connector(api_key=api_key).generate_session(request_token, api_secret)
    access_token = session.get('access_token') or session.get('data', {}).get('access_token')
    if not access_token:
        raise RuntimeError('Kite token exchange returned no access_token')
    return access_token


def session_environment(base_env, access_token):
    env = dict(base_env)
    env['KITE_ACCESS_TOKEN'] = access_token
    env.pop('KITE_REQUEST_TOKEN', None)
    return env