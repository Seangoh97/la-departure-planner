# LA Departure Planner

A runnable traffic-aware departure planning engine and authenticated API for Zapier workflows. Compare driving times, find the earliest arrival, or choose the latest sampled departure that meets a deadline.

**Status:** functional integration prototype. Offline tests and synthetic demo are included. Live Google routing requires your own enabled API key and billing; no live accuracy study or trained ML model is claimed.

## Try it now

Python 3.9+ with the system timezone database. No third-party packages required for the CLI. On systems without timezone data, install `tzdata`.

```sh
python3 planner.py --demo
python3 -m unittest -v test_planner
```

The demo generates future timestamps and **invented** travel durations. It makes no API calls. It is not a forecast of current Los Angeles traffic.

## Use real traffic estimates

1. Enable Google Maps Routes API and billing in your Google Cloud project.
2. Restrict the API key to the Routes API and, where supported by your deployment, your server IP. Set billing budgets and quota limits.
3. Set `GOOGLE_MAPS_API_KEY` in your environment or hosting secret manager. Never commit it.
4. Generate a request template, then edit its locations, future timestamps, and goal:

```sh
python3 -c 'import json; from planner import demo_trip; print(json.dumps(demo_trip(), indent=2))' > trip.json
python3 planner.py trip.json
```

An example request (replace the dates before use):

```json
{
  "origin": "Santa Monica Pier, Santa Monica, CA",
  "destination": "Union Station, Los Angeles, CA",
  "earliest_departure": "2027-01-15T07:00:00-08:00",
  "latest_departure": "2027-01-15T08:30:00-08:00",
  "goal": "arrive_by",
  "arrival_deadline": "2027-01-15T09:30:00-08:00",
  "interval_minutes": 15,
  "parking_minutes": 10,
  "buffer_minutes": 15,
  "avoid_tolls": false,
  "avoid_highways": false
}
```

All input times require UTC offsets. Results use `America/Los_Angeles`, including daylight saving. Include city and state in locations; the provider resolves addresses, and this application does not enforce an LA boundary. It can also handle Seattle routes with Pacific time output.

## What the result means

- `shortest_drive`: smallest driving duration among eligible candidates, breaking ties toward earlier departure.
- `earliest_arrival`: earliest arrival including parking/walking allowance.
- `arrive_by`: latest sampled departure whose predicted arrival plus parking and buffer fits the deadline.
- Any supplied deadline constrains all three goals.
- `deadline_unreachable`: no sampled candidate meets the deadline; returns the earliest expected arrival instead. Do not describe this as an on-time recommendation.
- `expected_arrival` includes parking/walking; `arrival_with_buffer` additionally includes the planning buffer.

The buffer is a user-chosen allowance, **not a statistical confidence interval**. The search samples the requested window; it does not guarantee a globally optimal minute. Each candidate costs one Google Routes request (maximum 25 per plan). A single failed provider call fails the plan rather than silently comparing incomplete estimates. Recheck near departure. Very near departures are excluded to allow processing time.

## Zapier/API

See [the integration guide](ZAPIER.md). The service exposes `POST /plan` and `GET /health`. API mode never permits synthetic demo data. Use a production WSGI server behind HTTPS and request rate limits before exposing it to Zapier. GitHub stores the source; it does not host this Python API automatically.

## Design and data

`planner.py` contains validation, the Google adapter, deterministic selection logic, and CLI. `api.py` provides a WSGI interface. `test_planner.py` covers deadline behavior, timezone ambiguity, validation, provider responses, and authentication. [The chatbot directive](CHATBOT_DIRECTIVE.md) keeps explanations grounded in computed results.

This implementation calls a routing provider; it does not train a forecasting model. METR-LA's 2012 observations are not used as current data. A future ML extension should use recent, licensed observations, chronological holdouts, and compare against a historical baseline and the provider. Evaluate travel-time error and deadline misses before claiming improvements.

## Privacy and operation

Origins/destinations are sent to Google for route calculation. The application does not persist them or return them in responses, but your host and Zapier may retain request histories; configure retention appropriately. Do not put secrets in chatbot prompts. Provider estimates are retrieved per request and no traffic archive is bundled. Follow Google's applicable attribution, display, caching, and usage terms when integrating the returned results. Add Google Maps attribution to your user-facing response.

## References

- [Google Routes REST API](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes)
- [Traffic-aware routing](https://developers.google.com/maps/documentation/routes/config_trade_offs)
- [Caltrans PeMS](https://pems.dot.ca.gov/)
- [METR-LA original research](https://arxiv.org/abs/1707.01926)
- [Zapier API options](https://help.zapier.com/hc/en-us/articles/44391646192397-Ways-to-make-API-requests-in-Zapier)

Code is provided under the MIT license. Provider services and data retain their respective terms.
