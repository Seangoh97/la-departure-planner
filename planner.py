"""Traffic-aware departure planning. Python 3.9+, standard library only."""
import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

LA = ZoneInfo('America/Los_Angeles')
UTC = timezone.utc

class ProviderError(Exception):
    pass

def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Times must be ISO 8601 strings with an explicit UTC offset.')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Invalid timestamp; use e.g. 2027-01-15T08:00:00-08:00.') from None
    if result.utcoffset() is None:
        raise ValueError('Include a UTC offset to avoid ambiguous daylight-saving times.')
    return result.astimezone(UTC)

def integer(data, name, default, low, high):
    value = data.get(name, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer from {low} to {high}.')
    return value

def validate(data, now):
    if not isinstance(data, dict):
        raise ValueError('Request must be a JSON object.')
    for key in ('origin', 'destination'):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 300:
            raise ValueError(f'{key} must be a nonempty address or place name, at most 300 characters.')
    start, end = timestamp(data.get('earliest_departure')), timestamp(data.get('latest_departure'))
    if start < now + timedelta(minutes=2):
        raise ValueError('Earliest departure must be at least two minutes in the future.')
    if end < start or end - start > timedelta(hours=6):
        raise ValueError('Departure window must be ordered and no longer than six hours.')
    if end > now + timedelta(days=30):
        raise ValueError('Plan no more than 30 days ahead.')
    step = integer(data, 'interval_minutes', 15, 5, 60)
    buffer = integer(data, 'buffer_minutes', 10, 0, 120)
    parking = integer(data, 'parking_minutes', 0, 0, 120)
    goal = data.get('goal', 'shortest_drive')
    if goal not in ('shortest_drive', 'earliest_arrival', 'arrive_by'):
        raise ValueError('goal must be shortest_drive, earliest_arrival, or arrive_by.')
    deadline = timestamp(data['arrival_deadline']) if data.get('arrival_deadline') else None
    if goal == 'arrive_by' and deadline is None:
        raise ValueError('arrive_by requires arrival_deadline.')
    for key in ('avoid_tolls', 'avoid_highways'):
        if key in data and type(data[key]) is not bool:
            raise ValueError(f'{key} must be a JSON boolean.')
    departures = []
    cursor = start
    while cursor <= end:
        departures.append(cursor)
        cursor += timedelta(minutes=step)
    if departures[-1] != end:
        departures.append(end)
    if len(departures) > 25:
        raise ValueError('At most 25 departure candidates; use a larger interval or shorter window.')
    return departures, goal, deadline, buffer, parking

class GoogleRoutes:
    source = 'Google Maps Routes API — traffic-aware prediction'
    demo = False
    def __init__(self, key=None):
        self.key = key or os.environ.get('GOOGLE_MAPS_API_KEY')
        if not self.key:
            raise ValueError('Set GOOGLE_MAPS_API_KEY or use the explicit offline --demo option.')

    def estimate(self, trip, departure, index):
        payload = {
            'origin': {'address': trip['origin']},
            'destination': {'address': trip['destination']},
            'travelMode': 'DRIVE', 'routingPreference': 'TRAFFIC_AWARE_OPTIMAL',
            'departureTime': departure.isoformat().replace('+00:00', 'Z'),
            'computeAlternativeRoutes': False, 'languageCode': 'en-US',
            'regionCode': 'us',
            'routeModifiers': {'avoidTolls': trip.get('avoid_tolls', False),
                               'avoidHighways': trip.get('avoid_highways', False)}
        }
        request = Request('https://routes.googleapis.com/directions/v2:computeRoutes',
            data=json.dumps(payload).encode(), headers={
                'Content-Type': 'application/json', 'X-Goog-Api-Key': self.key,
                'X-Goog-FieldMask': 'routes.duration,routes.distanceMeters,routes.description,fallbackInfo'})
        try:
            with urlopen(request, timeout=15) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise ProviderError(f'Routing provider returned HTTP {exc.code}; check API access, billing, and quota.') from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise ProviderError('Routing provider unavailable or returned invalid JSON. Try again later.') from None
        if not isinstance(result, dict) or result.get('fallbackInfo'):
            raise ProviderError('Provider could not supply the requested traffic-aware estimate.')
        routes = result.get('routes')
        if not isinstance(routes, list) or not routes or not isinstance(routes[0], dict):
            raise ProviderError('No drivable route was returned for these locations.')
        route = routes[0]
        raw = route.get('duration', '')
        if not isinstance(raw, str) or not re.fullmatch(r'\d+(?:\.\d+)?s', raw):
            raise ProviderError('Provider returned an invalid travel duration.')
        seconds = float(raw[:-1])
        if not math.isfinite(seconds) or not 0 <= seconds <= 604800:
            raise ProviderError('Provider returned an implausible travel duration.')
        return seconds, route.get('description', 'Primary driving route')

class DemoRoutes:
    source = 'SYNTHETIC DEMO — invented durations; not LA traffic observations'
    demo = True
    def estimate(self, trip, departure, index):
        return (55, 40, 32, 35, 43)[index % 5] * 60, 'Illustrative route only'

def local(value):
    return value.astimezone(LA).isoformat()

def plan(trip, provider, now=None):
    now = now or datetime.now(UTC)
    departures, goal, deadline, buffer, parking = validate(trip, now)
    candidates = []
    for index, departure in enumerate(departures):
        seconds, route = provider.estimate(trip, departure, index)
        # Keep exact seconds for decisions; rounded minutes are display-only.
        arrival = departure + timedelta(seconds=seconds, minutes=parking)
        planned = arrival + timedelta(minutes=buffer)
        candidates.append({'departure': local(departure), 'drive_minutes': round(seconds / 60, 1),
            'expected_arrival': local(arrival), 'arrival_with_buffer': local(planned),
            'meets_deadline': planned <= deadline if deadline else None, 'route': route,
            '_drive': seconds, '_arrival': arrival, '_departure': departure})
    eligible = [c for c in candidates if c['meets_deadline']] if deadline else candidates
    feasible = bool(eligible)
    pool = eligible or candidates
    if not feasible or goal == 'earliest_arrival':
        chosen = min(pool, key=lambda c: (c['_arrival'], c['_departure']))
    elif goal == 'arrive_by':
        chosen = max(pool, key=lambda c: c['_departure'])
    else:
        chosen = min(pool, key=lambda c: (c['_drive'], c['_departure']))
    reason = {'shortest_drive': 'Shortest predicted drive among the sampled feasible departures.',
              'earliest_arrival': 'Earliest predicted arrival among the sampled feasible departures.',
              'arrive_by': 'Latest sampled departure that meets the deadline including allowances.'}[goal]
    if not feasible:
        reason = 'No sampled departure meets the deadline with your allowances; earliest expected arrival shown.'
    for c in candidates:
        for key in ('_drive', '_arrival', '_departure'):
            del c[key]
    return {'status': 'ok' if feasible else 'deadline_unreachable', 'demo': provider.demo,
            'source': provider.source, 'retrieved_at': datetime.now(UTC).isoformat(),
            'timezone': 'America/Los_Angeles', 'goal': goal, 'recommendation': chosen,
            'explanation': reason, 'parking_minutes': parking, 'buffer_minutes': buffer,
            'notice': 'Estimates are not guarantees. Buffer is a user-selected allowance, not a confidence interval. Recheck before departure.',
            'candidates': candidates}

def demo_trip():
    start = (datetime.now(UTC) + timedelta(minutes=5)).replace(second=0, microsecond=0)
    return {'origin': 'Santa Monica, CA', 'destination': 'Downtown Los Angeles, CA',
            'earliest_departure': local(start), 'latest_departure': local(start + timedelta(hours=1)),
            'goal': 'shortest_drive', 'interval_minutes': 15, 'buffer_minutes': 10, 'parking_minutes': 5}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', nargs='?', help='Path to JSON trip request')
    parser.add_argument('--demo', action='store_true', help='Use clearly labeled synthetic data; no network')
    args = parser.parse_args()
    try:
        if args.request:
            with open(args.request) as handle:
                trip = json.load(handle)
        elif args.demo:
            trip = demo_trip()
        else:
            parser.error('Supply a JSON request or use --demo.')
        print(json.dumps(plan(trip, DemoRoutes() if args.demo else GoogleRoutes()), indent=2))
    except (ValueError, ProviderError, OSError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
