---
doc_id: "hcip-datacom-advanced-rs-training-05"
title: "MUX VLAN、QinQ与以太网交换安全"
book: "HCIP-Datacom-Advanced-RS-Training"
book_title: "HCIP-Datacom Advanced Routing & Switching V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-advanced-rs"
doc_type: "training"
source_pdf: "HCIP-Datacom-Advanced+Routing+&+Switching+Technology+V1.0+培训教材(1).pdf"
seq: 5
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# MUX VLAN、QinQ与以太网交换安全

## 1. MUX VLAN（续）

Separate VLAN / Group VLAN 都必须与 Principle VLAN 绑定。Principal 接口可与 MUX VLAN 内所有接口通信。

典型应用：部门 A/B 为 Group VLAN（组内互通、组间隔离），访客为 Separate VLAN（仅能访服务器），服务器口为 Principal VLAN。

接口需 `port mux-vlan enable` 后策略才生效。

### 配置举例

```cli
[SW1] vlan batch 10 20 30 100
[SW1] vlan 100
[SW1-vlan100] mux-vlan
[SW1-vlan100] subordinate group 10 20
[SW1-vlan100] subordinate separate 30
[SW1] interface GigabitEthernet0/0/1
[SW1-GigabitEthernet0/0/1] port link-type access
[SW1-GigabitEthernet0/0/1] port default vlan 10
[SW1-GigabitEthernet0/0/1] port mux-vlan enable
```

实验要求：Server 与所有主机二层互通；部门 A/B/访客相互不互通；A、B 组内互通；访客组内不互通。

验证：`display vlan`；访客区 PC5 ping PC6 应不通。

## 2. QinQ

802.1Q VLAN ID 仅 12 bit（4096），城域网不够用。QinQ（802.1Q in 802.1Q）在已有 Tag 外再加一层 Tag，扩展 VLAN 空间。公网按外层 Tag 转发；内层为私网 Tag。

TPID：内层通常 0x8100；外层华为缺省 0x8100，802.1ad 规定 0x88A8，可用命令调整。

不同企业私网 VLAN 可重叠，靠不同公网外层 VLAN 隔离；对端 PE 剥离公网 Tag 后交给 CE。

### 基本 QinQ vs 灵活 QinQ

- **基本 QinQ（端口）**：入端口统一打缺省 VLAN 外层 Tag；方式固定，难按业务区分
- **灵活 QinQ（Selective）**：按内层 VLAN、802.1p、MAC、IP、端口等流分类选择外层 Tag

灵活 QinQ 建议接口 Hybrid，先 `qinq vlan-translation enable`；仅入方向生效。VLAN Stacking 发送时若需剥外层 Tag，接口以 Untagged 加入 stack-vlan，否则 Tagged。

### 基本 QinQ 配置举例

```cli
[SW1] vlan batch 100 200
[SW1] interface GigabitEthernet 0/0/1
[SW1-GigabitEthernet0/0/1] port link-type dot1q-tunnel
[SW1-GigabitEthernet0/0/1] port default vlan 100
[SW1] interface GigabitEthernet 0/0/2
[SW1-GigabitEthernet0/0/2] port link-type dot1q-tunnel
[SW1-GigabitEthernet0/0/2] port default vlan 200
[SW1] interface GigabitEthernet 0/0/3
[SW1-GigabitEthernet0/0/3] port link-type trunk
[SW1-GigabitEthernet0/0/3] port trunk allow-pass vlan 100 200
[SW1-GigabitEthernet0/0/3] qinq protocol 9100
```

企业 1/2 用重叠私网 VLAN，公网分别用 100/200。

### 灵活 QinQ 配置举例

```cli
[SW1] vlan batch 2 3
[SW1] interface GigabitEthernet 0/0/1
[SW1-GigabitEthernet0/0/1] port link-type hybrid
[SW1-GigabitEthernet0/0/1] qinq vlan-translation enable
[SW1-GigabitEthernet0/0/1] port vlan-stacking vlan 100 stack-vlan 2
[SW1-GigabitEthernet0/0/1] port vlan-stacking vlan 300 stack-vlan 3
[SW1] interface GigabitEthernet 0/0/2
[SW1-GigabitEthernet0/0/2] port link-type trunk
[SW1-GigabitEthernet0/0/2] port trunk allow-pass vlan 2 3
```

上网用户内层 VLAN100→外层 2；VoIP 内层 300→外层 3。

## 3. VLAN 高级技术思考题与总结

1. Sub-VLAN 与外部二层通信时出接口 Tag 为？→ Sub-VLAN  
2. QinQ 描述错误项：公网按内层 Tag 转发（错误）  

**总结：** VLAN 聚合靠 Super/Sub 与 ARP 代理；MUX VLAN 分 Principal/Group/Separate；QinQ 扩展 VLAN 并透传私网 Tag。

---

## 4. 以太网交换安全前言

针对 ARP、DHCP 等攻击需加强交换安全。内容包括：端口隔离、端口安全、MAC 漂移检测、风暴控制、端口限速、MAC 表安全、DHCP Snooping、IP Source Guard 等。

### 课程大纲

1. 端口隔离  
2. MAC 地址表安全  
3. 端口安全  
4. MAC 地址漂移防止与检测  
5. MACsec  
6. 交换机流量控制  
7. DHCP Snooping  
8. IP Source Guard  

## 5. 端口隔离

同一 VLAN 内端口也可隔离：加入隔离组即二层隔离，更灵活地节省 VLAN。

```cli
[Huawei-GigabitEthernet0/0/1] port-isolate enable [ group group-id ]
[Huawei] port-isolate mode { l2 | all }
[Huawei-GigabitEthernet0/0/1] am isolate { interface-type interface-number }&<1-8>
```

- 缺省未使能；未指定 group 则加入组 1
- `l2`：二层隔离三层互通（缺省）；`all`：二三四层都隔离
- 单向隔离：A 配隔离 B 后，A→B 不通，B→A 可通
- 二层隔离三层互通时，VLANIF 上可配 `arp-proxy inner-sub-vlan-proxy enable`

查看：`display port-isolate group { group-id | all }`。

## 6. MAC 地址表安全

二层按目的 MAC 查表转发；无表项则 VLAN 内广播。可配置：

- **静态 MAC**：防关键设备表项被恶意修改
- **黑洞 MAC**：丢弃匹配源/目的 MAC 的报文
- **老化时间**：及时清除废弃动态表项
- **关闭学习** / **限制学习数量**：防表项爆炸与攻击

```cli
[Huawei] mac-address static mac-address interface-type interface-number vlan vlan-id
[Huawei] mac-address blackhole mac-address [ vlan vlan-id ]
[Huawei] mac-address aging-time aging-time
[Huawei-GigabitEthernet0/0/1] mac-address learning disable [ action { discard | forward } ]
[Huawei-vlan2] mac-address learning disable
[Huawei-GigabitEthernet0/0/1] mac-limit maximum max-num
[Huawei-GigabitEthernet0/0/1] mac-limit action { discard | forward }
[Huawei-GigabitEthernet0/0/1] mac-limit alarm { disable | enable }
```

VLAN 基禁止学习优先级高于接口。配置举例：上行口禁学；用户口限学 100 并告警丢弃。验证：`display mac-limit`。

## 7. 端口安全

将动态学习转为安全 MAC（安全动态 / 安全静态 / Sticky），限制学习数量并配置越限动作，阻止非法用户经本口通信。

保护动作 `port-security protect-action`：

- `protect`：丢弃未知源 MAC 报文
- `restrict`：丢弃并告警
- `shutdown`：error-down 并告警

可使能 Sticky MAC，保存后表项不因重启轻易丢失。error-down 默认可手动 `restart`；也可 `error-down auto-recovery cause port-security interval ...` 自动恢复。

查看：`display mac-address security`、`display mac-address sticky`。

## 8. MAC 地址漂移

同 VLAN 两端口学到同一 MAC、后学覆盖先学，常意味环路或攻击。可通过学习优先级、禁止同优先级漂移、基于 VLAN/全局漂移检测及阻断/退 VLAN 等处理。

```cli
[Huawei-GigabitEthernet0/0/1] mac-learning priority priority-id
[Huawei] undo mac-learning priority priority-id allow-flapping
[Huawei-vlan2] mac-address flapping detection
```

华为默认开启全局漂移检测。验证：`display mac-address flapping record`。

## 9. MACsec

802.1AE：链路逐跳加密，提供完整性检查、用户数据加密、源真实性校验、重放保护。关键术语：CAK、MKA、SAK、Key Server。典型部署于接入与汇聚/核心之间，或经传输设备的交换机链路。

## 10. 流量抑制入门

通过阈值限制广播、未知组播、未知单播、已知组播/单播速率，防泛洪与冲击；也可对 ICMP 限速。出方向可对 BUM 阻塞。

```cli
[Switch] suppression mode by-packets
```

（具体接口抑制命令与风暴控制见下一章。）
