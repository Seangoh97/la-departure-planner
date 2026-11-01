# Connect the planner to Zapier

## Host the API

Deploy `planner.py` and `api.py` to a Python WSGI host. Configure `GOOGLE_MAPS_API_KEY` and `PLANNER_API_TOKEN` as secrets. Generate the latter locally with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`. Use a different secret from your Google key.

For a Linux deployment, install Gunicorn and run:

```sh
python3 -m pip install gunicorn
gunicorn --bind 0.0.0.0:8000 --workers 2 --timeout 420 api:application
```

Place it behind your host's HTTPS ingress. Set ingress/body timeouts consistently. Add rate limits and concurrency limits at the gateway: a valid request can generate up to 25 billable provider calls. For a synchronous Zap, start with 3–5 candidates and verify the Zap action's timeout; larger windows may require an asynchronous job workflow. The included `python3 api.py` server binds only to localhost and is for local testing.

`GET /health` checks process availability, not Google credentials. Perform a live `POST /plan` smoke test with your own locations before launch.

## Build the Zap

1. Trigger from your trip form or supported chatbot action. Collect origin, destination, date/time window, goal, deadline if needed, and allowances. Resolve dates into offset-bearing timestamps before calling the planner. Do not rely on the Zap account timezone.
2. Use API by Zapier with a static `Authorization: Bearer YOUR_PLANNER_TOKEN` header stored in its connection, or an equivalent securely configured HTTP action.
3. Send a POST to `https://YOUR-HOST/plan`, with `Content-Type: application/json` and fields matching the README example. Numbers and booleans must retain JSON types.
4. Branch on HTTP errors and `status`. A `deadline_unreachable` response is successful computation but an unsuccessful deadline; explain that distinction.
5. Pass the returned recommendation, source, timestamp, allowances, notice, and candidates into the response template or chatbot. Never ask the language model to invent missing travel times.
6. Show Google Maps attribution and the retrieval time. Return the response through your chosen channel. Zapier Chatbots' available actions and return-to-chat behavior depend on your setup; a webhook receipt alone does not constitute a conversational response.

## Response template

“Leave at {recommendation.departure}. The predicted drive is {recommendation.drive_minutes} minutes. Expected arrival, including {parking_minutes} minutes for parking/walking, is {recommendation.expected_arrival}. With your {buffer_minutes}-minute buffer, plan for {recommendation.arrival_with_buffer}. {explanation} Traffic estimates: Google Maps. Retrieved: {retrieved_at}. Recheck before leaving.”

If `demo` is true, label the result synthetic and do not issue actual travel advice. The hosted API cannot enable demo mode; this check is additional protection for other integrations.

Do not promise monitoring or reminders unless a separate authorized Zap actually implements them. Store secrets in connection settings, not conversational fields. Check provider charges and Zap task usage with a small real test before broad rollout.
