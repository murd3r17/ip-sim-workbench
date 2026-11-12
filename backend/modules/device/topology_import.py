"""Excel topology baseline parsing and link comparison."""
from io import BytesIO
from ipaddress import ip_address, ip_interface
import re

from openpyxl import load_workbook

from modules.device.schemas import (
    ImportedDevice,
    ImportedLink,
    ImportIssue,
    TopologyDiff,
    TopologyImportPreview,
)
from modules.device.lldp_parser import normalize_interface_name


SENSITIVE_HEADERS = {"账号", "用户名", "密码", "串口密码", "username", "password"}
DEVICE_HEADERS = {"设备名称": "hostname", "IP地址": "mgmt_ip", "备注": "notes"}
ADDRESS_RE = re.compile(
    r"^\s*\d+\s+(\S+)\s+(\S+)\s+(\S+/\d+)\s+(\S+)\s+(\S+)\s+(\S+/\d+)\s*$"
)


def _text_lines(worksheet):
    for row in worksheet.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            for line in str(cell.value).splitlines():
                line = line.strip()
                if line:
                    yield cell.row, line


def _parse_link_line(line: str):
    line = re.sub(r"^\s*\d+\.\s*", "", line)
    if "↔" not in line:
        return None
    left, right = line.split("↔", 1)
    left_parts = left.split()
    right_parts = right.split()
    if len(left_parts) != 2 or len(right_parts) != 2:
        return None
    return ImportedLink(
        source_device=left_parts[0],
        source_interface=left_parts[1],
        target_device=right_parts[0],
        target_interface=right_parts[1],
    )


class TopologyExcelParser:
    @staticmethod
    def parse(content: bytes, *, inventory_only: bool = False) -> TopologyImportPreview:
        issues: list[ImportIssue] = []
        try:
            workbook = load_workbook(BytesIO(content), data_only=True, read_only=False)
        except Exception as exc:
            return TopologyImportPreview(
                is_valid=False,
                issues=[ImportIssue(code="invalid_workbook", message=f"无法读取Excel文件: {exc}")],
            )

        if "设备信息" not in workbook.sheetnames:
            return TopologyImportPreview(
                is_valid=False,
                issues=[ImportIssue(code="missing_device_sheet", message="缺少设备信息工作表")],
            )

        worksheet = workbook["设备信息"]
        headers = {
            str(cell.value).strip(): cell.column
            for cell in worksheet[1]
            if cell.value is not None
        }
        missing_headers = [name for name in ("设备名称", "IP地址") if name not in headers]
        if missing_headers:
            return TopologyImportPreview(
                is_valid=False,
                issues=[ImportIssue(
                    code="missing_required_column",
                    message=f"缺少必填列: {', '.join(missing_headers)}",
                    row=1,
                )],
            )

        ignored = [name for name in headers if name.lower() in SENSITIVE_HEADERS]
        devices: list[ImportedDevice] = []
        seen_names: set[str] = set()
        seen_endpoints: set[tuple[str, int]] = set()
        for row_number in range(2, worksheet.max_row + 1):
            hostname = str(worksheet.cell(row_number, headers["设备名称"]).value or "").strip()
            mgmt_ip = str(worksheet.cell(row_number, headers["IP地址"]).value or "").strip()
            if not hostname and not mgmt_ip:
                continue
            if not hostname or not mgmt_ip:
                issues.append(ImportIssue(
                    code="missing_required_value",
                    message="设备名称和IP地址不能为空",
                    row=row_number,
                ))
                continue
            try:
                ip_address(mgmt_ip)
            except ValueError:
                issues.append(ImportIssue(code="invalid_management_ip", message=f"管理IP格式错误: {mgmt_ip}", row=row_number))
                continue
            if hostname in seen_names:
                issues.append(ImportIssue(code="duplicate_device", message=f"设备名称重复: {hostname}", row=row_number))
            port_column = headers.get("SSH端口") or headers.get("ssh_port")
            raw_port = worksheet.cell(row_number, port_column).value if port_column else None
            ssh_port = None
            if raw_port is not None and str(raw_port).strip():
                try:
                    if isinstance(raw_port, bool) or float(raw_port) != int(raw_port):
                        raise ValueError
                    ssh_port = int(raw_port)
                    if not 1 <= ssh_port <= 65535:
                        raise ValueError
                except (ValueError, TypeError, OverflowError):
                    issues.append(ImportIssue(code="invalid_ssh_port", message="SSH端口必须为1–65535的整数", row=row_number))
                    continue
            endpoint = (mgmt_ip, ssh_port or 22)
            if endpoint in seen_endpoints:
                issues.append(ImportIssue(code="duplicate_management_ip", message=f"管理地址与SSH端口重复: {mgmt_ip}:{endpoint[1]}", row=row_number))
            seen_names.add(hostname)
            seen_endpoints.add(endpoint)
            notes_column = headers.get("备注")
            notes = str(worksheet.cell(row_number, notes_column).value or "").strip() if notes_column else ""
            devices.append(ImportedDevice(hostname=hostname, mgmt_ip=mgmt_ip, ssh_port=ssh_port, notes=notes or None))

        links: list[ImportedLink] = []
        link_sheet = workbook["设备互联图"] if "设备互联图" in workbook.sheetnames else None
        if link_sheet:
            for row_number, line in _text_lines(link_sheet):
                link = _parse_link_line(line)
                if link:
                    links.append(link)
                elif "↔" in line:
                    issues.append(ImportIssue(
                        code="missing_interface",
                        message=f"链路端口缺失或格式错误: {line}",
                        row=row_number,
                    ))

        address_by_pair: dict[frozenset[str], tuple[str, str, str, str]] = {}
        if "Sheet1" in workbook.sheetnames:
            for row_number, line in _text_lines(workbook["Sheet1"]):
                match = ADDRESS_RE.match(line)
                if not match:
                    continue
                source_device, source_interface, source_ip, target_device, target_interface, target_ip = match.groups()
                try:
                    ip_interface(source_ip)
                    ip_interface(target_ip)
                except ValueError:
                    issues.append(ImportIssue(code="invalid_interconnect_ip", message=f"互联地址格式错误: {line}", row=row_number))
                    continue
                key = frozenset((f"{source_device}:{source_interface}", f"{target_device}:{target_interface}"))
                address_by_pair[key] = (source_device, source_ip, target_device, target_ip)

        device_names = {device.hostname for device in devices}
        deduplicated: dict[frozenset[str], ImportedLink] = {}
        for link in links:
            if not link.source_interface or not link.target_interface:
                issues.append(ImportIssue(code="missing_interface", message=f"链路端口缺失: {link.source_device} - {link.target_device}"))
                continue
            missing_devices = {link.source_device, link.target_device} - device_names
            if missing_devices:
                issues.append(ImportIssue(code="incomplete_link", message=f"链路设备不存在: {', '.join(sorted(missing_devices))}"))
                continue
            key = frozenset((
                f"{link.source_device}:{link.source_interface}",
                f"{link.target_device}:{link.target_interface}",
            ))
            address = address_by_pair.get(key)
            if address:
                source_device, source_ip, _, target_ip = address
                if source_device == link.source_device:
                    link.source_ip, link.target_ip = source_ip, target_ip
                else:
                    link.source_ip, link.target_ip = target_ip, source_ip
            deduplicated[key] = link

        if not devices:
            issues.append(ImportIssue(code="no_devices", message="未解析到设备"))
        if inventory_only and links:
            issues.append(ImportIssue(code="inventory_links_not_allowed", message="仅设备库存模式不能包含链路，请使用完整拓扑导入"))
        if not deduplicated and not inventory_only:
            issues.append(ImportIssue(code="no_links", message="未解析到互联关系"))

        return TopologyImportPreview(
            is_valid=not issues,
            inventory_only=inventory_only,
            devices=devices,
            links=list(deduplicated.values()),
            issues=issues,
            ignored_sensitive_columns=ignored,
        )


def _link_key(link) -> frozenset[str]:
    get = link.get if isinstance(link, dict) else lambda name: getattr(link, name)
    return frozenset((
        f"{get('source_device')}:{normalize_interface_name(get('source_interface'))}",
        f"{get('target_device')}:{normalize_interface_name(get('target_interface'))}",
    ))


def compare_topology_links(baseline: list, observed: list) -> TopologyDiff:
    baseline_map = {_link_key(link): link for link in baseline}
    observed_map = {_link_key(link): link for link in observed}
    return TopologyDiff(
        missing=[ImportedLink.model_validate(baseline_map[key]) for key in baseline_map.keys() - observed_map.keys()],
        unexpected=[ImportedLink.model_validate(observed_map[key]) for key in observed_map.keys() - baseline_map.keys()],
    )
