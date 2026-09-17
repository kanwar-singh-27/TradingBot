"""Plotly chart builders for the local paper dashboard."""

from datetime import datetime

import plotly.graph_objects as go

from .dashboard_view import completed_trades
from .models import IST


def empty_figure(message):
    figure = go.Figure()
    figure.update_layout(
        template='plotly_dark',
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        xaxis={'visible': False},
        yaxis={'visible': False},
        annotations=[{'text': message, 'xref': 'paper', 'yref': 'paper', 'x': 0.5, 'y': 0.5, 'showarrow': False}],
        margin={'l': 20, 'r': 20, 't': 20, 'b': 20},
    )
    return figure


def _as_datetimes(values):
    result = []
    for value in values:
        stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
        result.append(stamp.astimezone(IST) if stamp.tzinfo is not None else stamp)
    return result


def nifty_price_figure(snapshots, events):
    if not snapshots:
        return empty_figure('No recorded source snapshots for this session.')
    x = _as_datetimes([item['at'] for item in snapshots])
    y = [item['spot'] for item in snapshots]
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=x, y=y, mode='lines', name='Recorded NIFTY', line={'color': '#4cb3ff', 'width': 2}))
    trades, _ = completed_trades(events)
    observed = list(zip(x, y))

    def spot_for_trade(stamp):
        if not observed or stamp is None:
            return None
        return min(observed, key=lambda item: abs((item[0] - stamp).total_seconds()))[1]

    buys_x = [datetime.fromisoformat(item['buy_time']) for item in trades if item.get('buy_time')]
    buys_y = [spot_for_trade(stamp) for stamp in buys_x]
    sells_x = [datetime.fromisoformat(item['sell_time']) for item in trades if item.get('sell_time')]
    sells_y = [spot_for_trade(stamp) for stamp in sells_x]
    if buys_x and all(value is not None for value in buys_y):
        figure.add_trace(go.Scatter(x=buys_x, y=buys_y, mode='markers', name='Simulated buys', marker={'color': '#2ecc71', 'size': 10, 'symbol': 'triangle-up'}))
    if sells_x and all(value is not None for value in sells_y):
        figure.add_trace(go.Scatter(x=sells_x, y=sells_y, mode='markers', name='Simulated sells', marker={'color': '#ff6b6b', 'size': 10, 'symbol': 'triangle-down'}))
    figure.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin={'l': 40, 'r': 20, 't': 30, 'b': 40})
    return figure


def minute_bars_figure(snapshot):
    if not snapshot or not snapshot.get('bars'):
        return empty_figure('Completed underlying minute bars unavailable for this snapshot.')
    x = _as_datetimes([item[0] for item in snapshot['bars']])
    y = [item[1] for item in snapshot['bars']]
    figure = go.Figure(go.Scatter(x=x, y=y, mode='lines', name='Completed minute bars', line={'color': '#f5b14c', 'width': 2}))
    figure.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin={'l': 40, 'r': 20, 't': 30, 'b': 40})
    return figure


def realized_pnl_figure(trades):
    if not trades:
        return empty_figure('No completed simulated trades to chart yet.')
    cumulative = []
    running = 0.0
    for trade in trades:
        running += trade.get('net_pnl') or 0.0
        cumulative.append(running)
    x = _as_datetimes([trade['sell_time'] for trade in trades])
    figure = go.Figure(go.Scatter(x=x, y=cumulative, mode='lines+markers', name='Realized P&L', line={'color': '#2ecc71', 'width': 2}))
    figure.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin={'l': 40, 'r': 20, 't': 30, 'b': 40})
    return figure


def equity_history_figure(history):
    if not history:
        return empty_figure('Historical equity samples unavailable.')
    x = _as_datetimes([item['source_at'] or item['recorded'] for item in history])
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=x, y=[item['equity'] for item in history], mode='lines', name='Last-known equity', line={'color': '#4cb3ff', 'width': 2}))
    figure.add_trace(go.Scatter(x=x, y=[item['equity_lower_bound'] for item in history], mode='lines', name='Conservative lower bound', line={'color': '#ff6b6b', 'width': 1.5, 'dash': 'dash'}))
    figure.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin={'l': 40, 'r': 20, 't': 30, 'b': 40})
    return figure


def fees_figure(history):
    if not history:
        return empty_figure('No timestamped fee history recorded for this session.')
    x = _as_datetimes([item['source_at'] or item['recorded'] for item in history])
    y = [item['fees_paid'] for item in history]
    figure = go.Figure(go.Scatter(x=x, y=y, mode='lines', name='Estimated cumulative fees', line={'color': '#f5b14c', 'width': 2}))
    figure.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin={'l': 40, 'r': 20, 't': 30, 'b': 40})
    return figure


def trade_distribution_figure(trades):
    if len(trades) < 2:
        return empty_figure('Trade outcome distribution needs at least two completed simulated trades.')
    values = [trade.get('net_pnl') or 0.0 for trade in trades]
    figure = go.Figure(go.Histogram(x=values, nbinsx=min(12, max(4, len(values)))))
    figure.update_traces(marker_color='#4cb3ff')
    figure.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin={'l': 40, 'r': 20, 't': 30, 'b': 40})
    return figure