import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

import dns.exception
import dns.resolver


class UnsafeURL(ValueError):
    pass


def normalize_base_url(value: str) -> str:
    try:
        if any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError
        url = urlsplit(value)
        host = url.hostname
        if (
            url.scheme != "https"
            or not host
            or url.username is not None
            or url.password is not None
            or url.port not in (None, 443)
            or url.query
            or url.fragment
            or len(value) > 2048
        ):
            raise ValueError
        host = host.encode("idna").decode("ascii").lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host):
            raise ValueError
        if "." not in host or any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            for label in host.split(".")
        ):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
        # Restrict base paths instead of supporting ambiguous escaped traversal syntax.
        if not re.fullmatch(r"(?:/[a-zA-Z0-9_-]+)*/?", url.path):
            raise ValueError
        return urlunsplit(("https", host, url.path.rstrip("/"), "", ""))
    except (ValueError, UnicodeError):
        raise UnsafeURL(
            "Usar HTTPS, dominio DNS, puerto 443 y ruta base sin credenciales ni parámetros"
        ) from None


def endpoint_url(base: str) -> str:
    return normalize_base_url(base) + "/webservice/rest/server.php"


def public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    if str(address) == "168.63.129.16":  # Azure platform virtual address.
        return False
    return not (
        isinstance(address, ipaddress.IPv6Address)
        and (address.ipv4_mapped or address.sixtofour or address.teredo)
    )


def resolve_public(host: str) -> list[str]:
    addresses = []
    resolver = dns.resolver.Resolver()
    try:
        for kind in ("A", "AAAA"):
            answer = resolver.resolve(
                host, kind, lifetime=3, search=False, raise_on_no_answer=False
            )
            addresses.extend(str(record) for record in answer)
    except (dns.exception.DNSException, OSError):
        raise UnsafeURL("No se pudo resolver el destino de forma segura") from None
    if not addresses or any(not public_address(address) for address in addresses):
        raise UnsafeURL("El destino debe resolver exclusivamente a direcciones públicas permitidas")
    return sorted(
        set(addresses),
        key=lambda value: (ipaddress.ip_address(value).version, ipaddress.ip_address(value).packed),
    )
