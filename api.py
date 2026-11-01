"""Authenticated WSGI endpoint for Zapier. No trip storage or address logging."""
import hmac
import json
import os
from wsgiref.simple_server import make_server
from planner import GoogleRoutes, ProviderError, plan

MAX_BYTES = 8192

def application(environ, start_response):
    def respond(status, body):
        content = json.dumps(body).encode()
        start_response(status, [('Content-Type', 'application/json'),
                                ('Cache-Control', 'no-store'), ('Content-Length', str(len(content)))])
        return [content]
    if environ.get('PATH_INFO') == '/health' and environ.get('REQUEST_METHOD') == 'GET':
        return respond('200 OK', {'status': 'ok'})
    if environ.get('PATH_INFO') != '/plan':
        return respond('404 Not Found', {'error': 'Not found'})
    if environ.get('REQUEST_METHOD') != 'POST':
        return respond('405 Method Not Allowed', {'error': 'Use POST'})
    token = os.environ.get('PLANNER_API_TOKEN', '')
    if len(token) < 32:
        return respond('503 Service Unavailable', {'error': 'Server authentication is not configured.'})
    actual = environ.get('HTTP_AUTHORIZATION', '')
    if not hmac.compare_digest(actual.encode(), ('Bearer ' + token).encode()):
        return respond('401 Unauthorized', {'error': 'Authentication required'})
    try:
        length = int(environ.get('CONTENT_LENGTH') or '0')
        if not 0 < length <= MAX_BYTES:
            return respond('413 Payload Too Large', {'error': 'Supply a JSON body of 1–8192 bytes.'})
        if environ.get('CONTENT_TYPE', '').split(';')[0].strip() != 'application/json':
            return respond('415 Unsupported Media Type', {'error': 'Use application/json'})
        data = json.loads(environ['wsgi.input'].read(length))
        result = plan(data, GoogleRoutes())
        return respond('200 OK', result)
    except (ValueError, UnicodeError):
        return respond('400 Bad Request', {'error': 'Invalid request or missing provider configuration. Check fields and server setup.'})
    except ProviderError as exc:
        return respond('502 Bad Gateway', {'error': str(exc)})

if __name__ == '__main__':
    print('Local API: http://127.0.0.1:8000 (use a production WSGI server and HTTPS for Zapier)')
    with make_server('127.0.0.1', 8000, application) as server:
        server.serve_forever()
