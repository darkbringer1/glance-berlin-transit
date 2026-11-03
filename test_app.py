import unittest
from unittest.mock import patch
import datetime as dt
import app

class TransitTests(unittest.TestCase):
    def test_missing_delay_still_counts_as_observed(self):
        with patch.object(app, 'HUBS', ['one']), patch.object(app, 'fetch_json', return_value={'departures': [{'line': {'name': 'U1'}}]}):
            d = app.build()
        self.assertEqual(d['lines']['U1']['state'], 'ok')
        self.assertEqual(d['lines']['U2']['state'], 'none')
        rendered = app.render(d, False, 0, 'en', set())
        self.assertIn('without departure data', rendered)
        self.assertNotIn('All lines running normally', rendered)

    def test_partial_failure_and_html_escaping(self):
        deps = {'departures': [{'line': {'name': 'U1'}, 'remarks': [{'type': 'warning', 'summary': '<script>x</script>', 'text': 'Störung & Ausfall'}]}]}
        with patch.object(app, 'HUBS', ['one', 'two']), patch.object(app, 'fetch_json', side_effect=[deps, OSError()]):
            d = app.build()
        result = app.render(d, False, 0, 'tr', {'U1'})
        self.assertIn('1/2 durağa', result)
        self.assertIn('&lt;script&gt;', result)
        self.assertNotIn('<script>', result)
        self.assertEqual(d['lines']['U1']['state'], 'bad')

    def test_failure_keeps_cached_data(self):
        old = {'lines': {}, 'issues': []}
        with patch.object(app, '_cache', {'data': old, 'at': 1, 'failed_at': 0}), patch.object(app, 'build', side_effect=OSError()), patch.object(app.time, 'time', return_value=1000):
            value, stale, at = app.data()
        self.assertIs(value, old)
        self.assertTrue(stale)
        self.assertEqual(at, 1)

    def test_expired_remark(self):
        now = dt.datetime.now(app.TZ)
        self.assertFalse(app.remark_active({'validUntil': (now-dt.timedelta(hours=1)).isoformat()}, now))

if __name__ == '__main__':
    unittest.main()
