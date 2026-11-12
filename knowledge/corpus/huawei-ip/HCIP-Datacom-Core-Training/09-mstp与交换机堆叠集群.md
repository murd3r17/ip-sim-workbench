---
doc_id: "hcip-datacom-core-training-09"
title: "MSTP原理配置与交换机堆叠集群"
book: "HCIP-Datacom-Core-Training"
book_title: "HCIP-Datacom-Core Technology V1.0 培训教材"
track: "datacom"
level: "hcip"
series: "datacom-core"
doc_type: "training"
source_pdf: "HCIP-Datacom-Core+Technology+V1.0+培训教材(1).pdf"
seq: 9
vendor: huawei
language: zh
quality: "ocr-mixed"
ingest: true
---

# MSTP原理配置与交换机堆叠集群

## MSTI 特点

- 每个 MSTI 独立计算自己的生成树，互不干扰。
- 每个 MSTI 的生成树计算方法与 RSTP 基本相同。
- 每个 MSTI 的生成树可以有不同的根、不同的拓扑。
- 每个 MSTI 在自己的生成树内发送 BPDU。
- 每个 MSTI 的拓扑通过命令配置决定。
- 每个端口在不同 MSTI 上的生成树参数可以不同。
- 每个端口在不同 MSTI 上的角色、状态可以不同。

根桥和备份根桥：

- 可通过计算自动确定生成树的根桥，也可手动配置设备为指定生成树的根桥或备份根桥。
- 设备在各生成树中的角色互相独立；在同一棵生成树中，一台设备不能既作为根桥又作为备份根桥。
- 在一棵生成树中，生效的根桥只有一个；当两台或两台以上设备被指定为同一棵生成树的根桥时，系统将选择 MAC 地址最小的设备作为根桥。
- 可以在每棵生成树中指定多个备份根桥；根桥故障或关机时，备份根桥可取代根桥；若配置了新的根桥，则备份根桥不会成为根桥。若配置了多个备份根桥，则 MAC 地址最小的备份根桥将成为指定生成树的根桥。

## MSTP 网络数据转发

在运行 MSTP 协议的网络中，一个 VLAN 报文将沿着如下路径进行转发：

- 在 MST 域内，沿着其对应的 MSTI 转发。
- 在 MST 域间，沿着 CST 转发。

> （原图：多个 MST Region；VLAN1→MSTI1、VLAN2→MSTI2、Other VLANs→MSTI3；以 VLAN2 数据跨域访问为例）

## MSTP 基本概念小结

| 角色 | 说明 |
| --- | --- |
| MST 域 | 交换网络被划分成多个域；同属一个 MST 域的交换机必须配置相同的域名、相同的修订级别、以及相同的 VLAN 映射表 |
| MSTI | 基于 Instance 的生成树 |
| VLAN 映射表 | VLAN 和 MSTI 之间的映射关系 |
| CST | 公共生成树，连接所有 MST 域的一棵生成树 |
| IST | 内部生成树，MST 域内 Instance ID 为 0 的一棵生成树 |
| CIST | 公共和内部生成树，连接一个交换网络内所有交换设备的生成树（各域 IST + CST） |
| SST | 单生成树（域内仅一台设备，或设备只能属于一个生成树） |
| 总根 | CIST 的根桥 |
| IST 域根 | MST 域中，IST 距离总根最近的交换设备 |
| MSTI 域根 | MSTI 的根桥 |
| 主桥 | 距离总根最近的交换设备，包括总根和 IST 域根 |

同一 MST 域设备特点：都启动了 MSTP；具有相同的域名；具有相同的 VLAN 到生成树实例映射配置；具有相同的修订级别配置。IST 缺省存在，缺省时华为交换机上所有 VLAN 都映射到 Instance 0。每个 VLAN 只能对应一个 MSTI，而一个 MSTI 可能对应多个 VLAN。

### MSTP 端口角色

除边缘端口外，其他端口角色都参与生成树的计算过程。同一端口在不同的生成树实例中可以担任不同的角色。

MSTP 中定义的端口角色包括：根端口、指定端口、Alternate 端口、Backup 端口、Master 端口、域边缘端口和边缘端口。

- **Master 端口**：MST 域和总根相连的所有路径中最短路径上的端口；是域中报文去往总根的必经之路。Master 端口是特殊域边缘端口，在 CIST 上的角色是 Root Port，在其它各实例上的角色都是 Master 端口。
- **域边缘端口**：位于 MST 域的边缘并连接其它 MST 域或 SST 的端口。
- **边缘端口**：位于整个域的边缘、不再与任何交换设备连接的端口，一般与用户终端设备直接连接。

## MSTP 工作原理要点

优先级向量比较原则：同一向量比较，值最小的向量具有最高优先级。比较顺序：根交换设备 ID → 外部路径开销 → 域根 ID → 内部路径开销 → 指定交换设备 ID → 指定端口 ID → 接收端口 ID。

CIST 计算：经过比较 MST BPDU 消息后，在整个网络中选择一个优先级最高的交换设备作为 CIST 的树根（总根）。在每个 MST 域内，MSTP 通过计算生成 IST；同时将每个 MST 域作为单台交换设备对待，通过计算在 MST 域间生成 CST。CST 和 IST 构成整个交换设备网络的 CIST。

## MSTP 基本配置命令要点

- STP/RSTP/MSTP 模式切换：工作在 MSTP 模式下时，与运行 STP 的设备直连端口可工作在 STP 模式以实现互通；与 RSTP 可互相识别报文。
- 配置 MST 域：域名、修订级别、VLAN 到实例映射。缺省情况下，MST 域三个参数均取缺省值。域名：字符串，不支持空格，区分大小写。实例编号：整数，取值为 0 表示 IST。
- 修订级别：整数形式；若厂商设备修订级别不为 0，为保持域内计算一致，部署时需将各设备修订级别修改为一致。
- 配置实例根桥 / 备份根桥：`stp instance instance-id root { primary | secondary }`；配置为根桥后优先级自动为 0，备份根桥优先级自动为 4096，且不能再更改设备优先级。
- 配置设备优先级、路径开销计算方法、端口优先级等与 RSTP 类似，可按实例配置。

## 案例：单域多实例场景配置

目标示意：可将 SW1 配置为 VLAN2 的网关、SW2 配置为 VLAN3 的网关，最终实现不同 VLAN 流量走不同上行链路。

映射关系示例：

- VLAN2 → MSTI 1
- VLAN3 → MSTI 2

### 1. 配置基于接口划分 VLAN

SW1 配置示例：

```cli
[SW1] vlan batch 2 to 3
[SW1] interface GigabitEthernet 0/0/1
[SW1-GigabitEthernet0/0/1] port link-type trunk
[SW1-GigabitEthernet0/0/1] port trunk allow-pass vlan 2 to 3
[SW1-GigabitEthernet0/0/1] quit
[SW1] interface GigabitEthernet 0/0/2
[SW1-GigabitEthernet0/0/2] port link-type trunk
[SW1-GigabitEthernet0/0/2] port trunk allow-pass vlan 2 to 3
[SW1-GigabitEthernet0/0/2] quit
```

注：SW2 与 SW1 配置类似。

SW3 配置示例（含 Access 接终端）：

```cli
[SW3] vlan batch 2 to 3
[SW3] interface GigabitEthernet 0/0/1
[SW3-GigabitEthernet0/0/1] port link-type trunk
[SW3-GigabitEthernet0/0/1] port trunk allow-pass vlan 2 to 3
[SW3-GigabitEthernet0/0/1] quit
[SW3] interface GigabitEthernet 0/0/2
[SW3-GigabitEthernet0/0/2] port link-type trunk
[SW3-GigabitEthernet0/0/2] port trunk allow-pass vlan 2 to 3
[SW3-GigabitEthernet0/0/2] quit
[SW3] interface Ethernet 0/0/1
[SW3-Ethernet0/0/1] port link-type access
[SW3-Ethernet0/0/1] port default vlan 2
[SW3-Ethernet0/0/1] quit
```

注：SW4 与 SW3 配置类似。

### 2. 配置 MST 域与实例映射

注意：缺省情况下，设备上的 STP 功能处于启用状态。若未开启，可使用 `stp enable` 使能交换设备或端口上的 STP 功能。

（域配置命令按产品手册配置域名、修订级别、VLAN 映射到实例 1/2。）

### 3. 配置 MSTI1 与 MSTI2 的根桥和备份根桥

```cli
[SW1] stp instance 1 root primary
[SW2] stp instance 1 root secondary
[SW1] stp instance 2 root secondary
[SW2] stp instance 2 root primary
```

### 4. 将与终端相连的端口设置为边缘端口

```cli
[SW3] interface Ethernet 0/0/1
[SW3-Ethernet0/0/1] stp edged-port enable
[SW3-Ethernet0/0/1] quit
```

### 5. 验证配置结果

```cli
[SW1] display stp brief
[SW2] display stp brief
[SW3] display stp brief
[SW4] display stp brief
```

输出中关注各实例下端口 Role（DESI/ROOT/ALTE）与 STP State（FORWARDING/DISCARDING）。

### 思考题（MSTP）

1. （单选题）某运行 MSTP 的交换机端口角色显示 GigabitEthernet0/0/1 在 Instance1 中为 ALTE，其端口状态应该是？Blocking / Discarding / Forwarding / Learning
2. （判断题）CIST 是由内部生成树和公共生成树构成的一棵树。

参考：1. B（Discarding）；2. A（正确）。

### 本章总结（MSTP）

- 在 MSTP 网络中，可以将一个或多个 VLAN 映射到一个 Instance，然后 MSTP 基于该 Instance 计算生成树。基于 Instance 的生成树被称为 MSTI，映射到同一个 Instance 的 VLAN 将共享同一棵生成树。
- 部署 MSTP 后可：形成多棵无环路的树，解决广播风暴并实现冗余备份；多棵生成树在 VLAN 间实现负载均衡，不同 VLAN 的流量按照不同的路径转发。

## 交换机堆叠与集群

### 前言与目标

随着企业网络规模扩大，对可靠性、故障恢复时间、易管理提出更高要求。传统园区网高可靠技术切换时间很难做到毫秒级，且一主一备存在资源浪费；设备增多使管理更复杂。堆叠、集群技术用于构建可靠、易管理、资源利用率高、易于扩展的交换网络。

学完后应能够：描述堆叠、集群基本概念；阐述建立过程；阐述分裂检测技术原理。

### 堆叠、集群简介

- **堆叠（iStack）**：将多台支持堆叠特性的交换机通过堆叠线缆连接在一起，从逻辑上虚拟成一台交换设备，作为一个整体参与数据转发。
- **集群（CSS）**：将两台支持集群特性的交换机设备组合在一起，从逻辑上虚拟成一台交换设备。
- 集群只支持两台设备，一般高端框式交换机支持 CSS、盒式设备支持 iStack。
- 通过堆叠、集群技术结合链路聚合可以简单构建高可靠、无环的园区网络。

一般接入、汇聚层盒式交换机采用堆叠技术，汇聚、核心层交换机采用集群技术。在逻辑交换机之间使用链路聚合，无需部署 STP、VRRP 即可实现高可靠性，链路可同时传输流量，利用率提升。

### 堆叠、集群的优势

1. **提高资源利用率**：核心设备虚拟化为一台逻辑设备同时转发；汇聚到核心的所有链路使用链路聚合均参与转发。
2. **降低规划与管理复杂度**：逻辑设备之间使用链路聚合，无需再部署 STP、VRRP；只需管理虚拟化之后的逻辑设备。
3. **降低故障业务中断时间**：单台设备故障、链路故障时，流量被链路聚合负载分担到其他链路，业务几乎感知不到中断。

### 堆叠基本概念

成员交换机按功能分为：

- **主交换机（Master）**：负责管理整个堆叠，系统中只有一台。
- **备交换机（Standby）**：主交换机的备份；主故障时接替所有业务，系统中只有一台。
- **从交换机（Slave）**：用于业务转发，可有多台；数量越多转发带宽越大。备不可用时，从可承担备角色。

**堆叠优先级**：成员交换机属性，主要用于角色选举，优先级值越大优先级越高，当选为主交换机的可能性越大。

**堆叠 ID**：成员交换机的槽位号（Slot ID），用来标识和管理成员交换机，堆叠中所有成员交换机的堆叠 ID 都是唯一的。设备堆叠 ID 缺省为 0。建议提前规划好设备的堆叠 ID。

每台交换机支持两个逻辑堆叠端口：`stack-port n/1` 和 `stack-port n/2`，其中 n 为成员交换机的堆叠 ID。如果两端设备对应的逻辑堆叠端口（本端 stack-port n/1 与对端 stack-port m/2）内包含多个物理成员端口，对物理成员端口的连接无对应端口号的要求。

### 堆叠系统组建过程

1. 物理连接（选择连接方式和拓扑）
2. 主交换机选举
3. 拓扑收集和备交换机选举、分配堆叠 ID
4. 软件和配置同步，进入稳定运行

连接拓扑：

- **链形连接**：成员距离较远时可用；可靠性较低，一条堆叠链路故障可能导致堆叠断开。
- **环形连接**：成员距离较近时建议使用；一条堆叠链路故障后环形变链形，不影响堆叠正常工作。

主交换机选举规则（依次）：

1. 运行状态比较：已经运行的交换机比处于启动状态的交换机优先
2. 堆叠优先级高的优先
3. 优先级相同时，MAC 地址小的优先

堆叠主交换机选举超时时间为 20s。备交换机选举：除主外最先完成启动者优先；同时完成启动时比较优先级，再比较 MAC。

软件与配置同步：堆叠具有自动加载系统软件功能，成员版本只需兼容；配置文件同步使多台设备像一台设备工作。堆叠配置文件包括全局配置与接口配置；离开堆叠后堆叠相关配置仍会存在，彻底清除需手动执行清除命令（会导致设备重启）。

### 堆叠合并、分裂与 MAD

- **堆叠合并**：两个堆叠系统通过堆叠线缆连在一起，竞选新主交换机并更新拓扑；竞争失败侧成员重启以从角色加入，业务中断。
- **堆叠分裂**：稳定运行的堆叠中带电移出部分成员，或堆叠线缆多点故障导致一个堆叠变成多个堆叠。
- 堆叠系统 MAC 通常使用主交换机 MAC；主离开后缺省延时 10 分钟切换，期间分裂系统可能 MAC 相同。
- **MAD（Multi-Active Detection）**：分裂后通过 MAD 检测线缆发送 MAD 检测报文竞选；失败方关闭所有物理端口（保留端口除外），避免 IP/MAC 冲突导致业务异常。

MAD 竞争原则类似主选举：先比较启动时间（差在 20 秒内视为相同），再比较主交换机优先级，再比较系统 MAC。

检测方式：直接连接、经中间设备、Full-mesh、代理检测等。代理检测正常运行时以 30s 为周期发送 MAD 报文；分裂后以 1s 为周期发送。

冲突处理结果：

- **Detect**：竞争成功，正常工作
- **Recovery**：竞争失败，禁用状态，关闭除保留端口外的所有物理端口

### 跨设备链路聚合与本地优先转发

堆叠支持跨设备链路聚合：Eth-Trunk 成员接口可分布在不同成员交换机上，实现链路间和设备间备份。跨成员设备流量会经过堆叠线缆，流量较大时增加堆叠线缆带宽压力。可开启**流量本地优先转发**：本设备进入的流量优先从本地转发出去，本地无出接口或出接口全部故障时才从其它成员交换机转发出去。

### 集群（CSS）要点

CSS 与 iStack 功能类似，一般框式称 CSS、盒式称堆叠。

- 缺省集群 ID 为 1；相同 ID 的两台交换机不能建立集群，建立前需手工将一台配置为 2。
- 集群优先级越高当选为主的可能性越大，但选举不止比较优先级。
- 业务口集群组网：1+0（单逻辑集群端口、单业务板）与 1+1（两逻辑集群端口、两业务板备份）。
- **CSS2**：交换网板上通过集群卡建立的交换网硬件集群，支持集群主控 1+N 备份；转控分离架构下，单框无正常工作主控板不影响该框流量转发。

### 堆叠配置要点

```cli
[Huawei] interface stack-port member-id/port-id
[Huawei-stack-port0/1] port interface interface-type interface-number1 [ to interface-type interface-number2 ] enable
[Huawei] stack slot slot-id renumber new-slot-id
[Huawei] stack slot slot-id priority priority
[Huawei-GigabitEthernet0/0/1] mad detect mode direct
[Huawei] interface eth-trunk trunk-id
[Huawei-Eth-Trunk1] mad detect mode relay
[Huawei-Eth-Trunk1] mad relay
[Huawei] mad domain domain-id
[Huawei] slave switchover
[Huawei] stack timer mac-address switch-delay delay-time
[Huawei] reset stack configuration
```

缺省：堆叠 ID 为 0；堆叠优先级为 100；MAD 域值为 0；系统 MAC 切换时间为 10 分钟（设为 0 表示不切换）。

环形堆叠案例要点：本设备的 `stack-port0/1` 必须连接邻设备的 `stack-port0/2`，否则堆叠组建不成功；配置堆叠 ID/优先级后需 save，下电连线后再上电生效。

### 集群配置要点

```cli
[Huawei] set css id new-id
[Huawei] interface css-port port-id
[Huawei-css-port1] port interface { interface-type interface-number1 [ to interface-type interface-number2 ] } &<1-10> enable
[Huawei] set css priority priority
[Huawei] css enable
[Huawei] set css mode { lpu | css-card }
```

使能集群功能后系统会提示立即重启使配置生效，需在两台成员上分别使能。

### 思考题要点（堆叠/集群）

1. 堆叠加入 vs 堆叠合并：未上电通过线缆连入已有堆叠并上电→加入（只能成从）；两套已运行堆叠互连→合并（重新竞选主）。
2. MAD 作用：防止分裂后相同 IP/MAC 造成表项冲突；失败方关闭除保留端口外所有端口。
3. CSS2 支持 1+N 主控备份：整个集群只要有一个主控板工作，控制平面正常时数据平面可正常转发。

### 本章总结（堆叠/集群）

- 堆叠、集群简化网络部署与管理，快速构建高可靠无环园区网，降低故障影响时间。
- 配置 MAD 检测（直连或代理）；竞争失败方关闭非保留物理端口。
- 部署 Eth-Trunk 时尽量开启本地优先转发，避免跨框流量。
- CSS2 通过交换网板集群卡结合转控分离实现主控 1+N 备份。
