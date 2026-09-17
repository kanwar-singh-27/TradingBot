"""Streamlit dashboard for the local NIFTY paper journal."""

from datetime import datetime
import json
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from .dashboard_charts import (
    equity_history_figure,
    fees_figure,
    minute_bars_figure,
    nifty_price_figure,
    realized_pnl_figure,
    trade_distribution_figure,
)
from .dashboard_control import PaperSessionController
from .dashboard_data import JournalReader
from .dashboard_view import (
    build_overview,
    completed_trades,
    explain_reason,
    format_ist,
    latest_snapshot,
    option_rows,
    position_summary,
    risk_summary,
    selection_metrics,
    timeline_rows,
)
from .models import UTC
from .paths import existing_outputs
from .replay import diagnose


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
REFRESH_CHOICES = {'Off': 0, '5s': 5000, '15s': 15000, '30s': 30000}
SOURCE_OPTIONS = ['public', 'public_loose', 'demo']
DEFAULT_VIRTUAL_CAPITALS = {
    'public': 1_000_000.0,
    'public_loose': 4_000_000.0,
    'demo': 1_000_000.0,
}


def make_reader():
    return JournalReader(WORKSPACE_ROOT)


def make_controller():
    return PaperSessionController(WORKSPACE_ROOT)


def currency(value):
    if value is None:
        return 'N/A'
    return f'INR {value:,.2f}'


def default_virtual_capital(source):
    return DEFAULT_VIRTUAL_CAPITALS.get(source, 1_000_000.0)


def age_label(seconds):
    if seconds is None:
        return 'N/A'
    if seconds < 60:
        return f'{seconds:.0f}s'
    return f'{seconds / 60:.1f}m'


def metric_card(label, value, help_text=None):
    st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>', unsafe_allow_html=True)
    if help_text:
        st.caption(help_text)


def render_header(source, latest_status):
    if source == 'public':
        source_badge = 'PUBLIC SNAPSHOT'
    elif source == 'public_loose':
        source_badge = 'PUBLIC SNAPSHOT LOOSE'
    else:
        source_badge = 'SYNTHETIC DEMO'
    running = latest_status.get('process_status', latest_status.get('status', 'UNKNOWN'))
    st.markdown(
        f'''<div class="hero">
                <div>
                    <div class="eyebrow">LOCAL DASHBOARD</div>
                    <h1>NIFTY 50 Options Paper Monitor</h1>
                    <p>Paper-only supervision for the existing detached worker. No broker route, no live orders, no manual bypass.</p>
                </div>
                <div class="hero-badges">
                    <span class="badge danger">PAPER ONLY</span>
                    <span class="badge info">{source_badge}</span>
                    <span class="badge neutral">{running}</span>
                </div>
            </div>''',
        unsafe_allow_html=True,
    )


def load_source_state(reader, controller, source):
    status = controller.status(source)
    sessions = reader.list_sessions(source, limit=50)
    latest = reader.load_latest(source)
    return status, sessions, latest


def render_controls(controller, selected_source, latest_status, all_statuses):
    st.sidebar.markdown('## Paper Session Controls')
    refresh_choice = st.sidebar.selectbox('UI refresh cadence', list(REFRESH_CHOICES), index=0)
    if REFRESH_CHOICES[refresh_choice]:
        st_autorefresh(interval=REFRESH_CHOICES[refresh_choice], key=f'autorefresh-{selected_source}')

    any_worker_active = any(item.get('worker_lock_held') or item.get('alternate_book_blocked') for item in all_statuses.values())
    last_request = st.session_state.get('last_start_request')
    if last_request and not all_statuses.get(last_request[0], {}).get('worker_lock_held'):
        st.session_state.pop('last_start_request', None)
    control_source = st.sidebar.radio('Paper source', options=SOURCE_OPTIONS, index=SOURCE_OPTIONS.index(selected_source) if selected_source in SOURCE_OPTIONS else 0, horizontal=True)
    default_minutes = 60.0 if control_source in ('public', 'public_loose') else 1.0
    with st.sidebar.form('paper-start-form'):
        duration = st.number_input('Duration minutes', min_value=0.01, max_value=375.0, value=default_minutes, step=1.0)
        capital = st.number_input('Virtual capital (INR)', min_value=1.0, max_value=1_000_000_000.0, value=default_virtual_capital(control_source), step=50_000.0, key=f'virtual-capital-{control_source}')
        diagnostic = st.checkbox('Diagnostic only — no positions', value=False)
        source_status = all_statuses[control_source]
        start_disabled = any_worker_active or source_status.get('state', {}).get('position') is not None
        start_clicked = st.form_submit_button('Start paper session', disabled=start_disabled, type='primary')
        if start_clicked:
            request_key = (control_source, duration, capital, diagnostic)
            if st.session_state.get('last_start_request') == request_key:
                st.warning('Duplicate start request blocked until status changes.')
            else:
                result = controller.start(control_source, duration_minutes=duration, capital=capital, diagnostic=diagnostic)
                st.session_state['last_start_request'] = request_key
                st.session_state['last_start_result'] = result
                st.success(f"Start requested for {control_source} session {result.get('pid', 'spawned worker')}.")

    stop_session_id = latest_status.get('id')
    stop_disabled = not (latest_status.get('worker_lock_held') and stop_session_id)
    if st.sidebar.button('Request graceful stop', disabled=stop_disabled):
        result = controller.stop(selected_source, expected_session_id=stop_session_id)
        st.session_state['last_stop_result'] = result
        st.warning(f"Stop requested for session {result.get('session_id')}.")

    cols = st.sidebar.columns(2)
    if cols[0].button('Refresh status'):
        st.session_state['manual_refresh_at'] = datetime.now(UTC).isoformat()
        st.rerun()
    if cols[1].button('Source health check'):
        result = controller.check(selected_source)
        st.session_state['last_source_check'] = result

    st.sidebar.caption('Controls invoke the fixed paper CLI with approved project directories only. Refreshing this page never starts a worker.')
    if any(item.get('alternate_book_blocked') for item in all_statuses.values()):
        st.sidebar.warning('New starts blocked: an alternate journal has an active worker or unresolved position. Select that journal to inspect it.')


def render_status_messages(latest_status):
    if 'last_start_result' in st.session_state:
        result = st.session_state['last_start_result']
        st.info(f"Start requested. Confirm running via lock/heartbeat for source {result.get('source')}.")
    if latest_status.get('stop'):
        st.warning('Stop has been requested for this session. Flat confirmation still depends on a later usable exit quote.')
    if latest_status.get('state', {}).get('status') == 'UNRESOLVED':
        st.error('This session ended with unresolved simulated exposure. The dashboard is showing last-known and conservative values separately.')
    source_check = st.session_state.get('last_source_check')
    if source_check:
        st.caption(
            f"Last explicit source check: {format_ist(source_check.get('received_at'))} | age {age_label(source_check.get('age_seconds'))} | note: {source_check.get('note')}"
        )


def render_overview(session, latest_status):
    overview = build_overview(session, now=datetime.now(UTC))
    render_status_messages(latest_status)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        metric_card('Worker liveness', latest_status.get('process_status', 'UNKNOWN'), 'Actual worker lock and heartbeat state.')
        metric_card('Stored session status', overview['status'])
        metric_card('Source observation age', age_label(overview['source_age_seconds']))
    with col2:
        metric_card('Virtual capital', currency(overview['starting_capital']))
        metric_card('Cash balance', currency(overview['cash_balance']))
        metric_card('Estimated fees paid', currency(overview['fees_paid']))
    with col3:
        metric_card('Realized P&L', currency(overview['realized_pnl']))
        metric_card('Estimated unrealized P&L', currency(overview['estimated_unrealized_pnl']))
        metric_card('Conservative equity lower bound', currency(overview['conservative_equity']))
    with col4:
        metric_card('Last-known equity', currency(overview['last_known_equity']))
        metric_card('Currently usable equity', currency(overview['usable_equity']), 'Intentionally blank when marks are stale.')
        metric_card('Entries / completed', f"{overview['entries']} / {overview['completed_trades']}")

    st.markdown('### Session State')
    left, right = st.columns(2)
    with left:
        st.write({
            'session_id': overview['session_id'],
            'source': overview['source'],
            'started_at_ist': overview['started_at_ist'],
            'planned_end_ist': overview['planned_end_ist'],
            'remaining_seconds': overview['remaining_seconds'],
            'heartbeat_age_seconds': overview['worker_heartbeat_age_seconds'],
            'valuation_status': overview['valuation_status'],
            'pending_action': overview['pending'],
            'risk_halted': overview['halted'],
        })
    with right:
        st.write({
            'source_as_of_ist': format_ist(session['state'].get('source_as_of')),
            'source_received_at_ist': format_ist(session['state'].get('source_received_at')),
            'quote_age_seconds': overview['source_age_seconds'],
            'reason': overview['reason'],
            'source_url': session['state'].get('source_url'),
            'classification': session['state'].get('classification'),
        })
    if overview['equity_history_notice']:
        st.caption(overview['equity_history_notice'])


def render_market(session):
    snapshot = latest_snapshot(session)
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(nifty_price_figure(session.get('snapshots', []), session.get('events', [])), width='stretch')
    with col2:
        st.plotly_chart(minute_bars_figure(snapshot), width='stretch')

    st.caption('A chain-wide timestamp does not prove every individual option quote is fresh.')
    if not snapshot:
        st.info('No recorded snapshots are available for this session yet.')
        return

    expiries = sorted({quote.get('expiry') for quote in snapshot.get('quotes', [])})
    filter_cols = st.columns(3)
    right_filter = filter_cols[0].selectbox('CE/PE filter', options=['All', 'CE', 'PE'])
    expiry_filter = filter_cols[1].selectbox('Expiry filter', options=['All'] + expiries)
    distance_filter = filter_cols[2].selectbox('Strike proximity', options=[100, 250, 500, 1000], index=2)
    rows = option_rows(
        snapshot,
        right=None if right_filter == 'All' else right_filter,
        expiry=None if expiry_filter == 'All' else expiry_filter,
        strike_distance=distance_filter,
    )
    if rows:
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
    else:
        st.info('No option rows matched the current filters.')


def render_timeline(session):
    rows = timeline_rows(session.get('events', []))
    if not rows:
        st.info('No recorded events for this session yet.')
        return
    table = pd.DataFrame([{k: row[k] for k in ['timestamp_ist', 'action', 'instrument', 'reason_title', 'reason_code', 'units', 'price', 'fee', 'net_pnl']} for row in rows])
    st.dataframe(table, width='stretch', hide_index=True)
    for row in rows:
        label = f"{row['timestamp_ist']} | {row['action']} | {row['reason_title']}"
        with st.expander(label):
            st.write({
                'instrument': row['instrument'],
                'trade_id': row['trade_id'],
                'reason_code': row['reason_code'],
                'reason_detail': row['reason_detail'],
                'analysis': row['analysis'],
                'raw_event': row['raw'],
            })


def render_forecast(session):
    render_diagnostics(session)
    metrics = selection_metrics(session)
    st.warning('Unvalidated, uncalibrated research baseline. These outputs do not establish an edge.')
    left, right = st.columns(2)
    with left:
        st.write({
            'model': metrics['model'],
            'forecast_horizon_minutes': metrics['horizon_minutes'],
            'expected_log_return': metrics['expected_log_return'],
            'estimated_return_variability': metrics['return_std'],
            'up_move_probability_model_only': metrics['p_up_model_only'],
        })
    with right:
        st.write({
            'iv_stress_scenario_mean_pnl': metrics['iv_stress_mean_pnl'],
            'candidate_score_after_costs_and_uncertainty': metrics['candidate_score'],
            'decision_reason': metrics['reason'],
        })
    counts = metrics['candidate_counts']
    if counts:
        st.markdown('#### Candidate Filter Summary')
        st.write({
            'quotes_seen': counts.get('total'),
            'valid_quotes': counts.get('valid'),
            'expiry_window_ok': counts.get('days_window'),
            'strike_window_ok': counts.get('strike_window'),
            'spread_ok': counts.get('spread_ok'),
            'depth_ok': counts.get('depth_ok'),
            'positive_score_candidates': counts.get('positive_score'),
        })
    if metrics['top_candidates']:
        st.markdown('#### Top Candidates By Score')
        st.dataframe(pd.DataFrame(metrics['top_candidates']), width='stretch', hide_index=True)


def render_diagnostics(session):
    st.markdown('### Decision Pipeline')
    report = session.get('diagnostics') or {}
    cache_key = f"diagnostic-replay-{session.get('output')}-{session.get('id')}"
    if not report.get('summary'):
        st.info(report.get('notice', 'This older session has no persisted candidate traces.'))
        if report.get('recorded_reasons'):
            st.write({'recorded_session_reasons': report['recorded_reasons']})
        if st.button('Replay stored snapshots (no trades)', disabled=not (session.get('output') and session.get('id'))):
            try:
                st.session_state[cache_key] = diagnose(session['output'], session['id'])
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(f'Diagnostic replay unavailable: {exc}')
        report = st.session_state.get(cache_key, report)
    summary = report.get('summary')
    if not summary:
        return
    if report.get('recorded_reasons'):
        st.write({'all_recorded_session_reasons_including_no_data': report['recorded_reasons']})
    if report.get('notice'):
        st.caption(report['notice'])
    if report.get('status') == 'OFFLINE_DIAGNOSTIC_REPLAY':
        st.warning(report['notice'])
    st.caption(summary['count_unit'])
    st.dataframe(pd.DataFrame([{'stage': key, 'candidate_observations': value} for key, value in summary['funnel'].items()]), width='stretch', hide_index=True)
    st.write({'trades_taken_in_these_evaluations': summary['trades_taken'], 'execution_outcomes': summary['actions']})
    st.info(summary['final_stage_explanation'])
    failures = [{'code': key, 'first_failure_count': value, 'all_failure_count': summary['all_failed_gates'].get(key, 0)}
                for key, value in summary['first_failed_gates'].items()]
    failures += [{'code': key, 'first_failure_count': 0, 'all_failure_count': value}
                 for key, value in summary['all_failed_gates'].items() if key not in summary['first_failed_gates']]
    st.dataframe(pd.DataFrame(failures), width='stretch', hide_index=True)
    st.markdown('#### Score and Uncertainty')
    st.json({'score_INR': summary['score_statistics'], 'unweighted_uncertainty_INR': summary['uncertainty_statistics']})
    with st.expander('Near misses — no automatic threshold changes'):
        st.json(summary['near_misses'])
    latest = report.get('latest') or {}
    candidates = latest.get('candidates') or []
    if candidates:
        selected = st.selectbox('Candidate decision trace', options=list(range(len(candidates))),
                                format_func=lambda i: f"{i+1}. {candidates[i]['instrument']} | {candidates[i]['final_decision']}")
        trace = candidates[selected]
        st.write({k: v for k, v in trace.items() if k not in ('validations', 'stages')})
        st.dataframe(pd.DataFrame([{'gate': k, **v} for k, v in trace['validations'].items()]).astype(str), width='stretch', hide_index=True)
    for limitation in latest.get('limitations', []):
        st.caption(limitation)
    st.download_button('Download diagnostic report', json.dumps(report, indent=2, allow_nan=False),
                       file_name='paper-diagnostics.json', mime='application/json')


def render_positions_and_risk(session):
    now = datetime.now(UTC)
    position = position_summary(session, now)
    risk = risk_summary(session)
    trades, notice = completed_trades(session.get('events', []))
    left, right = st.columns(2)
    with left:
        st.markdown('#### Current Position')
        if position:
            st.write(position)
        else:
            st.info('No open simulated position for this session.')
    with right:
        st.markdown('#### Risk State')
        st.write(risk)
        st.caption('A planned stop or target is not a guaranteed maximum loss. Exits still require a later usable quote.')

    st.markdown('#### Completed Simulated Trades')
    if trades:
        st.dataframe(pd.DataFrame(trades), width='stretch', hide_index=True)
    else:
        st.info(notice or 'No completed simulated trades available yet.')


def render_history(session):
    trades, notice = completed_trades(session.get('events', []))
    if notice:
        st.info(notice)
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(realized_pnl_figure(trades), width='stretch')
    with col2:
        st.plotly_chart(equity_history_figure(session.get('equity_history', [])), width='stretch')
    col3, col4 = st.columns(2)
    with col3:
        st.plotly_chart(fees_figure(session.get('equity_history', [])), width='stretch')
    with col4:
        st.plotly_chart(trade_distribution_figure(trades), width='stretch')


def apply_theme():
    st.set_page_config(page_title='NIFTY Paper Dashboard', page_icon='P', layout='wide')
    st.markdown(
        '''
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
        :root {
            --bg: #06131f;
            --panel: rgba(12, 28, 43, 0.84);
            --panel-border: rgba(133, 168, 196, 0.22);
            --text: #e9f2fb;
            --muted: #96afc4;
            --accent: #4cb3ff;
            --green: #2ecc71;
            --red: #ff6b6b;
            --amber: #f5b14c;
        }
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(76, 179, 255, 0.14), transparent 32%),
                radial-gradient(circle at 85% 0%, rgba(245, 177, 76, 0.12), transparent 28%),
                linear-gradient(180deg, #05111b 0%, #081925 100%);
            color: var(--text);
            font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif;
        }
        .hero, .metric-card {
            background: var(--panel);
            border: 1px solid var(--panel-border);
            border-radius: 18px;
            backdrop-filter: blur(10px);
        }
        .hero {
            padding: 1.25rem 1.5rem;
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 1rem;
            margin-bottom: 1rem;
        }
        .hero h1 {
            margin: 0.2rem 0 0.4rem 0;
            font-size: 2rem;
        }
        .eyebrow {
            color: var(--muted);
            font-size: 0.8rem;
            letter-spacing: 0.12em;
        }
        .hero-badges {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
        }
        .badge {
            padding: 0.45rem 0.75rem;
            border-radius: 999px;
            font-size: 0.82rem;
            font-weight: 600;
        }
        .badge.danger { background: rgba(255, 107, 107, 0.14); color: #ffd4d4; }
        .badge.info { background: rgba(76, 179, 255, 0.16); color: #d7eeff; }
        .badge.neutral { background: rgba(150, 175, 196, 0.16); color: #e3edf6; }
        .metric-card {
            padding: 0.85rem 1rem;
            min-height: 112px;
            margin-bottom: 0.85rem;
        }
        .metric-label {
            color: var(--muted);
            font-size: 0.86rem;
            margin-bottom: 0.45rem;
        }
        .metric-value {
            font-size: 1.28rem;
            font-weight: 600;
        }
        </style>
        ''',
        unsafe_allow_html=True,
    )


def main():
    apply_theme()
    reader = make_reader()
    controller = make_controller()

    overrides = {}
    needs_choice = False
    for source in SOURCE_OPTIONS:
        books = existing_outputs(WORKSPACE_ROOT, source)
        if len(books) > 1:
            st.sidebar.warning(f'Multiple {source} journals exist. They are separate books, not merged.')
            chosen = st.sidebar.selectbox(f'{source} journal', options=books, index=None, placeholder='Choose the journal to inspect', format_func=lambda p: str(p.relative_to(WORKSPACE_ROOT)))
            if chosen is None:
                needs_choice = True
            else:
                overrides[source] = chosen
    if needs_choice:
        st.info('Choose each ambiguous journal above before viewing or controlling a paper session. No books are merged or reset.')
        return
    reader.output_overrides = overrides
    controller.output_overrides = overrides

    selected_source = st.sidebar.radio('Source view', options=SOURCE_OPTIONS, horizontal=True, key='selected_source')
    try:
        all_statuses = {source: controller.status(source) for source in SOURCE_OPTIONS}
        latest_status, sessions, latest_session = load_source_state(reader, controller, selected_source)
    except Exception as exc:
        st.error(f'Unable to load local paper status: {exc}')
        return

    render_controls(controller, selected_source, latest_status, all_statuses)
    render_header(selected_source, latest_status)

    session_choices = {item['id']: f"{item['id'][:10]} | {item['state'].get('status')} | {format_ist(item['started'])}" for item in sessions}
    if not sessions:
        st.info('No paper sessions recorded yet.')
        st.caption('Use Start paper session for a public snapshot run or an explicit synthetic demo. The dashboard itself never starts one automatically.')
        return

    default_session_id = st.session_state.get('selected_session_id', latest_session.get('id'))
    selected_session_id = st.selectbox('Session', options=list(session_choices), index=max(0, list(session_choices).index(default_session_id)) if default_session_id in session_choices else 0, format_func=session_choices.get)
    st.session_state['selected_session_id'] = selected_session_id
    session = reader.load_session(selected_source, selected_session_id, event_limit=300, snapshot_limit=300)

    tabs = st.tabs(['Overview', 'Market', 'Timeline', 'Forecast', 'Positions & Risk', 'History'])
    with tabs[0]:
        render_overview(session, latest_status)
    with tabs[1]:
        render_market(session)
    with tabs[2]:
        render_timeline(session)
    with tabs[3]:
        render_forecast(session)
    with tabs[4]:
        render_positions_and_risk(session)
    with tabs[5]:
        render_history(session)