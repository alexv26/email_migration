import ipaddress
import json
import socket

from cryptography.fernet import Fernet

from webapp.config import settings

_fernet = Fernet(settings.fernet_key.encode())


class UnsafeHostError(ValueError):
    pass


def validate_public_host(hostname: str, port: int = 993) -> None:
    """Reject hostnames that resolve to a private/internal/metadata address.

    Guards against SSRF via user-supplied IMAP hosts. Resolves DNS and checks
    the resolved IP (not the hostname string) since users could otherwise
    submit a hostname that only *looks* external.
    """
    if not hostname or len(hostname) > 253:
        raise UnsafeHostError("Invalid host")

    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise UnsafeHostError("Could not resolve host") from None

    for info in infos:
        sockaddr = info[4]
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
            or str(ip) == "169.254.169.254"
        ):
            raise UnsafeHostError("Host resolves to a disallowed address")


def encrypt_payload(data: dict) -> bytes:
    return _fernet.encrypt(json.dumps(data).encode())


def decrypt_payload(token: bytes) -> dict:
    return json.loads(_fernet.decrypt(token).decode())


def scrub_secrets(text: str, secret_values) -> str:
    for value in secret_values:
        if value:
            text = text.replace(value, "[redacted]")
    return text
