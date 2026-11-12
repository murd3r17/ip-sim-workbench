---
doc_id: "hcie-datacom-v1.0-training-22"
title: "NETCONF、YANG 与 RESTCONF"
book: "HCIE-Datacom-V1.0-Training"
book_title: "HCIE-Datacom V1.0 培训教材"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "training"
source_pdf: "HCIE-Datacom+V1.0+培训教材.pdf"
seq: 22
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# NETCONF、YANG 与 RESTCONF

## 前言与目标

对于设备配置管理，工程师更习惯使用 CLI 与设备交互，该方式简单直接、便于理解。但在网络自动化领域，CLI 存在效率较低、机器不易理解等问题。

IETF 为解决设备配置管理复杂问题，先后成立工作组，发布了 NETCONF、YANG 和 RESTCONF 相关标准。

学完本课程后，您将能够：

- 描述传统网络配置管理的问题与挑战
- 描述 NETCONF、YANG 和 RESTCONF 的基本原理
- 描述 NETCONF、YANG 和 RESTCONF 之间的区别和关系
- 了解 NETCONF 和 RESTCONF 的工作原理

课程大纲：

1. 网络管理技术背景
2. NETCONF 协议
3. YANG 建模语言
4. RESTCONF 协议

## 1. 网络管理技术背景

### 设备数据简介

运行设备上可获取的信息分为两类：

- **配置数据**：可写（writable）数据，可改变系统状态（例如从初始状态变为当前状态）。
- **状态数据**：只读（read-only）的非配置数据，例如状态信息与统计信息。

更改/获取设备数据的方法包括 CLI、SNMP、NETCONF、RESTCONF、Telemetry 等。命令行和 SNMP 是最经典的方法。

### 经典配置管理问题

**SNMP 问题：**

- 基于 UDP，对配置管理而言无状态、无序、不可靠。
- 只能对一个对象单独配置，而非面向业务；多对象同时配置时部分成功部分失败会对网络造成未知影响。
- 只是单设备管理，不支持网络级配置和多设备协同。
- 安全性不足。

| 方法 | 优势 | 劣势 |
|------|------|------|
| CLI | 文本接口，人类易理解；基于 Telnet/SSH，使用便利 | 各厂商 CLI 不同，需分别学习与适配；脚本非结构化、易变，解析复杂，难自动化 |
| SNMP | 机器与机器接口，有数据模型（MIB）；主要用于网络监控 | 基于 UDP 不可靠；面向单对象；不支持网络级协同；不安全 |

结论：无论配置自动化技术如何发展，若本质仍停留在 CLI，则难以彻底解决机器可读问题；SNMP 不适合配置管理。

### 网络管理本质诉求

2002 年 IAB（Internet Architecture Board）网络管理大会提出 14 项本质诉求，包括：

- 易用；设备解决内部配置次序；基于角色的访问控制和最小授权；避免不必要的变化
- 区分配置数据与状态数据；支持配置备份和恢复
- 可跨设备对 ACL 做一致性检查；能分别获取配置/状态数据并可跨设备比较
- 支持配置校验（含网络级）；支持多个配置集，区分配置与激活
- 网络级业务配置能力；标准数据模型与统一数据格式
- 支持面向数据与面向任务的访问控制；支持网络级配置事务；基于文本的配置

IETF 逐步落实上述结论。NETCONF 1.0 对模型语言没有要求；NETCONF 1.1 确定与 YANG 结合。

### 工程师配置设备流程

命令行是人类与设备的交互语言。工程师查询产品文档，使用嵌套命令行配置设备。例如：

```cli
[Router] interface GE1/0/0
[Router-GE1/0/0] mtu 1500
```

> （说明：真实 YANG 模型不会将整个设备做成一个 YANG 文件，而是按功能拆分为多个 YANG 文件。）

---

## 2. NETCONF 协议

### NETCONF 简介

NETCONF（Network Configuration Protocol，网络配置协议）提供一套管理网络设备的机制，用户可增加、修改、删除设备配置，获取配置和状态信息。

三个对象：

- **NETCONF 客户端**：管理平台 / SDN 控制器
- **NETCONF 服务器**：网络设备
- **NETCONF 消息**：客户端与服务器之间的交互消息

### NETCONF 协议框架（四层）

| 层次 | 说明 |
|------|------|
| 安全传输层（Secure Transport） | 为客户端与服务器提供通信路径；当前华为常用 SSH 作为承载协议 |
| 消息层（Messages） | 提供不依赖传输层的 RPC 请求与回应；Client 将请求封装在 `<rpc>`，Server 将结果封装在 `<rpc-reply>` |
| 操作层（Operations） | 定义一组基本操作，作为 RPC 调用方法，构成 NETCONF 基本能力（如 `<edit-config>`、`<get-config>` 等） |
| 内容层（Content） | 描述配置/状态数据，依赖各制造商设备；主流数据模型有 Schema、YANG 等 |

### XML 编码

XML 是 NETCONF 的编码格式，用文本文件表示复杂层次化数据。

XML 文件头示例：

```xml
<?xml version="1.0" encoding="UTF-8"?>
```

示例文档：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<note>
  <to>Learners</to>
  <from>Huawei</from>
  <heading>Reminder</heading>
  <body>Don't forget Reading!</body>
</note>
```

说明：

- `<?` 表示指令开始，`?>` 表示指令结束
- `xml` 表示此文件是 XML；`version="1.0"` 表示 XML 1.0；`encoding` 当前仅支持 UTF-8
- XML 文档形成树结构；标签由使用者自定义；`/` 表示结束当前标签

### 传输层与消息层

NETCONF 使用 SSH 实现安全传输，使用 RPC（Remote Procedure Call）实现客户端与服务端通信。

- `<rpc>`：封装从客户端到服务端的 NETCONF 请求；头部用 `message-id` 标识序列
- `<rpc-reply>`：服务端回应
- `<rpc-error>`：在 `<rpc-reply>` 中发送；一个 `<rpc-reply>` 可包含多个 `<rpc-error>`
- `<ok>`：在 `<rpc-reply>` 中发送，表示没有错误且没有数据返回

更多详见 RFC 6241。

### NETCONF 基本操作

| 场景分类 | 操作 | 功能描述 |
|---------|------|---------|
| 查询数据 | `<get-config>` | 查询配置数据 |
| 查询数据 | `<get>` | 查询设备当前运行的配置和状态数据 |
| 编辑数据 | `<edit-config>` | 修改、创建、删除配置数据 |
| 备份/恢复 | `<copy-config>` | 导出配置，或用一套配置整体替换另一套配置 |
| 备份/恢复 | `<delete-config>` | 删除配置数据集（如清空 startup） |
| 锁定/解锁 | `<lock>` | 加锁，独占配置数据集修改权 |
| 锁定/解锁 | `<unlock>` | 解锁，放弃独占修改权 |
| 事务操作 | `<commit>` | 提交 `<candidate>` 中的配置成为当前运行配置 |
| 事务操作 | `<cancel-commit>` | 放弃配置提交试运行 |
| 事务操作 | `<discard-changes>` | 放弃 `<candidate>` 中尚未提交的配置 |
| 事务操作 | `<validate>` | 检查指定配置数据的语法语义是否正确 |
| 会话操作 | `<close-session>` | 正常结束本 NETCONF 会话 |
| 会话操作 | `<kill-session>` | 强制结束指定会话 |

### NETCONF 操作对象（配置库）

操作对象通常涉及三个配置库，可灵活读取和编辑，实现整体下发、验证和回滚：

| 配置库 | 说明 |
|--------|------|
| `<startup>` | 启动配置库（重启恢复） |
| `<candidate>` | 候选配置库 |
| `<running>` | 运行配置库 |

还可配合 `<URL>` 文件、`<lock>`/`<unlock>`、`<copy-config>`、`<discard-changes>`、`<delete-config>`、`<validate>`、`<edit-config>` 等操作流转数据。

### edit-config 的 operation 属性

`<config>` 中可包含可选 `operation` 属性；未携带时默认为 merge。

| 取值 | 含义 |
|------|------|
| merge | 目标数据不存在则创建，存在则修改（默认） |
| create | 仅当数据不存在时才能创建；若已存在返回 `<rpc-error>`，`<error-tag>` 为 `data-exists` |
| delete | 删除指定数据；不存在则返回 `<rpc-error>`，`<error-tag>` 为 `data-missing` |
| remove | 删除指定数据；不存在也返回成功 |

说明：Schema 是华为基于 W3C XML 标准扩展私有语法的一种语言；在 NETCONF 尚未与 YANG 绑定前，VRP V8 已实现 Schema。内容最丰富的是 Huawei-YANG。

### 案例：下发 VLAN 配置（Huawei-YANG）

本例 `edit-config` 将数据加载到运行数据库 `<running/>`。内容层命名空间为 `vrp/huawei-vlan`；结构为 `<vlans>` 包含 `<vlan>`，`<vlan>` 包含 `<vlanId>` 等。RPC 请求：创建 VLAN ID 为 10 的普通 VLAN。

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rpc xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" message-id="801">
  <edit-config>
    <target>
      <running/>
    </target>
    <default-operation>merge</default-operation>
    <error-option>rollback-on-error</error-option>
    <config>
      <vlans>
        <vlan>
          <vlanId>10</vlanId>
          <protocolVlans>
            <!-- protocolVlan 等子节点按实际 YANG 填写 -->
          </protocolVlans>
        </vlan>
      </vlans>
    </config>
  </edit-config>
</rpc>
```

更多详见官网《NETCONF YANG API 参考》。

### 案例：下发 VLAN 配置（Schema）

同样创建 VLAN 10，但内容为 Schema 方式。更推荐使用 Huawei-YANG，特性支持更完整。

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rpc xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" message-id="108">
  <edit-config>
    <target>
      <running/>
    </target>
    <default-operation>merge</default-operation>
    <error-option>rollback-on-error</error-option>
    <config>
      <vlans>
        <vlan operation="create">
          <vlanId>10</vlanId>
          <vlanType>common</vlanType>
        </vlan>
      </vlans>
    </config>
  </edit-config>
</rpc>
```

### NETCONF 设备配置

1. 进入 NETCONF 视图：

```cli
[Huawei] netconf
```

2. 配置 NETCONF 服务端口号（在 830 端口使能 SSH 服务器的 NETCONF 服务）：

```cli
[Huawei-netconf] protocol inbound ssh port 830
```

3. 使能 NETCONF 功能（在 TCP 22 端口使能 SSH 服务器的 NETCONF 服务）：

```cli
[Huawei] snetconf server enable
```

说明：

- `snetconf server enable` 与 `protocol inbound ssh port 830` 都可以使能 NETCONF；若两者都配置，客户端可用 22 或 830 端口建立连接。
- NETCONF 使用 SSH 作为承载协议，使用前必须配置 SSH。

---

## 3. YANG 建模语言

### YANG 的起源

虽然 NETCONF 协议标准化，但数据内容未统一标准化。数据模型（Data Model）是对数据特征的抽象和表达，需要一门语言描述：数据结构、数据完整性约束、数据操作（三要素），且便于人类理解与计算机实现。

要点：

- YANG 起源于 NETCONF，但不仅用于 NETCONF。
- YANG 文件可分为：厂家私有 YANG、IETF 标准 YANG、OpenConfig YANG。
- NETCONF 中的 Config&Status Data、Notification Data 以及 RPC 消息都可通过 YANG 建模；YANG 文件可转换为 XML/JSON，再被 NETCONF/RESTCONF 消息封装。

### 认识 YANG 文件：Module

一个 YANG 文件通常定义为一个模块（module）或子模块（submodule）。模块可引用其他模块以复用数据类型和结构。

模块常见声明包括：

- YANG 版本（1.0 或 1.1）
- 命名空间（namespace）与前缀（prefix）
- 机构信息、联系人、文件描述
- 修订信息（revision）
- 数据节点（如 `container system`）

### Leaf / Leaf-list / List / Container / Grouping

**Leaf**：定义简单指定类型变量。

```yang
leaf host-name {
  type string;
  description "...";
}
```

对应 XML 示例：`<host-name>...</host-name>`

**Leaf-list**：数组类型变量。

```yang
leaf-list domain-search {
  type string;
  description "...";
}
```

对应 XML 可出现多个 `<domain-search>` 元素。

**List**：带 key 的列表节点。

```yang
list user {
  key "name";
  leaf name { type string; }
  leaf full-name { type string; }
  leaf class { type string; }
}
```

**Container**：更大范围的数据集合；容器本身无值，只有子节点（可为 container、leaf、leaf-list、list 等）。

**Grouping**：定义可重复使用的节点，一般与 `uses` 一起使用。例如 `grouping target` 定义 `address`/`port`，在 `container peer` 中 `uses target` 复用。

### 配置数据与状态数据

`config` 声明用于区分：

- `config true`：配置数据
- `config false`：状态数据

示例：

```yang
list interface {
  key "name";
  config true;
  leaf name { type string; }
  leaf speed { type enumeration { ... } }
  leaf observed-speed {
    type uint32;
    config false;
  }
}
```

更多细节见 RFC 7950。

### 数据类型

YANG 支持内置类型与通过 `typedef` 扩展类型。常见内置类型包括：binary、bits、boolean、decimal64、empty、enumeration、identityref、instance-identifier、int8/16/32/64、uint8/16/32/64、leafref、string、union 等。

`typedef` 示例：

```yang
typedef percent {
  type uint8 {
    range "0 .. 100";
  }
}
leaf completed {
  type percent;
}
```

### FAQ：如何加载 YANG 模型？

在 NETCONF 客户端（网管平台/SDN 控制器）加载 YANG 文件，通过工具将 YANG 转换为 NETCONF 消息下发到设备。设备侧可支持 Huawei YANG、IETF YANG、OpenConfig YANG，以及 NETCONF Schema 等。

---

## 4. RESTCONF 协议

### RESTCONF 起源

2000 年 Roy Thomas Fielding 博士论文定义 REST 风格。REST（Representational State Transfer，表述性状态转移）描述资源在网络中以某种表现形式进行状态转化。REST 是客户端-服务器交互框架，常用 GET/POST/PUT/DELETE 等 API。

2017 年 IETF 发布 RFC 8040 RESTCONF 协议规范。

### RESTCONF 概述

RESTCONF 允许 Web 应用以模块化、可扩展方式访问网络设备的配置数据、状态数据和事件通知。特点：

- 使用 HTTP 方法对设备 YANG 定义的数据进行 CRUD 操作
- 设备上 NETCONF 与 RESTCONF 可共享 YANG 文件
- 数据编码支持 XML 或 JSON
- 与 NETCONF 相比，操作方法与数据编码不同；二者可共存

### RESTCONF 与 NETCONF 对比

- NETCONF：可操作多个配置库，有事务机制与回滚。
- RESTCONF：使用 HTTP 操作，无状态，无事务机制，无回滚。

| RESTCONF | 对应的 NETCONF 操作 |
|----------|---------------------|
| GET | `<get-config>`、`<get>` |
| POST | `<edit-config>`（如 `nc:operation="create"`）等；也可 invoke RPC |
| PUT | `<edit-config>`（create/replace）；对 datastore 的 PUT 类似 `<copy-config>` |
| PATCH | `<edit-config>`（operation 取决于 PATCH 内容） |
| DELETE | `<edit-config>`（`nc:operation="delete"`） |

传输层：NETCONF 多为 SSH over TCP；RESTCONF 多为 TLS over TCP（HTTPS）。内容层：NETCONF 数据为 XML；RESTCONF 为 XML/JSON。

### 一次典型的 RESTCONF 交互

完整交互包含请求和响应。本例客户端通过 OPTIONS 获取设备支持的操作方法；设备回复支持 POST、DELETE、GET、HEAD、PATCH、OPTIONS。

请求：

```http
OPTIONS /restconf/data/huawei-aaa:aaa/domains/domain HTTP/1.1
```

响应：

```http
HTTP/1.1 200 OK
Accept-Patch: application/yang-data+xml, application/yang-data+json
Allow: POST, DELETE, GET, HEAD, PATCH, OPTIONS
Content-Length: 0
```

请求报文头部可包含 Accept、Authorization、Host、From 等字段（可查阅相关 RFC）。

### RESTCONF 请求案例

RESTCONF 请求对象地址为 `192.168.56.100`。创建/修改 domain，设置 `domainName` 为 `abc`，`accessLimit` 为 `10`：

```http
POST /restconf/data/huawei-aaa:aaa/domains HTTP/1.1
Host: 192.168.56.100
Content-Type: application/yang-data+xml

<domain>
  <domainName>abc</domainName>
  <accessLimit>10</accessLimit>
</domain>
```

### RESTCONF 响应案例

- 返回状态码 201，表示资源创建成功。
- 头部 Content-Type、Content-Length 描述 Body；本例 Body 长度为 0。

```http
HTTP/1.1 201 Created
Content-Type: application/yang-data+xml
Content-Length: 0
```

更多状态码说明可参考 RFC 7231 中 Response status code 章节。

### 要点回顾

1. 华为使用 SSH 作为 NETCONF 传输层协议；开启设备 NETCONF 时需创建 SSH 用户作为 NETCONF 用户登录。
2. YANG 是建模语言，用于描述 NETCONF 和 RESTCONF 的内容层。RESTCONF 基于 HTTP 构建传输层、消息层和操作层；NETCONF 使用 SSH 为传输层、RPC 为消息层、NETCONF 定义操作层。

### 本章总结

- NETCONF 是网络配置协议，提供增加、修改、删除配置及获取配置/状态信息的机制。
- YANG 是数据建模语言，定义数据层次化结构，可用于基于 NETCONF 的操作。
- RESTCONF 使用 HTTP 方法对设备 YANG 定义的数据进行操作。

---

## Telemetry 概述（续）

> 以下为后续 Telemetry 章节开篇内容，完整实践见下一分册。

### 前言与目标

Telemetry 是一种网络设备监控技术，提供周期采样网络设备内统计数据与状态数据的能力。本章讲述技术背景、概念、框架与原理，并通过静态订阅完成实践。

学完后，您将能够：

- 描述 Telemetry 技术背景
- 描述 Telemetry 的概念和框架
- 区分静态订阅和动态订阅
- 描述 gRPC 的概念和作用
- 实现 Telemetry 数据采样

### 技术背景

网络设备统一监控与性能管理是运维平台重要功能。监控数据包括数据、控制和管理平面数据。获取方式有 SNMP、CLI、Syslog、NetStream、sFlow 等。

- NetStream/sFlow 主要针对数据平面流量监控。
- SNMP 是最主流传统方式。

传统采集问题：

- 按奈奎斯特采样定律，采样频率需大于信号频率 2 倍才可完整保留信息。SNMP 采集周期常为 5 分钟，细节易丢失，难以发现流量异常。
- **微突发**：毫秒级瞬时突发速率可达平均速率数十/数百倍甚至超过端口带宽；长周期平均带宽曲线可能仍平稳，但设备已因微突发丢包。
- SNMP 一问一答，重复查询压力大；Telemetry 订阅一次后可持续推送。

业界也有将 SNMP 称为传统 Telemetry，而把当前技术称为 Streaming Telemetry 或 Model-Driven Telemetry 的说法。

### Telemetry 技术特点与优势

特点：推模式工作；YANG 模型定义结构；精度可达亚秒级；传统网管解耦为采集器与控制器；向第三方分析系统开放 API。

优势：

| 能力 | 说明 |
|------|------|
| 精细监控 | 精度高、类型丰富，充分反映网络状况 |
| 快速定位 | 可达秒级甚至亚秒级故障定位 |
| 主动上报 | 配置一次订阅后持续上报，减轻设备查询压力 |

### 网络模型与应用场景

- **广义 Telemetry**：采集器、分析器、控制器和设备构成自闭环系统。
- **狭义 Telemetry**：设备采样数据上送给采集器的功能。

应用场景示例：

- **广域网**：路由器端口数据实时上报，洞察流量走向，支撑扩容、Cost 调整、CDN/路由策略等。
- **园区网**：设备状态、有线无线数据同时监控上报，实现智能运维（AP/射频/用户/设备/接口等指标）。
- **数据中心**：采集器通过 Telemetry 采集性能数据，并通过 ERSPAN 采集流镜像。

### 技术原理要点

- 框架可参考 RFC 草案：https://tools.ietf.org/html/draft-song-ntf-02
- **gRPC**：Google 开发的远程过程调用系统
- **UDP**：无连接数据报协议
- **Protobuf（GPB）**：序列化结构数据的机制，二进制编码，传输效率高于 XML/JSON

形象理解：YANG 像菜单；按 YANG 写采购清单；装入 GPB 信封；由 gRPC 信使经 HTTP/2 送到设备侧解析核对。

### 数据源、订阅与推送

**数据源**：采用 YANG 定义可获取数据（Huawei-YANG、IETF-YANG、OpenConfig-YANG）。

**订阅方式（华为）**：

| 类型 | 角色关系 | 典型用途 |
|------|---------|---------|
| 静态订阅（dial-out） | 设备作客户端，主动连采集器并上送 | 长期巡检 |
| 动态订阅（dial-in） | 采集器作客户端连设备并发起 Subscribe | 短期监控 |

静态订阅流程概要：

1. 网管下发静态配置（采样路径、周期、上送目标、编码等）；支持 CLI 或 NETCONF（如 openconfig-telemetry.yang）。
2. 设备启动采样任务，主动向采集器发起连接并推送；支持 gRPC（如 `dataPublish`）或 UDP。

关键配置视图概念：

- `destination-group`：采集器 IPv4 地址、端口、协议与加密方式
- `sensor-group` / `sensor-path`：传感器采样路径
- `subscription`：关联传感器组、采样周期、抑制与心跳等

常用查询：

```cli
display telemetry sensor
display telemetry destination
display telemetry subscription
display telemetry sensor-path
```

自定义事件上报示例思路：在 sensor-path 上配置条件表达式，例如 CPU 使用率 `gt 40` 时触发相关订阅上报。

动态订阅：采集器向设备发起 gRPC 连接与 Subscribe（指定路径、周期等），设备将采样数据作为 RPC 应答持续返回。设备侧需配置 gRPC server（source-ip、server-port、service enable，以及可选 ACL/idle-timeout/ssl 等）。

```cli
display telemetry dynamic-subscription
```

### gRPC 与数据生成/推送

gRPC 特点：语言中立、平台中立、开源；支持 C++、Python、Java、Go 等；基于 HTTP/2（双向流、流控、头部压缩、多路复用）。

协议栈五层：TCP →（可选）TLS → HTTP/2.0 → gRPC → 数据模型层（GPB/XML/JSON 等）。

四种服务模式（通过 stream 区分）：

| 模式 | 示例 |
|------|------|
| 简单模式 | `rpc Cancel(CancelArgs) returns (CancelReply);` |
| 服务端流 | `rpc Subscribe(SubsArgs) returns (stream SubsReply);` |
| 客户端流 | `rpc LotsOfGreetings(stream HelloRequest) returns (HelloResponse);` |
| 双向流 | `rpc dataPublish(stream serviceArgs) returns (stream serviceArgs);` |

数据生成采用 GPB（Google Protocol Buffers）编码。推送方式：基于 gRPC 或基于 UDP。

基于 UDP 推送可优化为采集器与线路卡 CPU 多对一隧道，缓解主控板压力并提升效率。

gRPC 推送格式层次：TCP → TLS（可选）→ HTTP2 → gRPC → RPC（dialout/dialin proto）→ Telemetry 层（huawei-telemetry.proto）→ 业务数据层（如 huawei-debug.proto）。

UDP 推送格式层次：UDP → DTLS（可选）→ 消息头层（ietf draft）→ Telemetry 层 → 业务数据层。

### 案例开篇：配置 Telemetry 静态订阅

案例描述：某公司 CE12800 管理 IP 为 `192.168.56.100`，要求通过 Telemetry 静态订阅将 CPU 信息推送到服务端（采集器本例为本地 PC `192.168.56.1`）。

> 具体配置步骤与 Python 采集器实现见下一分册。
