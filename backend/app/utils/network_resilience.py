import socket


_TRANSIENT_PHRASES = (
    "no close frame received or sent",
    "connection aborted",
    "connection reset",
    "failed to resolve",
    "getaddrinfo failed",
    "max retries exceeded",
    "remote host",
    "remote disconnected",
)


def is_transient_network_error(exc):
    if isinstance(exc, (ConnectionError, TimeoutError, socket.gaierror, OSError)):
        return True

    message = str(exc).lower()
    return any(phrase in message for phrase in _TRANSIENT_PHRASES)


def classify_network_error(exc):
    if isinstance(exc, ConnectionResetError):
        return "connection reset by remote host"
    if isinstance(exc, ConnectionAbortedError):
        return "connection aborted"
    if isinstance(exc, socket.gaierror):
        return "dns resolution failed"

    message = " ".join(str(part).lower() for part in getattr(exc, "args", ()))
    message = f"{message} {str(exc).lower()}".strip()
    if "no close frame received or sent" in message:
        return "websocket closed unexpectedly"
    if "failed to resolve" in message or "getaddrinfo failed" in message:
        return "dns resolution failed"
    if "connection aborted" in message or "connection reset" in message:
        return "connection reset by remote host"
    if "max retries exceeded" in message:
        return "request retries exhausted"
    if "remote disconnected" in message:
        return "remote disconnected"
    return "network unavailable"


def summarize_network_error(exc):
    if is_transient_network_error(exc):
        return classify_network_error(exc)
    return str(exc)
