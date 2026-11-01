import io
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from planner import plan, timestamp, GoogleRoutes, ProviderError
from api import application

NOW = datetime(2027, 1, 1, tzinfo=timezone.utc)

def trip(**changes):
    data = dict(origin='Santa Monica, CA', destination='Los Angeles, CA',
                earliest_departure='2027-01-01T01:00:00Z', latest_departure='2027-01-01T01:30:00Z',
                interval_minutes=15, buffer_minutes=10, parking_minutes=5)
    data.update(changes)
    return data

class Fixed:
    source = 'test fixture'
    demo = True
    def estimate(self, data, departure, index):
        return [50, 40, 30][index] * 60, 'test'

class Tests(unittest.TestCase):
    def test_shortest_is_not_earliest(self):
        shortest = plan(trip(), Fixed(), NOW)['recommendation']
        earliest = plan(trip(goal='earliest_arrival'), Fixed(), NOW)['recommendation']
        self.assertEqual(shortest['drive_minutes'], 30)
        self.assertEqual(earliest['drive_minutes'], 50)

    def test_latest_feasible_accounts_for_both_allowances(self):
        result = plan(trip(goal='arrive_by', arrival_deadline='2027-01-01T02:10:00Z'), Fixed(), NOW)
        self.assertEqual(result['recommendation']['drive_minutes'], 40)

    def test_unreachable_reports_earliest(self):
        result = plan(trip(goal='arrive_by', arrival_deadline='2027-01-01T01:30:00Z'), Fixed(), NOW)
        self.assertEqual(result['status'], 'deadline_unreachable')
        self.assertEqual(result['recommendation']['drive_minutes'], 50)

    def test_deadline_also_constrains_shortest(self):
        result = plan(trip(arrival_deadline='2027-01-01T02:05:00Z'), Fixed(), NOW)
        self.assertEqual(result['recommendation']['drive_minutes'], 50)

    def test_validation(self):
        cases = [dict(interval_minutes=0), dict(buffer_minutes=True), dict(origin=''),
                 dict(avoid_tolls='false'), dict(goal='unknown'), dict(goal='arrive_by'),
                 dict(earliest_departure='2020-01-01T00:00:00Z'),
                 dict(latest_departure='2027-01-01T07:00:00Z', interval_minutes=5),
                 dict(earliest_departure='2027-01-01T01:00:00')]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                plan(trip(**case), Fixed(), NOW)

    def test_dst_offsets_are_distinct(self):
        a = timestamp('2026-11-01T01:30:00-07:00')
        b = timestamp('2026-11-01T01:30:00-08:00')
        self.assertEqual((b-a).total_seconds(), 3600)

    def test_end_of_window_is_included(self):
        class Constant(Fixed):
            def estimate(self, *args): return 600, 'test'
        result = plan(trip(latest_departure='2027-01-01T01:20:00Z'), Constant(), NOW)
        self.assertEqual(len(result['candidates']), 3)

    def test_provider_request_and_fractional_duration(self):
        response = io.BytesIO(json.dumps({'routes':[{'duration':'123.5s'}]}).encode())
        with patch('planner.urlopen', return_value=response) as mocked:
            value = GoogleRoutes('test-secret').estimate(trip(), NOW, 0)
        self.assertEqual(value[0], 123.5)
        payload = json.loads(mocked.call_args[0][0].data)
        self.assertEqual(payload['travelMode'], 'DRIVE')
        self.assertEqual(payload['routingPreference'], 'TRAFFIC_AWARE_OPTIMAL')

    def test_provider_failures_do_not_become_recommendations(self):
        for body in ({'routes':[]}, {'fallbackInfo': {'reason':'x'}},
                     {'routes':[{'duration':'NaNs'}]}):
            with patch('planner.urlopen', return_value=io.BytesIO(json.dumps(body).encode())):
                with self.assertRaises(ProviderError):
                    GoogleRoutes('test').estimate(trip(), NOW, 0)

    def call_api(self, auth='', body=b'{}', **changes):
        environ = {'PATH_INFO':'/plan', 'REQUEST_METHOD':'POST',
                   'HTTP_AUTHORIZATION':auth, 'CONTENT_TYPE':'application/json',
                   'CONTENT_LENGTH':str(len(body)), 'wsgi.input':io.BytesIO(body)}
        environ.update(changes)
        statuses = []
        response = application(environ, lambda status, headers: statuses.append(status))
        return statuses[0], json.loads(b''.join(response))

    def test_api_auth_and_limits(self):
        with patch.dict(os.environ, {'PLANNER_API_TOKEN':'x'*32}):
            self.assertEqual(self.call_api()[0], '401 Unauthorized')
            self.assertEqual(self.call_api('Bearer '+'x'*32, CONTENT_LENGTH='9000')[0], '413 Payload Too Large')
            self.assertEqual(self.call_api('Bearer '+'x'*32, b'invalid')[0], '400 Bad Request')

    def test_api_success(self):
        with patch.dict(os.environ, {'PLANNER_API_TOKEN':'x'*32}), patch('api.GoogleRoutes'), patch('api.plan', return_value={'status':'ok'}):
            self.assertEqual(self.call_api('Bearer '+'x'*32), ('200 OK', {'status':'ok'}))

if __name__ == '__main__':
    unittest.main()
