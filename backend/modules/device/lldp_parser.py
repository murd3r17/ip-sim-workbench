"""LLDP neighbor output parser for Huawei VRP devices"""
import re
from typing import List, Dict, Optional


INTERFACE_RE = re.compile(
    r"^(?:(?:[A-Za-z-]*Ethernet|GE|XGE|FE|MEth|Eth-Trunk|\d+GE)\d+(?:/\d+)*)$",
    re.IGNORECASE,
)


def is_interface_name(name: str) -> bool:
    return bool(INTERFACE_RE.fullmatch(name.strip()))


def normalize_interface_name(name: str) -> str:
    """
    规范化接口名称，将完整名称转换为缩写格式。
    例如：GigabitEthernet3/0/0 -> GE3/0/0
         GigabitEthernet0/0/0 -> GE0/0/0
    """
    name = re.sub(r'^GigabitEthernet', 'GE', name, flags=re.IGNORECASE)
    name = re.sub(r'^XGigabitEthernet', 'XGE', name, flags=re.IGNORECASE)
    name = re.sub(r'^FastEthernet', 'FE', name, flags=re.IGNORECASE)
    return name


def parse_lldp_neighbor_brief(output: str) -> List[Dict[str, str]]:
    """
    Parse 'display lldp neighbor brief' output from Huawei VRP devices.
    
    Expected format:
    Local Intf    Neighbor Dev        Neighbor Intf    Neighbor TTL
    GE0/0/0       S-1                 GE0/0/1          120
    
    Or with more columns:
    Local Intf    Neighbor Dev        Neighbor Intf    Neighbor TTL    Exptime(s)
    """
    neighbors = []
    lines = output.strip().splitlines()
    
    # Find the header line
    header_idx = -1
    for i, line in enumerate(lines):
        if 'Local Intf' in line or 'Local' in line and 'Neighbor' in line:
            header_idx = i
            break
    
    if header_idx == -1:
        return neighbors
    
    # Parse data lines after header
    for line in lines[header_idx + 1:]:
        line = line.strip()
        if not line or line.startswith('-') or line.startswith('Total'):
            continue
        parts = line.split()
        if len(parts) >= 3 and is_interface_name(parts[0]) and is_interface_name(parts[2]):
            local_intf = normalize_interface_name(parts[0])
            neighbor_dev = parts[1]
            neighbor_intf = normalize_interface_name(parts[2])
            neighbors.append({
                "local_interface": local_intf,
                "neighbor_device": neighbor_dev,
                "remote_interface": neighbor_intf,
            })
    
    return neighbors


def classify_link_type(src_interface: str, dst_interface: str) -> str:
    """
    Classify link type based on interface names.
    management: if either endpoint is the out-of-band management port
    business: everything else

    用"接口号精确相等"而不是子串匹配：此前 `GE0/0/0` 会命中 `XGE0/0/0`、
    `GE0/0/01`、`GE0/0/0.100`，把业务链路误判为管理链路，
    而 baseline_service 又用 `link_type != management` 决定要删除哪些基线链路。
    """
    mgmt_ports = {"ge0/0/0", "meth0/0/0", "gigabitethernet0/0/0"}
    for value in (src_interface, dst_interface):
        port = (value or "").strip().upper()
        # 去掉可能的 * 前缀与空白，只比较"接口名+编号"本身
        port = port.lstrip("*").strip()
        if port.lower() in mgmt_ports:
            return "management"
    return "business"


def build_neighbor_pairs(devices_neighbors: Dict[str, List[Dict]]) -> List[Dict]:
    """
    From all devices' LLDP neighbors, build deduplicated link pairs.
    devices_neighbors: {hostname: [neighbor_dicts]}
    Returns list of unique links.
    """
    seen = set()
    links = []
    
    for src_hostname, neighbors in devices_neighbors.items():
        for nb in neighbors:
            dst_hostname = nb["neighbor_device"]
            src_if = nb["local_interface"]
            dst_if = nb["remote_interface"]
            
            # Create canonical key to deduplicate (sorted hostnames + interfaces)
            key_parts = sorted([
                f"{src_hostname}:{src_if}",
                f"{dst_hostname}:{dst_if}"
            ])
            canonical_key = "|".join(key_parts)
            
            if canonical_key in seen:
                continue
            seen.add(canonical_key)
            
            link_type = classify_link_type(src_if, dst_if)
            
            links.append({
                "src_dev": src_hostname,
                "src_if": src_if,
                "dst_dev": dst_hostname,
                "dst_if": dst_if,
                "link_type": link_type,
            })
    
    return links
