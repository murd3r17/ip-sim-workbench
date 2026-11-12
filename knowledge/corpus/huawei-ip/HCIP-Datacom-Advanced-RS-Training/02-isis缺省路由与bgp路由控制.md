---
doc_id: "hcip-datacom-advanced-rs-training-02"
title: "IS-IS缺省路由与BGP路由控制"
book: "HCIP-Datacom-Advanced-RS-Training"
book_title: "HCIP-Datacom Advanced Routing & Switching V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-advanced-rs"
doc_type: "training"
source_pdf: "HCIP-Datacom-Advanced+Routing+&+Switching+Technology+V1.0+培训教材(1).pdf"
seq: 2
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# IS-IS缺省路由与BGP路由控制

## 1. IS-IS 缺省路由

在 IS-IS 中，主要通过以下方式控制缺省路由的生成和发布：

- 在 Level-1-2 设备上控制 Level-1 LSP 中 ATT 位的置位
- 在 Level-1 设备上配置即使收到 ATT 置位也不自动产生缺省路由
- 在 IS-IS 中主动发布缺省路由

ATT（Attachment）由 Level-1-2 路由器产生，指明始发路由器是否与其它区域相连。华为数通产品实际使用其中 1 bit。ATT 只会在 Level-1 LSP 中置位，且仅 Level-1-2 设备会设置，因此相关命令仅对 Level-1-2 生效。

```cli
[Huawei-isis-1] attached-bit advertise { always | never }
```

- `always`：ATT 永远置位，Level-1 设备会生成缺省路由
- `never`：永不置位，避免 Level-1 生成缺省、减小路由表

使 Level-1 不将缺省下发到路由表的两种方式：

- Level-1-2 上 `attached-bit advertise never`
- 相连 Level-1 上 `attached-bit avoid-learning`（针对指定设备）

### 1.1 发布缺省路由

```cli
[Huawei-isis-1] default-route-advertise [ always | match default | route-policy route-policy-name ] [ cost cost | tag tag | [ level-1 | level-1-2 | level-2 ] ] [ avoid-learning ]
```

- `always`：无条件发布缺省，下一跳为自己
- `match default`：路由表存在其他协议或其他 IS-IS 进程缺省时才发布
- `route-policy`：存在满足策略的外部路由才发布，避免路由黑洞
- `cost` / `tag`：开销与标记（tag 需 wide/wide-compatible/compatible）
- `level-1` / `level-2` / `level-1-2`：发布级别；未指定则默认 Level-2
- `avoid-learning`：避免学到其他协议/进程缺省并加入路由表

若在 Level-1 设备配置该命令，只向 Level-1 区域发布，不会发布到 Level-2。

### 1.2 缺省路由配置举例

场景：R1–R2 的 GE0/0/1 运行 OSPF；R2 的 GE0/0/2 与 R3 运行 IS-IS。为使 R3 访问 OSPF 网络，在 R2 的 IS-IS 发布缺省；同理在 R2 的 OSPF 也发布缺省。

```cli
[R2] isis
[R2-isis-1] default-route-advertise always
[R2] ospf
[R2-ospf-1] default-route-advertise always
[R3] display ip routing-table
```

R3 可见 `0.0.0.0/0` 协议为 ISIS-L2，下一跳指向 R2。

## 2. IS-IS 多进程与多实例

- 多进程共用全局路由表；多实例使用 VPN 各自路由表
- 可为指定进程关联一组接口，协议操作限于该组接口
- 创建时可绑定 VPN 实例；删除 VPN 实例时进程一并删除

```cli
[Huawei] isis [ process-id ] [ vpn-instance vpn-instance-name ]
```

`process-id`：1～65535，缺省 1；`vpn-instance-name`：1～31 字符。

## 3. LSP 分片扩展

当 PDU 信息量过大时，路由器生成多个 LSP 分片。LSP Number 为 1 Byte，一个进程最多 256 个分片。

可通过配置虚拟系统 ID，生成虚拟 IS-IS 的 LSP 携带更多信息：

- **初始系统（Originating System）**：实际运行 IS-IS 的路由器
- **系统 ID（Normal System-ID）**：初始系统的系统 ID
- **虚拟系统（Virtual System）**：由附加系统 ID 标识，生成扩展 LSP
- **附加系统 ID**：虚拟系统 ID，域内唯一；每个附加 ID 可再生成 256 个扩展分片
- **24 号 TLV（IS Alias ID TLV）**：表示初始系统与虚拟系统关系

使能分片扩展后，若存在因报文装满丢失的信息，系统会提醒重启 IS-IS；重启后装不下的信息放入虚拟系统 LSP，并通过 24 号 TLV 告知关系。附加系统 ID 与系统 ID 都必须在路由域唯一。

### Mode-1 / Mode-2

- **Mode-1**：虚拟系统参与 SPF；为兼容不支持分片扩展的老版本。虚拟系统邻居指向初始系统且 metric 为最大值减 1；初始系统指向虚拟系统 metric 为 0，保证虚拟系统成为下游。区域地址、过载标志等需与原 LSP 一致。
- **Mode-2**：虚拟系统不参与 SPF；路由器识别 24 号 TLV，知虚拟系统 LSP 属于初始系统。

无论哪种模式，初始系统与虚拟系统的 LSP 零分片都必须包含 IS Alias ID TLV。

```cli
[Huawei-isis-1] lsp-fragments-extend [ [ level-1 | level-2 | level-1-2 ] | [ mode-1 | mode-2 ] ]
[Huawei-isis-1] virtual-system virtual-system-id
```

`virtual-system-id` 格式 `XXXX.XXXX.XXXX`（6 字节）。

## 4. IGP 高级特性思考题与总结

1.（多选）OSPF 有哪些快速收敛机制？A. I-SPF B. LSP 快速扩散 C. 智能定时器 D. OSPF IP FRR  
2.（判断）OSPF Type5 LSA 中 FA 字段一定为 0.0.0.0。  
3.（判断）IS-IS Mode-2 LSP 分片扩展下，虚拟系统不参与 SPF，路由器知道虚拟系统 LSP 属于初始系统。

**本章（IGP）总结要点：** OSPF/IS-IS 支持 PRC/I-SPF、FRR、智能定时器等快速收敛；支持过滤、等价与缺省路由控制；支持多进程隔离；OSPF 用 FA 避免次优；IS-IS 支持 LSP 分片扩展。

---

## 5. BGP 高级特性前言

大型网络中 BGP 路由控制更灵活。路由可携带多个路径属性，可用 AS_Path Filter、Community Filter 等匹配工具，结合路由策略控制收发。本课程介绍 BGP 路由控制、ORF、对等体组、安全特性及路由反射器组网。

### 学习目标

- 在 AS_Path Filter / Community Filter 中使用正则表达式
- 用上述过滤器实现 BGP 路由控制
- 应用 ORF、对等体组
- 实现 BGP 安全基本配置
- 描述路由反射器组网方式

### 课程内容

1. BGP 路由控制  
2. BGP 特性介绍  
3. BGP 路由反射器组网方式  

说明：ACL、IP Prefix List、Filter-Policy、Route-Policy 及 BGP 路径属性基础请参考《HCIP-Datacom-Core Technology》。

## 6. 正则表达式与 AS_Path Filter

正则表达式可检查/获取符合规则的子串，或按规则替换。圆括号可定义范围与优先度，如 `gr(a|e)y` 等价 `gray|grey`。

常见示例：

| 表达式 | 含义 |
| --- | --- |
| `^a.$` | 以 a 开始、任意单字符结束 |
| `^100_` | 以 100 起始的 AS_Path |
| `^100$` | 只匹配 100 |
| `100$\|400$` | 以 100 或 400 结束 |
| `^\(65000\)$` | 只匹配 (65000) |
| `abc*d` / `abc+d` / `abc?d` | c 出现 0 次以上 / 1 次以上 / 0 或 1 次 |
| `[abcd]` | 匹配 a/b/c/d 之一 |
| `[^act]$` | 不以 a/c/t 结束 |

AS_Path 是公认必遵属性，记录路由经过的 AS 号集合（可为 0 个、1 个或多个）。

同一过滤器编号下多条规则为“或”关系：通过任一条即通过该过滤器。默认行为为 deny；若全是 deny，则无路由可通过，需在 deny 后加 permit 放行其余。

```cli
[Huawei] ip as-path-filter { as-path-filter-number | as-path-filter-name } { deny | permit } regular-expression
```

编号 1～256；名称 1～51 字符且不能全数字。

### 配置举例：拒绝始发于 AS101 的路由

```cli
[R2] ip as-path-filter 1 deny _101$
[R2] ip as-path-filter 1 permit .*
```

直接应用到 peer：

```cli
[R2] bgp 102
[R2-bgp] peer 10.1.23.3 as-number 103
[R2-bgp] ipv4-family unicast
```

或经 Route-Policy：

```cli
[R2] route-policy AS_Path permit node 10
[R2-route-policy] if-match as-path-filter 1
[R2-route-policy] quit
[R2] bgp 102
[R2-bgp] peer 10.1.23.3 as-number 103
[R2-bgp] ipv4-family unicast
[R2-bgp-af-ipv4] peer 10.1.23.3 route-policy AS_Path export
```

查看：

```cli
[R2] display ip as-path-filter 1
[R2] display bgp routing-table regular-expression _101$
```

## 7. Community Filter

Community 为可选过渡属性，可按特征标识路由而不必关心零散前缀与繁多 AS 号。

| 团体属性 | 团体号 | 说明 |
| --- | --- | --- |
| Internet | 0 | 可向任何 BGP 对等体发送；缺省所有路由属于 Internet |
| No_Advertise | 0xFFFFFF02 | 不向任何对等体发送 |
| No_Export | 0xFFFFFF01 | 不向 AS 外发送 |
| No_Export_Subconfed | 0xFFFFFF03 | 不向 AS 外发送；联盟内也不向其他子 AS 发布 |

格式：十进制整数，或 `AA:NN`。

```cli
[Huawei-route-policy] apply community { community-number | aa:nn | internet | no-advertise | no-export | no-export-subconfed } [ additive ]
```

```cli
[Huawei] ip community-filter { basic comm-filter-name | basic-comm-filter-num } { permit | deny } [ community-number | aa:nn | internet | no-export-subconfed | no-advertise | no-export ]
[Huawei] ip community-filter { advanced comm-filter-name | adv-comm-filter-num } { permit | deny } regular-expression
```

基本过滤器号 1～99；高级 100～199。

```cli
[Huawei-route-policy] if-match community-filter { basic-comm-filter-num [ whole-match ] | adv-comm-filter-num }
[Huawei-route-policy] if-match community-filter comm-filter-name [ whole-match ]
```

基本过滤器举例：

```cli
ip community-filter 1 permit 100:1 200:1 300:1
ip community-filter 1 permit 100:1
ip community-filter 1 permit 200:1 300:1
```

高级举例：`ip community-filter 100 permit ^10`

### 配置 Community 属性举例

R1 通告 10.1.1.1/32 时携带 `101:1`；R2 向 EBGP 对等体 R3 追加 `no-export`，并 `advertise-community`：

```cli
[R2] ip ip-prefix 1 permit 10.1.1.1 32
[R2] route-policy Community permit node 10
[R2-route-policy] if-match ip-prefix 1
[R2-route-policy] apply community no-export additive
[R2-route-policy] quit
[R2] route-policy Community permit node 20
[R2-route-policy] quit
[R2] bgp 102
[R2-bgp] peer 10.1.23.3 as-number 103
[R2-bgp] peer 10.1.23.3 advertise-community
[R2-bgp] peer 10.1.23.3 route-policy Community export
```

过滤携带 101:1 的路由：

```cli
[R2] ip community-filter 1 permit 101:1
[R2] route-policy Community deny node 10
[R2-route-policy] if-match community-filter 1
[R2-route-policy] quit
[R2] route-policy Community permit node 20
[R2-route-policy] quit
[R2] bgp 102
[R2-bgp] peer 10.1.23.3 route-policy Community export
```

R3 将收不到 10.1.1.1/32。

## 8. ORF、对等体组与安全入门

### 8.1 ORF（Outbound Route Filters）

若本端只想收需要的路由，而对端难为每个邻居维护不同出口策略，可配置基于前缀的 ORF：把本端入口前缀策略经 Route Refresh 发给邻居，邻居据此构造出口策略过滤发送，降低无用路由、CPU 与带宽占用。

```cli
[Huawei-bgp-af-ipv4] peer { group-name | ipv4-address } ip-prefix ip-prefix-name { import | export }
[Huawei-bgp] peer { group-name | ipv4-address } capability-advertise orf [ non-standard-compatible ] ip-prefix { both | receive | send } [ standard-match ]
```

配置举例（R2 只期望 10.1.1.1/32）：

```cli
[R2] ip ip-prefix 1 permit 10.1.1.1 32
[R2] bgp 102
[R2-bgp] peer 10.1.12.1 as-number 101
[R2-bgp] peer 10.1.12.1 ip-prefix 1 import
[R2-bgp] peer 10.1.12.1 capability-advertise orf ip-prefix send
[R1] bgp 101
[R1-bgp] peer 10.1.12.2 as-number 102
[R1-bgp] peer 10.1.12.2 capability-advertise orf ip-prefix receive
```

查看：`display bgp peer 10.1.12.2 orf ip-prefix`；`display bgp routing-table peer 10.1.12.1 received-routes`。

### 8.2 对等体组

Peer Group 是具有相同策略的对等体集合；加入组后获得组配置，组变更时成员同步变更，可简化大型网络配置。组内个体仍可单独配置收发策略。

```cli
[Huawei-bgp] group group-name [ external | internal ]
```

查看：`display bgp group in`。

### 8.3 BGP 安全性概述

常见攻击：建立非法邻居通告非法路由；发送大量非法报文导致 CPU 升高。可用 **MD5/Keychain 认证** 与 **GTSM** 保障交互安全。（详细配置见下一章。）
