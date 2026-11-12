# -*- coding: utf-8 -*-
"""V7-B 可信基础 API 模型。"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class EnvironmentDevice(BaseModel):
    device_id: int
    role: str = ""
    mgmt_ip: str = ""
    vendor: str = ""
    os_version: str = ""
    interfaces: list[dict[str, Any]] = Field(default_factory=list)
    # Per-role task facts; global expectations are ambiguous in multi-device labs.
    expected_neighbors: Optional[list[str]] = None
    expected_routes: Optional[list[str]] = None


class EnvironmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    version: str = Field("v1", max_length=32)
    site: str = Field("", max_length=128)
    devices: list[EnvironmentDevice] = Field(default_factory=list)
    protections: list[dict[str, Any]] = Field(default_factory=list)
    expected_neighbors: list[str] = Field(default_factory=list)
    expected_routes: list[str] = Field(default_factory=list)


class EnvironmentUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=128)
    version: Optional[str] = Field(None, max_length=32)
    site: Optional[str] = Field(None, max_length=128)
    status: Optional[str] = Field(None, pattern="^(draft|ready|mismatch|unreachable|busy|unknown)$")
    devices: Optional[list[EnvironmentDevice]] = None
    protections: Optional[list[dict[str, Any]]] = None
    expected_neighbors: Optional[list[str]] = None
    expected_routes: Optional[list[str]] = None


class EnvironmentResponse(BaseModel):
    id: int
    name: str
    version: str
    site: str
    status: str
    devices: list[dict[str, Any]]
    protections: list[dict[str, Any]]
    expected_neighbors: list[str] = Field(default_factory=list)
    expected_routes: list[str] = Field(default_factory=list)
    source: str
    revision: int = 1
    content_hash: str = ""
    last_preflight_status: str = ""
    last_preflight_mode: str = ""
    last_preflight_at: str = ""
    updated_at: str


class PreflightRequest(BaseModel):
    device_id: Optional[int] = None


class PreflightResponse(BaseModel):
    environment_id: int
    version: str
    status: str
    checks: list[dict[str, Any]]
    checked_at: str
    verification_mode: str = "unknown"
    real_device_verified: bool = False
    environment_revision: int = 1


class ObservationCreate(BaseModel):
    device_id: int
    action_id: str = Field(..., min_length=1, max_length=64)
    environment_id: Optional[int] = None


class ObservationResponse(BaseModel):
    id: int
    environment_id: Optional[int]
    environment_version: str = ""
    environment_snapshot: dict[str, Any] = Field(default_factory=dict)
    device_id: int
    action_id: str
    command: str
    collected_at: str
    source: str
    mode: str
    adapter_mode: str = "unknown"
    completeness: str
    parser_version: str
    facts: dict[str, Any]
    raw_excerpt: str = ""
    status: str
    error_message: str


class OspfRuleRequest(BaseModel):
    observation_id: Optional[int] = None
    observation_ids: list[int] = Field(default_factory=list)
    device_id: Optional[int] = None
    environment_id: Optional[int] = None
    expected_neighbors: list[str] = Field(default_factory=list)
    expected_routes: list[str] = Field(default_factory=list)
    max_age_seconds: int = Field(300, ge=1, le=86400)
    allow_simulated: bool = False


class RuleResponse(BaseModel):
    status: str
    reason: str
    expected: dict[str, Any]
    observed: dict[str, Any]
    missing: list[str]
    unexpected: list[str]
    evidence_ids: list[int]
    checked_at: str
    verification_mode: str = "unknown"
    evidence_versions: list[dict[str, Any]] = Field(default_factory=list)
    expected_source: str = "unknown"
    evaluation_scope: str = "official"
    target_version: str = ""
    rejected_reason: str = ""
