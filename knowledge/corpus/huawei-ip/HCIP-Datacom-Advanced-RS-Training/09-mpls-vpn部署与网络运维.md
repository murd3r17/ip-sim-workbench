---
doc_id: "hcip-datacom-advanced-rs-training-09"
title: "MPLS VPN部署与网络运维"
book: "HCIP-Datacom-Advanced-RS-Training"
book_title: "HCIP-Datacom Advanced Routing & Switching V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-advanced-rs"
doc_type: "training"
source_pdf: "HCIP-Datacom-Advanced+Routing+&+Switching+Technology+V1.0+培训教材(1).pdf"
seq: 9
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# MPLS VPN部署与网络运维

## 1. Hub-Spoke 路由发布示例

Spoke-CE1 → Spoke-CE2（PE–CE 为 OSPF 或 EBGP 的两种路径描述）：路由经 Spoke-PE → Hub-PE（VPN_in）→ Hub-CE → 再回 Hub-PE（VPN_out）→ Spoke-PE2 → Spoke-CE2。通过不同 VPN 实例的 Import/Export Target 控制 Spoke 间必须经 Hub。

## 2. OSPF VPN 扩展

同 AS 两站点互通时，通常希望对端路由为区域间而非 AS 外部。BGP 扩展团体属性携带：

- **Domain ID**：区分 OSPF 域
- **Route Type**：Area-ID + 类型（1/2 区域内，3 区域间，5 外部，7 NSSA）

```cli
# 在绑定 VRF 的 OSPF 进程下
domain-id ...
```

缺省 Domain ID 为 0（NULL）。建议同一 VPN 相关 OSPF 实例使用相同 Domain ID。

Domain ID 与本地是否相同 + RouteType → PE 生成 Type3 或 Type5/7 等不同 LSA。

### 防环

**Type3 场景：** PE 引入 OSPF 到 BGP 再发回时，可能因 IGP 优先于 IBGP 形成环路或振荡。缺省 OSPF LSA **DN 位**置 1；可用 `dn-bit-set disable` 关闭（慎用）。

**Type5/7 场景：** BGP 引入到 OSPF 再被其他 PE 学回时，AS_Path 为空可能导致优选错误。用 **VPN Route Tag**（本地概念，可 `route-tag` 配置；缺省按 BGP AS 计算）防环。

### Sham link

CE 间若有 Backdoor 直连 OSPF，学到区域内路由会优于经骨干的区域间路由。配置 **Sham link** 可使经骨干路径表现为区域内并优选，Backdoor 作备份。

同进程多条 Sham link 可共用端点；不同进程不能端点完全相同。缺省 Cost=1。

```cli
<PE1> display ospf sham-link area 0
<CE1> display ospf routing
```

### VPN 部署思考题与总结

1.（多选）PE 向 OSPF 引入 VPN 路由可能产生 Type3/5/7 等  
2.（判断）CE 通过 BGP 传给 PE 可能携带 SoO  

**总结：** Intranet/Extranet/Hub-Spoke；跨域/单域；PE–CE 可用静态/OSPF/IS-IS/BGP；OSPF 扩展含 Domain ID、DN 位、VPN Route Tag、Sham link。

---

## 3. 网络运维

日常维护是预防性计划工作；故障处理是事件驱动。良好维护习惯有助于防患未然。

### 学习目标

- 描述日常维护检查项
- 描述信息中心功能特点
- 使用常用维护工具

### 日常维护

分设备环境维护与软硬件运行维护。方法：现场观测 + 远程 `display`。

Checklist 大类：设备环境、基本信息、运行状态、接口、业务。

**环境：** 摆放、温湿度、空调、清洁、能源。

**基本信息：** 版本、补丁、License、系统时间、存储、配置是否保存、debug 开关、信息中心。

**运行状态：**

| 检查项 | 命令示例 | 关注点 |
| --- | --- | --- |
| 单板 | `display device` | Present / PowerOn |
| 复位 | `display reset-reason` 等 | 无异常复位 |
| 温度 | `display temperature` | 在上下限内 |
| 风扇 | `display fan` | Present=YES |
| 电源 | `display power` | Supply |
| CPU | `display cpu-usage` | 超 80% 重点关注 |
| 内存 | `display memory-usage` | 超约 60% 关注 |
| 日志/告警 | `display logbuffer` / `trapbuffer` | 严重告警立即处理 |
| 主备 | `display switchover state` | 主备状态正常 |

**接口：** 错包持续增加常指向链路/物理问题。

### 信息中心与工具

信息中心提供 Log、Trap、Debug，多通道控制输出方向与级别。还可配合报文捕获、流量统计、LLDP 等工具高效排障。

定期备份配置与软件版本，极端情况下用于恢复。

### 运维总结

设备环境/基本信息/运行状态检查；配置与版本备份；善用信息中心与多种信息获取工具。
