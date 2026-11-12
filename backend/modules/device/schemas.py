"""设备管理模块Schema"""
from pydantic import BaseModel, ConfigDict, Field, computed_field
from typing import Optional, List, Literal
from datetime import datetime


class DeviceCreate(BaseModel):
    hostname: str
    mgmt_ip: str
    ssh_port: int = 22
    device_type: Literal["router", "switch_l2", "switch_l3", "firewall", "server", "other"] = "router"
    vendor: Literal["huawei", "h3c", "other"] = "huawei"
    model: Optional[str] = None
    vrp_version: Optional[str] = None
    topology_id: int
    network_role: str = "access"
    notes: Optional[str] = None
    tags: Optional[str] = None


class TopologyLinkCreate(BaseModel):
    source_device_id: int
    source_interface: str
    target_device_id: int
    target_interface: str
    link_type: str = "physical"
    discovery_source: str = "manual"


class TopologyLayoutPosition(BaseModel):
    x: float = Field(..., ge=0, le=1)
    y: float = Field(..., ge=0, le=1)


class TopologyLayoutUpdate(BaseModel):
    positions: dict[int, TopologyLayoutPosition]


class TopologyLayoutResponse(BaseModel):
    draft_positions: dict[str, TopologyLayoutPosition]
    published_positions: dict[str, TopologyLayoutPosition]


class DeviceUpdate(BaseModel):
    hostname: Optional[str] = None
    mgmt_ip: Optional[str] = None
    ssh_port: Optional[int] = None
    device_type: Optional[Literal["router", "switch_l2", "switch_l3", "firewall", "server", "other"]] = None
    vendor: Optional[Literal["huawei", "h3c", "other"]] = None
    model: Optional[str] = None
    vrp_version: Optional[str] = None
    network_role: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[str] = None


class DeviceResponse(BaseModel):
    id: int
    hostname: str
    mgmt_ip: str
    ssh_port: int
    device_type: str
    vendor: str
    model: Optional[str]
    vrp_version: Optional[str]
    status: str
    topology_id: int
    network_role: str
    last_seen_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TopologyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    topology_type: str = "main"
    parent_id: Optional[int] = None


class TopologyResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    topology_type: str
    device_count: int
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TopologyLinkResponse(BaseModel):
    id: int
    source_device_id: int
    source_interface: str
    target_device_id: int
    target_interface: str
    link_type: str
    status: str
    bandwidth: Optional[str] = None
    discovery_source: Optional[str] = None
    source_type: str = "baseline"
    source_ip: Optional[str] = None
    target_ip: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ImportedDevice(BaseModel):
    hostname: str
    mgmt_ip: str
    ssh_port: Optional[int] = Field(default=None, ge=1, le=65535)
    notes: Optional[str] = None


class ImportedLink(BaseModel):
    source_device: str
    source_interface: str
    target_device: str
    target_interface: str
    source_ip: Optional[str] = None
    target_ip: Optional[str] = None
    link_type: Optional[str] = None


class ImportIssue(BaseModel):
    code: str
    message: str
    row: Optional[int] = None


class TopologyImportPreview(BaseModel):
    is_valid: bool
    inventory_only: bool = False
    devices: List[ImportedDevice] = Field(default_factory=list)
    links: List[ImportedLink] = Field(default_factory=list)
    issues: List[ImportIssue] = Field(default_factory=list)
    ignored_sensitive_columns: List[str] = Field(default_factory=list)
    current_device_count: int = 0
    current_link_count: int = 0
    replaced_link_count: int = 0

    @computed_field
    @property
    def device_count(self) -> int:
        return len(self.devices)

    @computed_field
    @property
    def link_count(self) -> int:
        return len(self.links)


class TopologyDiff(BaseModel):
    missing: List[ImportedLink] = Field(default_factory=list)
    unexpected: List[ImportedLink] = Field(default_factory=list)

    @property
    def has_differences(self) -> bool:
        return bool(self.missing or self.unexpected)


class SnapshotDiffResponse(BaseModel):
    added_devices: int = 0
    removed_devices: int = 0
    changed_devices: int = 0
    added_links: int = 0
    removed_links: int = 0
    changed_links: int = 0


class TopologyImportResult(BaseModel):
    version: int
    batch_id: str
    device_count: int
    link_count: int
    source_type: str = "excel"
    diff: SnapshotDiffResponse


class RuntimeBaselineConfirmationResult(BaseModel):
    version: int
    runtime_check_id: int
    device_count: int
    link_count: int
    diff: SnapshotDiffResponse


class TopologyVersionResponse(BaseModel):
    id: int
    version: int
    batch_id: str
    source_name: str
    source_type: str
    summary: SnapshotDiffResponse
    rollback_of_version: Optional[int] = None
    created_at: datetime


class TopologyRollbackResult(BaseModel):
    version: int
    rollback_of_version: int
    diff: SnapshotDiffResponse


class RuntimeCheckResponse(BaseModel):
    check_id: int
    status: Literal["matched", "different", "partial", "no_baseline"]
    discovered: int = 0
    imported: int = 0
    ssh_success: int
    ssh_failed: int
    links: List[ImportedLink] = Field(default_factory=list)
    diff: TopologyDiff
    errors: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    compared_version_id: Optional[int] = None
    confirmed_version_id: Optional[int] = None
    current_version_id: Optional[int] = None
    is_stale: bool = False
    coverage: Optional[dict] = None
    evidence_stale: bool = True
    mode_changed: bool = False
