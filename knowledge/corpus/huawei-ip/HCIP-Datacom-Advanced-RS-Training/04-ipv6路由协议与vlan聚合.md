---
doc_id: "hcip-datacom-advanced-rs-training-04"
title: "IPv6路由协议与VLAN聚合"
book: "HCIP-Datacom-Advanced-RS-Training"
book_title: "HCIP-Datacom Advanced Routing & Switching V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-advanced-rs"
doc_type: "training"
source_pdf: "HCIP-Datacom-Advanced+Routing+&+Switching+Technology+V1.0+培训教材(1).pdf"
seq: 4
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# IPv6路由协议与VLAN聚合

## 1. OSPFv3 双栈配置续

接口使能 OSPFv3（接上章）：

```cli
[R1] interface gigabitethernet 0/0/1
[R1-GigabitEthernet0/0/1] ospfv3 1 area 1
[R2] interface gigabitethernet 0/0/1
[R2-GigabitEthernet0/0/1] ospfv3 1 area 1
[R2] interface gigabitethernet 0/0/0
[R2-GigabitEthernet0/0/0] ospfv3 1 area 0
[R3] interface gigabitethernet 0/0/1
[R3-GigabitEthernet0/0/1] ospfv3 1 area 0
[R3] interface gigabitethernet 0/0/2
[R3-GigabitEthernet0/0/2] ospfv3 1 area 2
[R4] interface gigabitethernet 0/0/2
[R4-GigabitEthernet0/0/2] ospfv3 1 area 0
[R5] interface gigabitethernet 0/0/2
[R5-GigabitEthernet0/0/2] ospfv3 1 area 2
```

验证：`display ospf peer` / `display ospfv3 peer` 对比邻居与 DR/BDR；`display ospf routing` / `display ospfv3 routing` 对比路径；`display ospf lsdb` 可见 Type1/2/3。

## 2. IS-IS（IPv6）

IS-IS 报文含 Hello、LSP、SNP；变长字段为 TLV。支持 IPv6 时新增：

- **232 号 TLV**：IPv6 Interface Address
- **236 号 TLV**：IPv6 Reachability（含 Metric、U/X/S/R、Prefix Length/Prefix、可选 Sub-TLV）
- **129 号 TLV**：Protocol Supported 中增加 NLPID；IPv4=0xCC，IPv6=0x8E。发布 IPv6 路由必须携带 IPv6 NLPID

### 单拓扑不足与多拓扑

单拓扑要求所有接口同时跑 IPv4/IPv6，不够灵活，也无法用 IPv4 区域连接 IPv6 孤岛。

多拓扑（MT）：域内运行多个独立 IP 拓扑（如 IPv4 与 IPv6），分别做 SPF。MT ID=0 标准 IPv4；MT ID=2 预留给 IPv6。多拓扑 TLV 出现在 IIH 与 LSP 0 分片。

```cli
[Huawei-isis-1] ipv6 enable [ topology { ipv6 | standard } ]
[Huawei-GigabitEthernet0/0/1] isis ipv6 cost { cost | maximum } [ level-1 | level-2 ]
```

- `topology ipv6`：独立 IPv6 拓扑分别 SPF
- `standard`：集成拓扑（缺省）；须保证链路拓扑模式一致

查看：`display isis interface ...`、`display isis peer`、`display isis route ... ipv6`。

### IS-IS 双栈配置举例

区域 49.0001，全部 Level-2；IPv4/IPv6 优选不同路径，IPv6 单独拓扑。

IPv4：

```cli
[R1] isis 1
[R1-isis-1] is-level level-2
[R1-isis-1] network-entity 49.0001.0000.0000.0001.00
[R1] interface gigabitethernet 0/0/1
[R1-GigabitEthernet0/0/1] isis enable 1
[R1] interface gigabitethernet 0/0/2
[R1-GigabitEthernet0/0/2] isis enable 1
[R1-GigabitEthernet0/0/2] isis cost 40 level-2
```

IPv6：

```cli
[R1] isis 1
[R1-isis-1] ipv6 enable topology ipv6
[R1] interface gigabitethernet 0/0/1
[R1-GigabitEthernet0/0/1] isis ipv6 enable 1
[R1-GigabitEthernet0/0/1] isis ipv6 cost 40 level-2
[R1] interface gigabitethernet 0/0/2
[R1-GigabitEthernet0/0/2] isis ipv6 enable 1
```

验证：`display ip routing-table protocol isis` 与 `display ipv6 routing-table protocol isis`，可见 IPv4/IPv6 逻辑拓扑与优选路径不同。

## 3. BGP4+

BGP 通过 NLRI 反映 IPv6 信息。MP-BGP 用地址族区分协议：IPv4 单播/组播、IPv6 单播、VPNv4、VPNv6 等。IPv6 邻居需在 IPv6 单播地址族使能。

Update 可携带 MP_REACH_NLRI / MP_UNREACH_NLRI（AFI/SAFI、下一跳长度与地址、NLRI 前缀等）。

```cli
[Huawei-bgp] ipv6-family [ unicast | vpnv6 | vpn-instance vpn-instance-name ]
[Huawei-bgp-af-ipv6] network ipv6-address prefix-length [ route-policy route-policy-name ]
```

查看：`display bgp ipv6 peer`、`display bgp ipv6 routing-table`。

### BGP 双栈配置举例

AS65001–AS65002 EBGP；同时跑 IPv4 与 IPv6。

```cli
[R1] bgp 65001
[R1-bgp] router-id 10.1.1.1
[R1-bgp] peer 10.1.12.2 as-number 65002
[R1-bgp] ipv4-family unicast
[R1-bgp-af-ipv4] network 10.1.1.1 32
[R1-bgp] peer 2001:DB8:2345:12:2 as-number 65002
[R1-bgp] ipv6-family unicast
[R1-bgp-af-ipv6] peer 2001:DB8:2345:12:2 enable
[R1-bgp-af-ipv6] network 2001:DB8:2345:1:1 128
```

R2 对称配置。抓包 Update 中可见 MP_REACH_NLRI（AFI=IPv6，SAFI=Unicast，下一跳与前缀）。

## 4. IPv6 路由思考题与总结

1.（多选）属于 OSPFv3 的 LSA：A. Router-LSA B. Network-LSA C. Network-Summary-LSA D. Link-LSA  
2.（判断）IS-IS 支持 IPv4 与 IPv6 分别计算最短路径树  

**总结：** IPv6 静态可互通；OSPFv3 为支持 IPv6 的新协议；IS-IS 靠新 TLV；BGP 靠多协议地址族与扩展属性。

---

## 5. VLAN 高级技术前言

园区网常用 VLAN 隔离广播域；VLAN 过多导致地址规划浪费。大型企业还有合作伙伴隔离需求。本课程介绍 **VLAN 聚合、MUX VLAN、QinQ**。

### 学习目标

- 描述 VLAN 聚合、MUX VLAN 应用场景、QinQ 实现方式
- 实现三者配置

### 课程内容

1. VLAN 聚合  
2. MUX VLAN  
3. QinQ  

## 6. VLAN 聚合（Super-VLAN）

传统一 VLAN 一 VLANIF、一子网，子网号/广播/网关不可用且空闲地址难复用，造成浪费。

**VLAN 聚合**：多个 Sub-VLAN 隔离广播域，聚合成逻辑 Super-VLAN，共享同一 IP 子网与缺省网关。

- Super-VLAN：只建三层 VLANIF，不含物理接口；VLANIF 状态取决于所含 Sub-VLAN 物理口状态
- Sub-VLAN：二层隔离广播域，共享网关地址，提高编址灵活性

同 Sub-VLAN 内二层直接通信。不同 Sub-VLAN 属不同广播域，ARP 无法跨域；需在 Super-VLAN 的 VLANIF 开启 **ARP 代理**（`arp-proxy inter-sub-vlan-proxy enable`）才能互通。与外部三层通信时先发往 Super-VLAN 网关再路由。二层 Tag 仍为 Sub-VLAN，设备不会发出 Super-VLAN Tag 报文。

```cli
[Huawei-vlan100] aggregate-vlan
[Huawei-vlan100] access-vlan { vlan-id1 [ to vlan-id2 ] }
[Huawei-vlanif100] arp-proxy inter-sub-vlan-proxy enable
```

注意：Super-VLAN 不能含物理口；VLAN1 不能作 Super-VLAN；加入时 Sub-VLAN 不能已有 VLANIF。

### 配置举例要点

SW1：创建 Sub-VLAN 10/20；Trunk 放行；VLAN100 `aggregate-vlan` + `access-vlan 10 20`；VLANIF100 配网关并开代理；Server 侧 VLAN200 Access。SW2/SW3 Access 接 PC 到对应 Sub-VLAN，上联 Trunk。

（MUX VLAN / QinQ 详见下一章。）
