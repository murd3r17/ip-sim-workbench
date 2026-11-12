---
doc_id: "hcie-datacom-v1.0-training-24"
title: "HTTP 报文、RESTful 与 NCE 开放能力"
book: "HCIE-Datacom-V1.0-Training"
book_title: "HCIE-Datacom V1.0 培训教材"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "training"
source_pdf: "HCIE-Datacom+V1.0+培训教材.pdf"
seq: 24
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# HTTP 报文、RESTful 与 NCE 开放能力

## 客户端请求消息

客户端发送的 HTTP 请求消息由请求行、请求头部、空行和请求数据四部分组成：

| 组成部分 | 说明 |
|---------|------|
| 请求行 | 请求方法 + URI + 协议版本 |
| 请求头部 | 头部字段名:值（可多行） |
| 空行 | 以回车换行分隔头部与正文 |
| 请求数据 | 请求体（如 POST 表单数据） |

### 请求行

请求行由三个字段组成：

- **请求方法**：HTTP 客户程序向服务器发送请求时必须指明请求类型，例如 GET、POST。
- **URI**：统一资源标识符，标识请求所针对的资源。
- **协议版本**：指示消息格式及对后续 HTTP 通信的理解能力。

请求行示例：

```text
GET http://www.w3.org/pub/WWW/TheProject.html HTTP/1.1
```

### HTTP 请求方法

HTTP/1.0 定义了三种请求方法：GET、POST、HEAD。HTTP/1.1 新增六种：OPTIONS、PUT、PATCH、DELETE、TRACE、CONNECT。

| 方法 | 描述 |
|------|------|
| GET | 请求指定的页面信息，服务端返回具体内容数据 |
| POST | 提交数据，例如提交表单 |
| HEAD | 类似于 GET，但响应中没有具体内容，用于获取报头 |
| PUT | 更新和修改数据 |
| DELETE | 请求删除指定的页面/资源 |
| CONNECT | 用于 HTTP 代理 |
| OPTIONS | 允许客户端查看服务器支持的能力 |
| TRACE | 回显服务器收到的请求，主要用于测试或诊断 |
| PATCH | 对已知资源进行局部更新 |

### 请求头部

请求头部允许客户端向服务器传递关于请求的附加信息，语义相当于方法调用中的参数。

请求头部示例：

```text
Accept: text/html
Accept-Encoding: gzip, deflate, br
Connection: keep-alive
```

补充说明：

- HTTP/1.0 每个连接通常只传送一个请求和响应后关闭；HTTP/1.0 没有 Host 字段。HTTP/1.1 可在同一连接中传送多个请求和响应。
- WWW-Authenticate 是早期简单有效的用户身份认证技术。
- 浏览器显示内容（HTML、XML、GIF、Flash 等）通过 MIME Type 区分。
- 更多细节见 RFC HTTP/1.1：https://www.ietf.org/rfc/rfc2616.html

常见首部字段示例：

| 字段 | 含义 |
|------|------|
| Host | Web 服务器主机名和端口 |
| User-Agent | 发起请求的应用程序名称 |
| Accept | 客户端可接受的媒体类型 |
| Accept-Language | 客户端可接受的语言 |
| Date | 当前 GMT 时间 |
| Content-Length | 内容长度 |
| Content-Type | 文档类型 |

### 请求数据

- **空行**：告诉服务器请求头部到此为止。
- **请求数据**：若方法为 GET，此项通常为空；若为 POST，通常放置要提交的数据。

请求数据示例：

```text
user=admin&password=<SET-YOUR-OWN-CREDENTIAL>
```

## 服务器响应消息

HTTP 响应消息由状态行、响应头部、空行和响应正文四部分组成。

### 状态行

状态行由协议版本、状态码和原因短语组成，元素之间由空格分隔。

- **协议版本**：指示消息格式及对后续 HTTP 通信的理解能力。
- **状态码**：3 位整数结果码，向客户端返回操作结果。
- **原因短语**：对状态码的简短文本描述。

状态行示例：

```text
HTTP/1.1 200 OK
```

### HTTP 状态码

HTTP 状态码是服务器响应状态的 3 位数字码。

| 类别 | 说明 | 示例 |
|------|------|------|
| 1XX (Informational) | 请求被接收 | 100 Continue：请求被接收，继续执行 |
| 2XX (Successful) | 请求成功 | 200 OK：成功，有响应消息体；201 Created：资源创建成功；204 No Content：成功，无响应消息体 |
| 3XX (Redirection) | 需要进一步操作 | 301 Moved Permanently：目标资源被分配了新的 URI |
| 4XX (Client Error) | 客户端请求错误 | 400 Bad Request：请求消息体错误；401 Unauthorized：授权失败；403 Forbidden：禁止访问；404 Not Found：找不到请求的资源 |
| 5XX (Server Error) | 服务端错误 | 500 Internal Server Error：服务器内部错误；501 Not Implemented：未实现 |

说明：

- 响应头用于描述服务器及数据基本信息，通知客户端如何处理后续数据。
- 设置响应头常与状态码结合：例如“位置已改变”通常伴随 Location 头；401 Unauthorized 必须伴随 WWW-Authenticate 头。
- 响应头还可用于设置 Cookie、指定日期、指示客户端按间隔刷新页面等。

### 响应正文

- **空行**：告诉客户端响应头部到此为止。
- **响应正文**：响应消息体。若请求纯数据则返回纯数据；若请求 HTML 页面则返回 HTML 代码。

## 报文示例

### 客户端请求示例（登录认证）

```http
POST http://www.w3.org/pub/WWW/TheProject.html HTTP/1.1
Accept: text/html
Accept-Encoding: gzip, deflate, br
Accept-Language: zh-CN,zh;q=0.9
Content-Type: text/html;charset=utf-8
Connection: keep-alive

user=admin&password=<SET-YOUR-OWN-CREDENTIAL>
```

### 服务器响应示例（认证成功）

```http
HTTP/1.1 200 OK
Date: YY-MM-DD
Accept-Language: zh-CN,zh;q=0.9
Content-Type: text/html
Connection: keep-alive

Login succeeded
```

## HTTPS 与 HTTP/2

### HTTPS

HTTP 采用明文传输，存在信息窃听、篡改和劫持风险。TLS 具有身份验证、信息加密和完整性校验能力，可避免此类问题。更多参考 RFC 5246：https://www.ietf.org/rfc/rfc5246.html

### SPDY 与 HTTP/2

SPDY 是 Google 开发的基于 TCP 的应用层协议，目标是优化 HTTP 性能（压缩、多路复用、优先级等），核心思想是尽量减少 TCP 连接数；它不是替代 HTTP，而是对 HTTP 的增强。

HTTP/2 主要增强：

- **头部压缩**：采用 HPACK 压缩头部，减小头部体积。
- **多路复用**：请求可细分为帧交错发送，对端再重组。HTTP/1.1 中同一 TCP 连接上多请求时服务器需按序响应，后续请求可能被阻塞。
- **服务器推送**：除响应客户端请求外，还可主动推送额外资源。
- **优先级**：浏览器可一次请求多个资源并指定优先级，帮助服务器调度处理顺序。

## RESTful 接口调用实践

### 环境说明

- 实验组网包含 CloudIDE 与 iMaster NCE。
- CloudIDE 由华为云提供云端开发环境；也可使用本地环境编写代码。
- iMaster NCE 沙箱由数通开发者社区提供。
- Token 为字符串，用于 API 鉴权与认证。

### 案例：调用 RESTful 接口获得 Token

配置思路：

1. 环境准备：准备 IDE 和实验沙箱环境。
2. 编写 Python RESTful API 调用示例代码。
3. 结果验证。

交互示意：客户端（CloudIDE）向服务器（iMaster NCE）发送 HTTP POST 请求获取 Token，服务器返回 Token 数据。

参考：

- CodeHub 指南：https://support.huaweicloud.com/codehub/index.html
- 华为云 DevCloud 代码示例可在开发者社区获取
- 沙箱预约：https://devzone.huawei.com/openecosystem/experienceView/campus.html

沙箱信息关注点：

- “租户账号”为 NCE 页面登录账户
- “密码”为本次申请的沙箱登录密码
- 北向 IP/端口示例：`139.9.213.72:18002`

可在 CloudIDE 中右键选择 “Run Python File in Terminal” 运行代码。

### 编写 Python 脚本

```python
import requests

# 配置北向用户信息及北向地址
host = "139.9.213.72"
port = "18002"
nbi_name = "<北向用户名>"
nbi_pwd = "<北向密码>"

# 定义接口 URI
POST_TOKEN_URL = "/controller/v2/tokens"
post_token_url = "https://" + host + ":" + port + POST_TOKEN_URL

# 配置请求头部
headers_post = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# 发起请求，报文体为 JSON
r = requests.post(
    post_token_url,
    headers=headers_post,
    json={"userName": nbi_name, "password": nbi_pwd},
    verify=False,
)

# 解析返回数据，获得 token
token_id = r.json()["data"]["token_id"]
print("1. [ Get Token Id ]")
print("[ post_token_url ] : " + post_token_url)
print("[ token_id ] : " + token_id)
```

### 结果验证

调用成功后可得到 `token_id`，例如：

```text
[ Get Token Id ]
[ post_token_url ] : https://139.9.213.72:18002/controller/v2/tokens
[ token_id ] : x-rs5jy7z47vsum042r2qc9vtaq44o9hgqohf3uca7z9clio5vvz86al3s5dvs0aphpck5defw45uqpi3xdgddmn482kgajutf7vlfs649rw6k5c6r610a5i1g4b5j9c
```

### 思考题

1.（单选题）以下采用哪种方法的 HTTP 请求不需要请求数据？

- A. POST
- B. GET
- C. PUT
- D. DELETE

参考答案：B

### 本节小结

- SDN 以控制器为主体，让网络更加开放、灵活和简单。
- REST 是一种架构风格或设计风格，不是标准，仅提供设计原则和约束条件。
- REST 充分利用 HTTP 协议，核心是对有多种表现形式的资源进行操作（GET、POST、PUT、DELETE 等）。
- 通过 RESTful 接口调用，可根据需求撰写 Python 脚本实现自动化。

更多信息：

- REST 论文：https://www.ics.uci.edu/~fielding/pubs/dissertation/rest_arch_style.htm
- HTTP/1.0 RFC：https://www.ietf.org/rfc/rfc1945.html
- HTTP/1.1 RFC：https://www.ietf.org/rfc/rfc2616.html
- HTTP/2 RFC：https://www.ietf.org/rfc/rfc7540.html
- HTTPS RFC：https://www.ietf.org/rfc/rfc2818.html

---

## iMaster NCE-Campus 开放能力

### 前言与目标

iMaster NCE-Campus 是面向企业园区网的新一代 SDN 控制器，是华为智简园区网络 CloudCampus 解决方案的核心部件。它集中管控企业园区，提供自动化部署、安全防御和可视化运维，协助构建以业务为中心的网络业务动态调度能力，并提供标准 RESTful 接口开放能力，供合作伙伴开发创新应用。

学完本部分后，您将能够：

- 描述 iMaster NCE-Campus 解决方案
- 描述 iMaster NCE-Campus 主要开放 API
- 描述 iMaster NCE-Campus 典型应用场景

iMaster NCE-Campus 是集管理、控制、分析和 AI 于一体的网络自动化与智能化平台，提供园区网络全生命周期自动化、基于大数据和 AI 的故障智能闭环能力。

分层能力：

- **应用层**：聚焦主流场景，覆盖行业应用；网络业务数据全共享。
- **平台层**：覆盖多类 API，支持业界标准网络对接协议。
- **网络层**：支持 NETCONF/YANG/Telemetry 等开放接口；AP 开放三方物联插卡。
- **终端层**：支持物联终端（Zigbee、RFID、BLE 等）及有线/无线终端接入。

### 典型合作场景与开放接口

| 典型合作场景 | 相关 API / 能力 |
|-------------|----------------|
| 认证授权 | 三方认证 API、Portal+Radius、Authorization API |
| 网络运维 | 基础服务 API、网络配置 API、运维监控 API、策略服务 API |
| 位置服务 | 位置服务 API、平台 RSSI API、AP RSSI API、蓝牙 API |
| 人群画像 | 增值业务 API、终端数据/应用数据/流量数据 API |
| 智慧物联 | IoT API；网络层物联插卡（RFID/ZigBee/Bluetooth 等） |
| 资产管理 / 能效管理 / 电子价签 / 物联定位 | 物联相关开放能力 |

网络层还可对接 NETCONF/YANG/Telemetry/Syslog/SNMP 等。

### 认证授权场景

- 租户或 MSP 希望使用已有或第三方认证平台，通过 Web 页面（认证 Portal）进行接入认证与授权。
- 终端用户连接 Wi-Fi SSID，登录开发者应用推送的 Portal 页面；应用调用 iMaster NCE-Campus 认证授权 API，给 AP 授权终端接入权限。
- NAC：Network Access Control（网络访问控制）。
- HACA 协议基于移动互联网的 HTTP/2.0 协议。

参考：

- 认证授权方案：https://devzone.huawei.com/cn/enterprise/campus/apiSolution.html
- RADIUS 方案：https://devzone.huawei.com/cn/enterprise/campus/radiusSolution.html

### 位置服务场景

- LBS（Location Based Services）利用定位技术获取当前位置，并通过移动互联网提供信息与服务。
- iMaster NCE-Campus 可将 AP 采集的终端位置数据汇聚，周期性发送给第三方 LBS 分析平台，用于热力图、轨迹跟踪、客流分析等（需满足如 GDPR 等相关标准）。
- 支持直接上报终端位置数据（中继位置服务方案）。
- Validator 为 UUID 格式，由 iMaster NCE-Campus 生成。

参考：

- 开发者社区：https://developer.huaweicloud.com/techfield/network.html#CloudCampus
- AP 位置上报：https://devzone.huawei.com/cn/enterprise/campus/lbsWiFiSolution.html
- AP 蓝牙定位：https://devzone.huawei.com/cn/enterprise/campus/lbsBluetoothSolution.html

### 人群画像场景

第三方大数据分析平台对园区网络探测和管理的终端位置与状态信息进行分析，获取区域内人群画像特征，支持精准信息推送。

| 集成方案 | 场景建议 |
|---------|---------|
| 位置服务 API | 提供终端位置信息 |
| 增值业务 API | 提供终端上下线信息、网络应用信息、网络流量信息 |

参考：https://devzone.huawei.com/cn/enterprise/campus/valueAddedApi.html

### 网络运维场景

客户/MSP 使用已有网管平台管理或监控华为控制器平台管理的设备（创建租户管理员、管理设备、下发配置、监控状态与告警等）。

| 集成方案 | 场景建议 |
|---------|---------|
| 网络业务 API（RESTful） | 适用于与各种三方私有 SaaS 平台对接 |
| NETCONF/YANG/Telemetry/Syslog/SNMP/NetStream 等 | 适用于与传统网管类软件对接 |

参考：https://devzone.huawei.com/cn/enterprise/cloudcampus/quickStart.html#network

### 智慧物联场景

通过 AP 开放插卡能力，将 AP 扩充为物联基站，实现能效管理、资产管理、物联定位、电子价签等。

- 合作伙伴借助华为网络基础设施完成物联信号（Zigbee、BLE、RFID 等）覆盖，避免部署第二套物联网络，降低 Capex。
- 华为侧提供基础网络设施、开放 AP 硬件与物联插卡的基础管理和监控。
- 合作伙伴侧完成物联插卡开发、插卡软件与物联业务软件开发。

参考：https://devzone.huawei.com/cn/enterprise/cloudcampus/quickStart.html#iot

### 开放合作案例摘要

**案例 1：城市 Wi-Fi 统一云化管理**

- 挑战：覆盖质量、租户环境多样；海量设备运维成本高。
- 价值：即插即用、全生命周期云管理、开放接口对接第三方认证计费；降低 OPEX。
- 合作接口：认证授权（Portal + Radius API）。

**案例 2：建筑群未来商业**

- 挑战：高密度高质量无线；室内导航；客流与人员位置可视化。
- 方案要点：三射频 AP 独立射频做 Wi-Fi TAG 定位扫描；地下车库结合蓝牙 beacon，可实现约 1m～3m 定位；开放 API 对接应用平台。
- 合作接口：位置服务（AP RSSI API）。

**案例 3：超市数字化转型**

- 通过物联网 AP（如 AP4050DN-E）内置插槽实现 IoT 与 Wi-Fi 融合部署。
- 电子价签对接超市管理与 ERP，支持动态变价、扫码购、优惠券、缺货预警等。
- 合作接口：智慧物联相关能力。

### 思考题

1.（多选题）智简园区开放支持哪几个层级？

- A. 应用层
- B. 平台层
- C. 网络层
- D. 终端层

参考答案：A、B、C、D

### 本节小结

通过介绍华为智简园区生态开放的方案架构、合作场景与 API 能力，可指导 MSP、增值应用伙伴与客户进行系统对接和业务融合，实现网络价值最大化。

---

## NCE 业务开放可编程

### 前言与目标

随着网络数字化转型，传统封闭网络难以满足快速创新。利用现有资产提升开放能力、按客户意图进行业务编排成为核心诉求。NCE 业务开放可编程基于 YANG 模型驱动的开放架构，以网元驱动包和业务包形式，使能网元层与网络层开放可编程，实现新设备快速对接与新网络业务快速构建。

学完本部分后，您将能够：

- 描述华为 NCE 业务开放可编程基本概念
- 描述其架构和工作原理
- 描述应用场景
- 使用系统完成新设备对接和新业务构建实践

### 背景

- 运营商面临收入下降、OPEX 上升及 OTT 竞争，需要多网融合、多厂商协同与高效管理。
- 5G 催生新业务，但传统“运营商提诉求—厂商实现”周期很长；需消除“运营商不懂设备、厂商不懂业务”的 GAP。
- 客户有定制需求；厂商更适合提供可定制能力，由客户自行完成定制。
- 云时代基础设施需被云平台统一纳管，DC 业务变更频繁，对自动化要求极高。

传统自动化多依赖 CLI 脚本模板，需逐设备适配，可维护性随规模下降。SDN 强调转控分离，集中控制器通过 API 操控转发面，为现代网络自动化铺路。

iMaster NCE（简称 NCE）融合网络管理、业务控制和网络分析，目标是从网络自动化迈向自适应乃至自治。整体开放可编程包括自动化、分析和意图；NCE 业务开放可编程属于自动化引擎的关键执行环节。

### 架构类比与关键组件

类比操作系统：驱动识别硬件 → 设备管理 → 业务/程序管理。NCE 侧对应加载设备驱动、管理设备状态与配置、构建业务能力，并提供事务失败回滚、配置变更自动检测等。

两个关键软件包：

| 包 | 全称 | 作用 |
|----|------|------|
| SND | Specific NE Driver，网元驱动包 | 提供与网元交互的数据模型 |
| SSP | Specific Service Plugin，业务包 | 定义完成一条网络业务配置对应的数据模型 |

工程师先编写并加载 SND 实现新设备对接，再编写并加载 SSP 实现新业务构建。

相关概念：

- **网元 YANG 模型**：抽象设备层原子能力（如创建子接口），由设备厂商提供。
- **业务 YANG 模型**：抽象业务模型，可生成北向接口和配置页面。
- **Easymap**：映射逻辑算法，将网络层业务分解成网元层业务。

设计态建立业务 YANG 与网元 YANG 映射；运行态完成设备管理与业务发放：

- 业务管理：按业务 YANG 生成界面，增删改查业务。
- 设备管理：按网元 YANG 生成界面，差异对比、同步、对账等。
- API Gateway：按模型自动生成北向 RESTCONF 接口。
- Dry-Run：预览操作结果及对设备配置的影响。
- Jinja2：用于 SSP 包模板化处理。

开发流程概要：需求分析与 HLD → 按需开发 SND → 开发 SSP（南向 Jinja2 模板、业务 YANG、可选业务逻辑）→ 调试验证 → 生产与增量开发。

### 关键能力

| 能力 | 说明 |
|------|------|
| 设备能力开放 | 基于设备 YANG 自动生成北向接口与配置页面；差异比较、配置对账、同步 |
| 批量配置 | 设备分组、预制模板、按组批量下发、任务化异步下发 |
| 业务能力开放 | 业务 YANG 驱动开放 |
| 事务机制 | dryRun 预检查；Commit；失败 Rollback，保障一致性 |
| 业务屏蔽设备差异 | 一条业务对接不同厂商/协议设备 |
| 业务冲突检测 | 数据源溯源、冲突检查；第三方改配可检测并修复 |
| 多协议对接 | 南向支持 NETCONF、STelnet（存量 CLI） |
| 安全审计 | 记录/回退历史配置点；业务关联配置可视 |

多协议对接：新设备推荐 NETCONF；存量设备可 CLI/STelnet。CLI 驱动的 SND 包同样基于 YANG 文件。

### 功能包结构

**SND（设备原子驱动包）**

- 通常包含一个 `.py` 文件和若干特性 YANG。
- `.py` 定义网元相关信息（设备类型、厂商、连接信息等）。
- YANG 描述网元特性数据结构。

**SSP（业务包）**

- 通常包含 Jinja2 模板、Python 映射脚本、业务 YANG。
- Jinja2 描述业务数据结构（插值、条件、循环等）。
- Python 脚本将用户数据填充到模板并映射到网元数据结构。
- 业务 YANG 描述业务输入参数。

两层映射：

1. 业务模型 → 设备模型（SSP）
2. 设备模型 → 协议报文（SND；NETCONF 设备可自动转换）

### NETCONF 在开放可编程中的位置

NETCONF 由 IETF 定义，用于在网元上安装、维护和删除配置数据；操作通过基于 XML 编码的 RPC 实现。NCE 业务开放可编程主要使用 NETCONF 与网元通信。

| 层次 | 内容 |
|------|------|
| 内容层 | 配置数据、通知数据 |
| 操作层 | 如 `<edit-config>` 等 XML 操作集 |
| 消息层 | `<rpc>`、`<rpc-reply>`、notification |
| 安全传输层 | SSH、TLS、BEEP/TLS、SOAP/HTTP/TLS 等 |

### YANG / Jinja 要点（示例级）

- 可用 `module`/`submodule`、`import`/`include`、`augment`、`revision`、`description` 等声明模块信息。
- `container` / `leaf` / `leaf-list` / `list` / `grouping`+`uses` / `choice`+`case` / `rpc` / `action` 等建模节点。
- `config true/false` 区分配置数据与状态数据。
- Jinja 常用：`{% ... %}` 控制结构、`{{ ... }}` 表达式、`{# ... #}` 注释；可用过滤器（如 `| capitalize`、自定义 `to_ne_id`）。
- 更多 Jinja2：https://jinja.palletsprojects.com/en/2.11.x/

### 实践用例要点

1. **设备快速对接**：加载 SND；管理华为与三方设备；自动生成配置页面和北向接口。三方设备 YANG 从厂商获取；仅 CLI 时需定制对接。
2. **业务快速构建**：基于业务 YANG 自动生成配置页与北向接口；Easymap 简化增删改计算；业务层屏蔽设备差异。
3. **批量配置**：分组 + 预制模板批量下发（企业网 DCN 可预置大量模板）。
4. **事务与审计**：dryRun → Commit；失败回滚；历史配置回退与关联配置可视。
5. **冲突检测**：下发前检查不同业务对同一配置的冲突；不一致则提示。

### 思考题

1.（简答题）华为 iMaster NCE 业务开放可编程的核心功能包有？

参考答案：网元驱动包（SND）和业务包（SSP）。

2.（多选题）业务包中包含？

- A. 业务 YANG 模型
- B. 设备 YANG 模型
- C. Jinja2 模板
- D. Python 映射脚本

参考答案：A、C、D

### 本章总结

- 网络业务开放可编程是产业发展方向；使能从业者具备开放可编程能力是开放生态基石。
- 用户可通过编写 SND 与 SSP 实现新设备快速对接和新业务快速构建。
- 学习本部分需具备较好的 Python、NETCONF、YANG、Jinja2 等基础。

更多信息：

- 华为云开发者社区“数通网络开放可编程”：https://developer.huaweicloud.com/resource/network.html#AOC
- 《数通网络开放可编程开发指南》《数通网络开放可编程用户指南》
- Jinja2：https://jinja.palletsprojects.com/en/2.11.x/
