"""Discover this PC's own private IPv4 addresses for local campus access."""
from ipaddress import IPv4Address, IPv4Network
import socket

PRIVATE_NETWORKS = tuple(IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def local_lan_addresses():
    try:
        addresses = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return []
    result = set()
    for value in addresses:
        try:
            address = IPv4Address(value)
        except ValueError:
            continue
        if any(address in network for network in PRIVATE_NETWORKS):
            result.add(str(address))
    return sorted(result)
