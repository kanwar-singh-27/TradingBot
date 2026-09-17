from datetime import datetime, timezone
import unittest


class DashboardChartTests(unittest.TestCase):
    def test_market_charts_convert_timestamps_to_ist(self):
        from nifty_paper.dashboard_charts import minute_bars_figure, nifty_price_figure

        snapshots = [
            {'at': '2026-09-17T05:51:00+00:00', 'spot': 23249.05},
            {'at': '2026-09-17T05:57:22+00:00', 'spot': 23241.45},
        ]
        snapshot = {
            'bars': [
                ('2026-09-17T05:50:00+00:00', 23212.0),
                ('2026-09-17T05:51:00+00:00', 23249.05),
            ]
        }

        price_figure = nifty_price_figure(snapshots, [])
        bar_figure = minute_bars_figure(snapshot)

        self.assertEqual(price_figure.data[0].x[0].tzname(), 'IST')
        self.assertEqual(price_figure.data[0].x[0].hour, 11)
        self.assertEqual(price_figure.data[0].x[0].minute, 21)
        self.assertEqual(bar_figure.data[0].x[1].tzname(), 'IST')
        self.assertEqual(bar_figure.data[0].x[1].hour, 11)
        self.assertEqual(bar_figure.data[0].x[1].minute, 21)


if __name__ == '__main__':
    unittest.main()