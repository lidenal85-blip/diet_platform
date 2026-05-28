"""SSRF Protection: валидация URL перед HTTP-запросом."""
import ipaddress
import socket
from urllib.parse import urlparse
from building_blocks.logger import get_logger

log = get_logger(__name__)

# RFC1918 + link-local + loopback + cloud metadata
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # cloud metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_ALLOWED_SCHEMES = {"http", "https"}


def validate_url_for_ssrf(url: str) -> tuple[bool, str]:
    """
    Returns (is_safe, reason).
    Проверяет URL перед отправкой HTTP-запроса.
    Аудит: ContentFetchFailed(reason=SECURITY_VIOLATION) если небезопасно.
    """
    try:
        parsed = urlparse(url)

        if parsed.scheme not in _ALLOWED_SCHEMES:
            return False, f"Scheme not allowed: {parsed.scheme}"

        hostname = parsed.hostname
        if not hostname:
            return False, "Empty hostname"

        # Резолвим IP
        try:
            ip_str = socket.gethostbyname(hostname)
        except socket.gaierror as e:
            return False, f"DNS resolution failed: {e}"

        ip = ipaddress.ip_address(ip_str)

        for blocked_net in _BLOCKED_NETWORKS:
            if ip in blocked_net:
                log.warning(
                    "SSRF blocked: %s resolved to %s (%s)",
                    hostname, ip_str, blocked_net
                )
                return False, f"IP {ip_str} is in blocked network {blocked_net}"

        return True, "ok"

    except Exception as e:
        return False, f"Validation error: {e}"