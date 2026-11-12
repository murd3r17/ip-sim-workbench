---
doc_id: "hcip-datacom-advanced-rs-training-07"
title: "静态LSP与LDP原理配置"
book: "HCIP-Datacom-Advanced-RS-Training"
book_title: "HCIP-Datacom Advanced Routing & Switching V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-advanced-rs"
doc_type: "training"
source_pdf: "HCIP-Datacom-Advanced+Routing+&+Switching+Technology+V1.0+培训教材(1).pdf"
seq: 7
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# 静态LSP与LDP原理配置

## 1. 静态 LSP 配置案例（续）

```cli
[R1] static-lsp ingress 1to3 destination 3.3.3.0 24 nexthop 10.0.12.2 out-label 200
[R2] static-lsp transit 1to3 incoming-interface GigabitEthernet 0/0/0 in-label 200 nexthop 10.0.23.3 out-label 300
[R3] static-lsp egress 1to3 incoming-interface GigabitEthernet 0/0/0 in-label 300
```

检查：

```cli
[R1] display mpls lsp
[R2] display mpls lsp
[R3] display mpls lsp
```

可见 STATIC LSP：R1 `NULL/200`，R2 `200/300`，R3 `300/NULL`。单向静态 LSP 下 ping 双向仍可能通：去程带标签，回程可走 IP（抓包可见）。

### MPLS 思考题与总结

1.（多选）MPLS 头部 32 bit；可多层嵌套等  
2.（单选）Transit 静态 LSP 入/出标签取值均为 16～1023？→ 错误（出标签可用更大空间）

**总结：** MPLS 用本地意义标签标识 FEC；Push/Swap/Pop；控制面分发标签，数据面转发；VPN 等场景仍广泛使用。

---

## 2. LDP 原理与配置前言

本课程 LDP 特指 RFC3036/5036 定义的标签分发协议。其他如 MP-BGP、RSVP 也可分发标签。

### 学习目标

- 描述 LDP 概念与工作机制
- 描述标签分发控制/通告/保留模式
- 实现 LDP 基础配置

### 课程内容

1. LDP 基本概念  
2. LDP 工作原理  
3. LDP 基本配置  

## 3. LDP 基本概念

LDP 负责 FEC 分类、标签分配及 LSP 建立维护。过程：建立会话 → 交换标签-FEC 映射并建 LSP。

- **本地会话**：LSR 直连；**远程会话**：可非直连
- Hello 后建邻接；会话消息后成对等体
- **LDP ID**：LSR ID（32）+ Label Space ID（16），如 `2.2.2.2:0`；0 表示平台标签空间

消息类型：发现（UDP/646，如 Hello）、会话/通告/通知（TCP/646）。PDU 含 Version、PDU Length、LDP Identifier；消息含 U 位、Type、ID、参数等。

## 4. LDP 会话建立

状态机：Non-Existent → Initialized → OpenSent / OpenRec → Operational。传输地址较大方为主动方发 Initialization。缺省公网传输地址 = LSR ID。

查看：`display mpls ldp peer`；会话状态可用 debug/显示命令观察。

## 5. 标签发布与管理

下游决定绑定并发布给上游。由三种方式组合决定：

| 维度 | 模式 | 缺省 | 含义 |
| --- | --- | --- | --- |
| 发布 | DU | 是 | 无需请求即分配分发 |
| 发布 | DoD | 否 | 收到请求才分配分发 |
| 控制 | Independent | 否 | 无需下游标签即可向上游通告 |
| 控制 | Ordered | 是 | 有下游映射或自己是出口才向上游发 |
| 保持 | Liberal | 是 | 保留所有邻居映射 |
| 保持 | Conservative | 否 | 只保留下一跳邻居映射 |

华为缺省：**DU + Ordered + Liberal**。

PHP：Egress 默认向次末跳分配隐式空标签 3；QoS 场景可用显式空 0：

```cli
[Huawei-mpls] label advertise { explicit-null | implicit-null | non-null }
```

工作过程：IGP 建路由 → LDP 为 FEC 分配并通告 → 形成 LFIB → 转发时出标签为下游（路由下一跳）通告的标签。缺省按 32 位主机路由触发 LSP；非 32 位需 `lsp-trigger`。

## 6. LDP 基本配置

```cli
[Huawei] mpls ldp
[Huawei-GigabitEthernet0/0/0] mpls ldp
[Huawei] mpls ldp remote-peer remote-peer-name
[Huawei-mpls-ldp-remote-PeerName] remote-ip ip-address
[Huawei-mpls-ldp] label distribution control-mode { independent | ordered }
```

### 配置案例

R1–R4 已通 IGP；配置 MPLS/LDP 使 192.168.1.0/24 与 192.168.4.0/24 标签互通。

```cli
[R1] mpls
[R1-mpls] quit
[R1] mpls ldp
[R1-mpls-ldp] quit
[R1] interface GigabitEthernet 0/0/0
[R1-GigabitEthernet0/0/0] mpls
[R1-GigabitEthernet0/0/0] mpls ldp
[R1] ip ip-prefix ldp permit 192.168.1.0 24
[R1-mpls] lsp-trigger ip-prefix ldp
```

R4 对 192.168.4.0/24 同样触发。查看：`display mpls ldp lsp`。

### LDP 思考题与总结

1. 查看已为 FEC 分配的标签：相关 display 命令辨析  
2. 华为默认组合：DU + Ordered + Liberal  

**总结：** LDP 用四类消息建会话与分标签；三种模式决定发布管理；将路由映射为标签从而建立 LSP。

---

## 7. MPLS VPN 原理前言（开篇）

除非特别指出，MPLS VPN 即 BGP/MPLS IP VPN。骨干也可由企业自建，本课程主要讨论运营商服务场景。

### 学习目标

- 描述模型、基本概念、路由传递与标签分发、数据转发
- 执行基本配置

### 角色

- **CE**：用户边缘，可不感知 VPN、不必支持 MPLS
- **PE**：运营商边缘，VPN 处理集中点
- **P**：骨干，只做基本 MPLS 转发，不维护 VPN 信息
- **站点**：无需经运营商即可 IP 互通的一组系统；按拓扑非地理位置划分；一站点可属多 VPN

Intranet 为最典型组网。路由发布三段：本地 CE→入口 PE；入口 PE→出口 PE；出口 PE→远端 CE。P 不需 VPN 路由。

CE–PE 可用静态/OSPF/IS-IS/BGP，交换标准 IPv4 路由。不同 VPN 地址空间可重叠（无共同站点，或共同站点不与重叠地址设备互访）。

RD 构成 VPNv4 地址（RD + IPv4 前缀），常用 `AS:nn` 或 `IPv4:nn`，需全局唯一。PE 间用 MP-BGP 传 VPNv4；用 RT（Import/Export）控制导入实例。私网标签区分 VPN；公网标签穿通骨干（LDP 等）。（详细转发与配置见下一章。）
