---
doc_id: "hcie-datacom-v1.0-training-23"
title: "Telemetry 实践与 OPS 开放可编程"
book: "HCIE-Datacom-V1.0-Training"
book_title: "HCIE-Datacom V1.0 培训教材"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "training"
source_pdf: "HCIE-Datacom+V1.0+培训教材.pdf"
seq: 23
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# Telemetry 实践与 OPS 开放可编程

## Telemetry 静态订阅实践

### 配置思路

拓扑：网络设备 `192.168.56.100`（GE1/0/0）— 采集器（本地 PC）`192.168.56.1`。

| 侧 | 步骤 |
|----|------|
| 设备 | 进入 Telemetry 视图 → 配置推送目标 → 配置采样数据 → 创建静态订阅 |
| 采集器 | 准备并编译 proto 文件 → 编写 Python 代码（导入模块、创建 gRPC 服务器、获取并解码 Telemetry 数据）→ 结果验证 |

### 步骤：设备配置推送

1. 进入 Telemetry 视图。
2. 配置设备推送目标。本例创建目标组 Dest1，推送目标 IP `192.168.56.1`，端口 `20000`。

```cli
<CE1> system-view immediately
[CE1] telemetry
[CE1-telemetry] destination-group Dest1
[CE1-telemetry-destination-group-Dest1] ipv4-address 192.168.56.1 port 20000 protocol gRPC no-tls
```

### 步骤：设备配置采样和静态订阅

3. 配置采样数据：创建采样传感器组并指定采样路径。本例创建采样组 Sensor1，采样路径为 CPU 信息。
4. 创建静态订阅：关联目标组 Dest1 与传感器组 Sensor1，设置采样间隔为 1000 ms。配置完成后设备将持续向目标推送数据。

```cli
[CE1-telemetry] sensor-group Sensor1
[CE1-telemetry-sensor-group-Sensor1] sensor-path huawei-devm:devm/cpuInfos/cpuInfo
[CE1-telemetry] subscription Sub1
[CE1-telemetry-subscription-Sub1] sensor-group Sensor1 sample-interval 1000
[CE1-telemetry-subscription-Sub1] destination-group Dest1
```

> （原图：传感器组与订阅关联界面；采样路径以设备 YANG/产品文档为准。）

### 步骤：采集器编译 proto 文件

Telemetry 将采样数据推送给采集器后，采集器需基于 gRPC 与 GPB 进行对接开发。可在官网下载华为设备发布的 `.proto` 文件。

**公共 proto 文件：**

| 文件 | 用途 |
|------|------|
| huawei-gRPC-dialin.proto | 采集器作为客户端向设备发起 RPC 请求，订阅采样数据（动态订阅） |
| huawei-gRPC-dialout.proto | 设备作为客户端主动向采集器发起 RPC 请求，推送数据（静态订阅） |
| huawei-telemetry.proto | 业务数据之上的 Telemetry 头封装，方便对接 |

**业务 proto 文件：**

- `huawei-xx.proto`：按业务进行 GPB 编解码，例如 `huawei-mac.proto`、`huawei-mpls.proto`、`huawei-devm.proto`。

可通过脚本编译 proto，例如 `run_codegen.py`：

```python
from grpc_tools import protoc

protoc.main((
    "",
    "-I./protos",
    "--python_out=.",
    "--grpc_python_out=.",
    "./protos/huawei-telemetry.proto",
))
protoc.main((
    "",
    "-I./protos",
    "--python_out=.",
    "--grpc_python_out=.",
    "./protos/huawei-gRPC-dialout.proto",
))
protoc.main((
    "",
    "-I./protos",
    "--python_out=.",
    "--grpc_python_out=.",
    "./protos/huawei-devm.proto",
))
```

编译后当前目录会生成例如：

- `huawei_devm_pb2.py` / `huawei_devm_pb2_grpc.py`
- `huawei_grpc_dialout_pb2.py` / `huawei_grpc_dialout_pb2_grpc.py`
- `huawei_telemetry_pb2.py` / `huawei_telemetry_pb2_grpc.py`

说明：

- gRPC 模块可用 `pip install grpcio` / `grpcio-tools` 安装。
- `huawei_grpc_dialout_pb2_grpc`、`huawei_telemetry_pb2` 等为编译 proto 后生成。

### 步骤：编写 Python 代码（采集器侧）

思路：创建 gRPC 服务端，继承 dialout Servicer，实现 `dataPublish`，遍历请求迭代器中的 Telemetry 数据，按 `proto_path` 动态加载对应 `*_pb2` 模块并 `FromString` 解码打印。

示意结构：

```python
import importlib
# 另需导入编译生成的 huawei_grpc_dialout_pb2_grpc、huawei_telemetry_pb2 等

class Telemetry_CPU_Info(huawei_grpc_dialout_pb2_grpc.gRPCDataserviceServicer):
    def __init__(self):
        return

    def dataPublish(self, request_iterator, context):
        for telemetry_data in request_iterator:
            print(telemetry_data)
            print("The proto path is: " + telemetry_data.proto_path)
            module_name = telemetry_data.proto_path.split(":")[0].replace("-", "_")
            root_class = telemetry_data.proto_path.split("/")[-1]
            # 按实际 proto_path 规则解析模块名与根类名
            decode_module = importlib.import_module(module_name + "_pb2")
            for row_data in telemetry_data.data_gpb.row:
                decode_func = getattr(decode_module, root_class).FromString
                print(decode_func(row_data.content))
        return

def serve():
    # 创建 gRPC server，监听 20000，注册 Telemetry_CPU_Info 服务并启动
    pass

if __name__ == "__main__":
    serve()
```

> （原图：完整 Python 采集器代码与类继承关系；以上为 OCR 修复后的结构示意，变量名与服务类名以官方示例为准。）

### 步骤：结果验证

运行脚本后，输出中应成功获得设备 CPU 信息，例如：

```text
cpuInfos {
  cpuInfo {
    entIndex: 16842753
    interval: 8
    ovloadThreshold: 90
    position: "1"
    systemCpuUsage: 6
    unovloadThreshold: 75
  }
}
```

### 思考题

1.（多选题）Telemetry 数据推送有哪几种方式？

- A. TCP
- B. UDP
- C. gRPC

参考答案：B、C

2.（简答题）Telemetry 数据订阅有哪些方式？

参考答案：静态订阅和动态订阅

### Telemetry 本节小结

- Telemetry 是从物理或虚拟设备上高速采集数据的远程技术。
- 狭义 Telemetry 框架分为：数据源、数据生成、数据订阅、数据推送。
- 数据源用 YANG 定义；数据生成用 GPB；订阅分静态/动态；推送用 gRPC 或 UDP。
- 可通过 Python 脚本实现 Telemetry 订阅与数据采样。

更多信息：

- Protobuf：https://developers.google.com/protocol-buffers/
- gRPC：https://www.grpc.io/

---

## OPS（Open Programmability System）开放可编程

### 前言与目标

传统网络设备是封闭系统，功能和服务相对固定。随着多样化、差异化需求增加，用户希望设备提供不同层次开放性，便于自定义功能、私有管理策略与自动化运维。

华为推出 OPS（Open Programmability System，开放可编程系统），提供网络设备开放可编程能力，赋予用户二次开发能力。

学完本部分后，您将能够：

- 描述 OPS 基本概念
- 描述 OPS 基本功能
- 实现 OPS 基本配置

### 基本概念

- 传统设备相对封闭，难以应对灵活多变、差异化的网络管理需求。
- 有了 OPS，用户可按需编写脚本并导入设备运行。
- **VRP**：华为网络操作系统。
- **管理对象**：设备中开放出来、可被 RESTful API 调用的对象，如 CPU 信息、系统信息、接口信息等。
- **URI**（Uniform Resource Identifier）：统一资源标识符；OPS 中用 URI 标识管理对象。例如 CPU 信息 URI：`/devm/cpuInfos/cpuInfo`。
- **URL**（Uniform Resource Locator）：统一资源定位符，是 URI 的一种，还指明如何定位资源。
- 当前华为网络设备 OPS 集成 Python 运行环境；Java、C/C++ 运行环境视版本扩展。
- **API**：应用程序之间为保证互相通讯所提供的规则与要求。
- 更多 RESTful 知识可参考 HCIP 编程与自动化课程《RESTful 原理与实践》。
- OPS 典型用法：用户编写 Python 脚本，安装到设备；脚本运行时发送 HTTP 请求管理设备。

### HTTP 报文基础（OPS 相关）

HTTP 报文承载在 TCP 上。请求/响应报文组成：

- **起始行**：请求中说明要执行的操作；响应中说明执行结果。
- **首部字段**：补充附加信息（如 Host、Content-Type）。
- **主体**：请求中为客户端发送的数据；响应中为服务器返回的数据（HTML、图片等）。

常见首部字段：Host、User-Agent、Accept、Accept-Language、Date、Server、Last-Modified、ETag、Accept-Ranges、Vary、Content-Length、Content-Type 等。详见 RFC 2616。

OPS RESTful API 请求/响应格式与 HTTP 类似。当前 OPS RESTful API 以 XML 传输数据（未来版本可能支持 JSON）。《RESTful API 参考》可在华为 support 网站对应设备页面下载。

**维护助手**：可设置触发条件及条件满足时执行的 Python 脚本；系统实时监控设备，条件满足时自动执行脚本。详见产品文档。

### 自动部署相关组件（概念）

| 组件 | 作用 |
|------|------|
| DHCP 服务器 | 为自动部署设备分配临时管理 IP、缺省网关、脚本文件服务器地址等 |
| DHCP 中继 | 设备与 DHCP 服务器不同网段时转发 DHCP 交互报文 |
| 脚本文件服务器 | 保存自动部署所需 Python 脚本；脚本可获取软件/配置服务器地址、版本与配置文件等信息 |
| 软件和配置文件服务器 | 保存系统软件、配置文件、补丁文件 |

通过编写 Python 脚本，可实现下发命令；网络不通时将结果暂存设备，恢复后再传输到 Server，消减网络中断影响。

### 场景：自动备份配置文件

网络设备通过维护助手订阅配置文件保存事件；配置被保存后自动运行 Python 脚本，将配置文件发送至服务器备份，减少手工备份工作量。

### OPS 配置思路

1. 编写 Python 脚本（最关键）
2. 使用 FTP 等方式将脚本上传到网络设备
3. 安装脚本：`ops install file file-name`
4. 运行脚本：命令行手动运行 `ops run python file-name`，或通过维护助手运行

### Python 脚本编写

脚本作用：向系统下发 HTTP 请求以管理系统。华为提供 Python 脚本模板，用户按功能查找相应 RESTful API 并修改部分代码即可。

模板要点：

- shebang 与编码声明：`#!/usr/bin/env python`、`# -*- coding: utf-8 -*-`
- 导入：`traceback`、`httplib`（或兼容库）、`string` 等
- `OPSConnection` 类：封装建立 HTTP 连接与 RESTful 调用
  - `__init__(host, port=80)`：初始化，创建连接相关参数；headers 通常包含 `Content-type: text/xml`、`Accept: text/xml`
  - `close()`：关闭连接
  - `create(uri, req_data)`：POST，创建设备资源
  - `delete(uri, req_data)`：DELETE，删除设备资源
  - `get(uri, req_data=None)`：GET，查询设备资源
  - `set(uri, req_data)`：PUT，修改设备资源
  - `rest_call(method, uri, req_data)`：内部统一发起 HTTP 请求并打印请求/响应

用户需自行编写业务函数，例如 `get_startup_info(ops_conn)`：

- URI 示例：`/cfg/startupInfos/startupInfo`（获取系统启动信息）
- `req_data` 为 XML 请求体
- 调用 `ops_conn.get(uri, req_data)` 执行 GET
- `main()` 中 `host = "localhost"`（当前 RESTful API 仅支持设备内部调用）

系统启动信息响应 XML 结构示意（字段以产品文档为准）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rpc-reply>
  <data>
    <cfg>
      <startupInfos>
        <startupInfo>
          <position>6</position>
          <nextStartupFile>flash:/vrpcfg.cfg</nextStartupFile>
          <configedSysSoft>flash:/system-software.cc</configedSysSoft>
          <curSysSoft>flash:/system-software.cc</curSysSoft>
          <nextSysSoft>flash:/system-software.cc</nextSysSoft>
          <curStartupFile>flash:/vrpcfg.cfg</curStartupFile>
          <curPatchFile>NULL</curPatchFile>
          <nextPatchFile>NULL</nextPatchFile>
        </startupInfo>
      </startupInfos>
    </cfg>
  </data>
</rpc-reply>
```

| 操作 | URI | 描述 |
|------|-----|------|
| GET | `/cfg/startupInfos/startupInfo` | 获取系统启动信息 |

### 案例：获取设备 CPU 信息

组网：网络管理员 PC `192.168.56.1` — 网络设备 `192.168.56.100`（GE1/0/0）。管理员编写 Python 脚本上传到设备运行以获取 CPU 信息。

#### 查找 API

| 操作 | URI | 描述 |
|------|-----|------|
| GET | `/devm/cpuInfos/cpuInfo` | 获取 CPU 信息 |

请求内容示例：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<cpuInfo>
  <position></position>
  <entIndex></entIndex>
  <systemCpuUsage></systemCpuUsage>
  <ovloadThreshold></ovloadThreshold>
  <unovloadThreshold></unovloadThreshold>
</cpuInfo>
```

响应内容示例：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<cpuInfo>
  <position chassis="1" slot="17">17</position>
  <entIndex>17891329</entIndex>
  <systemCpuUsage>5</systemCpuUsage>
  <ovloadThreshold>95</ovloadThreshold>
  <unovloadThreshold>75</unovloadThreshold>
</cpuInfo>
```

#### 修改脚本关键部分

定义 `get_cpu_info`，URI 使用 `/devm/cpuInfos/cpuInfo`，构造上述 XML 作为 `req_data`，调用 `ops_conn.get`；在 `main()` 中建立 `OPSConnection("localhost")` 并调用该方法。

#### 上传、安装、运行

1. PC 开 FTP 服务，设备作客户端下载 `cpu_demo.py`：

```cli
<CE1> ftp 192.168.56.1
```

按提示输入用户名密码，使用 FTP 获取 `cpu_demo.py`（传输成功后可见 Transfer finished successfully 一类提示）。

2. 安装脚本：

```cli
<CE1> ops install file cpu_demo.py
<CE1> display ops script
```

可见类似：

```text
Index  Size(Byte)  Filename
1      4605        cpu_demo.py
```

3. 运行脚本：

```cli
<CE1> ops run python cpu_demo.py
```

请求示例：

```http
GET /devm/cpuInfos/cpuInfo HTTP/1.1

<?xml version="1.0" encoding="UTF-8"?>
<cpuInfo>
  <position></position>
  <entIndex></entIndex>
  <systemCpuUsage></systemCpuUsage>
  <ovloadThreshold></ovloadThreshold>
  <unovloadThreshold></unovloadThreshold>
</cpuInfo>
```

响应示例（设备有 2 个 CPU）：

```http
HTTP/1.1 200 OK

<?xml version="1.0" encoding="UTF-8"?>
<rpc-reply>
  <data>
    <devm>
      <cpuInfos>
        <cpuInfo>
          <position chassis="1" slot="1">1</position>
          <entIndex>16842753</entIndex>
          <systemCpuUsage>4</systemCpuUsage>
          <ovloadThreshold>90</ovloadThreshold>
          <unovloadThreshold>75</unovloadThreshold>
        </cpuInfo>
        <cpuInfo>
          <position chassis="1" slot="17">17</position>
          <entIndex>17891329</entIndex>
          <systemCpuUsage>4</systemCpuUsage>
          <ovloadThreshold>90</ovloadThreshold>
          <unovloadThreshold>75</unovloadThreshold>
        </cpuInfo>
      </cpuInfos>
    </devm>
  </data>
</rpc-reply>
```

字段含义：

| 字段 | 含义 |
|------|------|
| position | CPU 位置信息 |
| entIndex | CPU 索引信息 |
| systemCpuUsage | CPU 使用率 |
| ovloadThreshold | CPU 过载门限 |
| unovloadThreshold | CPU 去过载门限 |

### 思考题

1.（多选题）OPS 功能通过标准 HTTP 方法访问管理对象，支持的方法有哪些？

- A. GET
- B. PUT
- C. POST
- D. DELETE

参考答案：A、B、C、D

### OPS 本节小结

- OPS 是华为网络设备特有功能，利用 RESTful API，通过标准 HTTP 方法访问设备管理对象。
- 华为提供 Python 脚本模板，用户按功能查找 RESTful API 并修改部分代码即可。

更多信息：

- REST 论文：https://www.ics.uci.edu/~fielding/pubs/dissertation/rest_arch_style.htm
- HTTP/1.1 RFC：https://www.ietf.org/rfc/rfc2616.html
- Python：https://www.python.org
- OPS RESTful API：https://support.huawei.com

---

## SDN / REST / HTTP 概述（开篇）

> 以下为后续“REST/HTTP/RESTful 实践”章节开篇，完整 HTTP 报文与调用实践见下一分册。

### 前言与目标

计算产业开放生态推动多方发展；网络产业中 SDN（Software Defined Networking）备受关注。REST 风格与 RESTful 接口在网络开放中广泛使用。

学完后，您将能够：

- 描述 SDN 发展历史
- 描述 REST 背景、概念及亮点
- 辨别 REST、RESTful、RESTCONF 之间的关系
- 阐明 HTTP 报文格式及内容
- 辨别 HTTP、HTTPS、HTTP/2.0 之间的关系
- 实现基础 RESTful 接口调用

大纲：1. SDN 概述 2. REST 和 RESTful 3. HTTP 工作原理 4. RESTful 接口调用实践

### SDN 要点

- SDN 起源提出了 OpenFlow；随着发展，OpenFlow 成为控制器与交换机之间诸多南向协议之一。
- SDN 是更广泛概念，不局限于 OpenFlow；转控分离是实现方法而非全部本质。

分层：

| 层次 | 说明 |
|------|------|
| 协同应用层 | OSS、OpenStack 等；也可是调用控制器北向接口的安全 APP |
| 控制器层 | SDN 控制器，核心功能是网络业务编排 |
| 设备层 | 接收控制器指令并转发 |
| NBI | 北向接口，主要为 RESTful |
| SBI | 南向接口：NETCONF、SNMP、OpenFlow、OVSDB 等 |

相关系统：云平台（如 OpenStack）、EMS、容器编排（如 Kubernetes）、MTOSI/CORBA、Kafka/SFTP 等。

华为 SDN：管、控、析构建智简网络；iMaster NCE 连接物理网络与商业意图，南向集中管理控制分析，北向开放 API。产品形态包括 NCE-Fabric、NCE-Campus、NCE-WAN、NCE-IP、NCE-T 等。

### REST 背景与概念

北向接口经历 MTOSI、CORBA、SNMP 等到 REST 的演进。REST 规范 URI 命名、面向资源：

| 场景 | 无风格约束 URI | REST 风格 |
|------|---------------|-----------|
| 预约会议室 | `/reserve/meetingroom/B25R` | `/meetingroom/B25R` + POST |
| 取消预约 | `/cancel/meetingroom/B25R` | `/meetingroom/B25R` + DELETE |
| 查询状态 | `/meetingroom/B25R?method=query` | `/meetingroom/B25R` + GET |

- **无状态请求**：服务器处理结果必须全部来自一次请求所携带的信息。
- REST 全称 Representational State Transfer（表现层状态转化），主体是资源。
- CRUD：Create、Read、Update、Delete。
- **表现层**：资源的外在形式（文本/HTML/XML/JSON/二进制等）；URI 定位资源，不代表形式。
- **状态转化**：HTTP 无状态，客户端用 HTTP 动作操作服务器，使服务器发生依赖表现层的状态转化。

**RESTful 与 RESTCONF：**

- RESTful：遵循 REST 设计风格的接口，无强制统一标准，定义相对自由。
- RESTCONF：遵循 REST 风格，且额外遵循 RFC 8040；基于 HTTP 访问 YANG 定义数据。

URI 与 URL：URL 是 URI 的子集；URL 必须是绝对路径，URI 可以是绝对或相对路径。

### HTTP 简介（衔接下文）

HTTP（HyperText Transfer Protocol）是应用层协议，基于 TCP/IP，默认 TCP 80。客户端通常是浏览器；服务器可为 Apache、IIS 等。

相关概念：SPDY、QUIC；Connection: close / keep-alive；MIME Type；HTTP/1.1 维持一段时间 TCP 连接；Cookie 用于状态保持。

> HTTP/1.1 请求与响应报文细节、HTTPS/HTTP2、RESTful Token 调用实践见下一分册。
