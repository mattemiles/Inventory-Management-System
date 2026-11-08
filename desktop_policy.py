"""Only the local inventory and the engine's internal document resources."""
from urllib.parse import urlsplit

def allowed_url(value, port):
    try:
        url = urlsplit(value)
        if url.scheme in ('about', 'data', 'blob', 'qrc', 'chrome-extension'):
            return True
        if url.scheme == 'chrome' and url.hostname == 'resources':
            return True  # Packaged PDF viewer controls; not an external connection.
        return (url.scheme == 'http' and url.hostname == '127.0.0.1'
                and url.port == port and not url.username and not url.password)
    except ValueError:
        return False
