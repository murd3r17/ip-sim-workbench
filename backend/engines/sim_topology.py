"""Link and address facts for the built-in six-device practice topology."""

DEMO_LINKS = (
    ("R-1", "GE3/0/0", "R-2", "GE3/0/1"),
    ("R-2", "GE3/0/2", "R-3", "GE3/0/3"),
    ("S-1", "GE0/0/1", "S-2", "GE0/0/2"),
    ("S-2", "GE0/0/3", "S-3", "GE0/0/1"),
    ("R-2", "GE0/0/4", "S-2", "GE0/0/4"),
)
DEMO_MANAGEMENT = {
    name: f"192.168.100.{suffix}" for suffix, name in enumerate(
        ("R-1", "R-2", "R-3", "S-1", "S-2", "S-3"), 11,
    )
}
_TRANSIT = {
    ("R-1", "GE3/0/0"): "10.0.123.1/24",
    ("R-2", "GE3/0/1"): "10.0.123.2/24",
    ("R-2", "GE3/0/2"): "10.0.23.2/24",
    ("R-3", "GE3/0/3"): "10.0.23.3/24",
}
_LOOPBACK = {"R-1": "10.0.0.1", "R-2": "10.0.0.2", "R-3": "10.0.0.3"}


def links_of(hostname: str) -> list[tuple[str, str, str]]:
    links = [(local_port, peer, peer_port) for local, local_port, peer, peer_port in DEMO_LINKS if local == hostname]
    links.extend((peer_port, local, local_port) for local, local_port, peer, peer_port in DEMO_LINKS if peer == hostname)
    return links


def interfaces_of(hostname: str) -> list[tuple[str, str, str]]:
    management = ("GE0/0/0", "up", f"{DEMO_MANAGEMENT[hostname]}/24")
    transit = [(port, "up", _TRANSIT.get((hostname, port), "")) for port, _, _ in links_of(hostname)]
    loopback = [("LoopBack0", "up", f"{_LOOPBACK[hostname]}/32")] if hostname in _LOOPBACK else []
    return [management, *transit, *loopback, ("GE0/0/7", "down", "")]


def ospf_peers_of(hostname: str) -> list[tuple[str, str, str]]:
    return [
        (local_port, _LOOPBACK[peer], _TRANSIT[(peer, peer_port)].partition("/")[0])
        for local_port, peer, peer_port in links_of(hostname)
        if (hostname, local_port) in _TRANSIT and (peer, peer_port) in _TRANSIT
    ]


def router_id(hostname: str) -> str:
    return _LOOPBACK.get(hostname, DEMO_MANAGEMENT[hostname])
