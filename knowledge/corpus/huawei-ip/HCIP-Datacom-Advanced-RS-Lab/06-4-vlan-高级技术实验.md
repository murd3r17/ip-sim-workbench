---
doc_id: "hcip-datacom-advanced-rs-lab-06"
title: "4 VLAN 高级技术实验"
book: "HCIP-Datacom-Advanced-RS-Lab"
book_title: "HCIP-Datacom Advanced Routing & Switching V1.0 实验手册"
track: "datacom"
level: "hcip"
series: "datacom-advanced-rs"
doc_type: "lab"
source_pdf: "HCIP-Datacom-Advanced Routing & Switching Technology V1.0 实验手册.pdf"
seq: 6
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 4 VLAN 高级技术实验

## 4.1 VLAN 高级技术

## 4.1.1 实验介绍

4.1.1.1 学习目标

- 实现VLAN 聚合的基本配置
- 实现MUX VLAN 的基本配置
- 实现配置ARP 代理完成Sub-VLAN 之间的通信
- 描述ARP 代理实现Sub-VLAN 间通信的过程

4.1.1.2 实验组网介绍

图4-1 VLAN 高级技术 在S1、S2 上部署VLAN 聚合，指定VLAN 100 为Super-VLAN，在S3 上配置其VLANIF 作 为R1、R2 的网关，指定VLAN 10、20 为Sub-VLAN。 在S2 上部署MUX VLAN，将VLAN 200 配置为Principal VLAN，配置VLAN 201 为Group

```cli
VLAN，VLAN 202 配置为Separate VLAN。

4.1.1.3 实验背景
```

你是公司的网络管理员，为了节省内网的IP 地址空间，你决定在内网部署VLAN 聚合，同时 为了限制不同业务之间的访问，你决定同时部署MUX VLAN。

## 4.1.2 实验任务

4.1.2.1 任务思路

1. 在S1、S3 上完成VLAN 聚合基础配置，配置R1、R2 的接口地址模拟终端用户。
2. 在S3 的Super-VLAN VLANIF 100 接口上开启ARP 代理，观察R1、R2 之间的通信过 程。
3. S1、S2、S3 上配置VLAN 200，用于模拟外部网络与Sub-VLAN 进行通信。
4. S2 上配置MUX VLAN，配置R3、R4 的接口地址用于验证MUX VLAN 隔离效果。

4.1.2.2 任务步骤

步骤 1 VLAN 聚合基本配置 在S1 上创建Sub-VLAN 10、20，将连接R1、R2 的接口分别划分到Sub-VLAN 10、20 中， 在S3 上创建Super-VLAN 100，同时创建VLANIF 100 作为网关。配置S1、S3 互联接口为T runk 接口，放通VLAN 10、20。配置R1、R2 的接口地址，模拟终端用户。

```cli
#设备命名
```

略

```cli
#关闭本实验中未使用的接口
```

略

```cli
#S1 上创建Sub-VLAN

[S1]vlan batch 10 20

#将S1 连接R1、R2 的接口分别划分到Sub-VLAN 10、20 内

[S1]interface GigabitEthernet0/0/1

[S1-GigabitEthernet0/0/1] port link-type access

[S1-GigabitEthernet0/0/1] port default vlan 10

[S1-GigabitEthernet0/0/1] quit

[S1]interface GigabitEthernet0/0/2

[S1-GigabitEthernet0/0/2] port link-type access

[S1-GigabitEthernet0/0/2] port default vlan 20

[S1-GigabitEthernet0/0/2] quit

#S3 上创建Super-VLAN 100，关联Sub-VLAN 10、20（S3 上需要存在VLAN 10、20）

[S3]vlan batch 10 20 100

[S3]vlan 100

[S3-vlan100] aggregate-vlan

[S3-vlan100] access-vlan 10 20

[S3-vlan100] quit

#S3 上创建VLANIF100 作为网关

[S3]interface Vlanif 100

[S3-Vlanif100] ip address 172.16.1.254 24

[S3-Vlanif100] quit

#S1、S3 的互联接口放通VLAN10、20

[S1]interface GigabitEthernet0/0/12

[S1-GigabitEthernet0/0/12] port link-type trunk

[S1-GigabitEthernet0/0/12] port trunk allow-pass vlan 10 20

[S1-GigabitEthernet0/0/12] quit

[S3]interface GigabitEthernet0/0/1

[S3-GigabitEthernet0/0/1] port link-type trunk

[S3-GigabitEthernet0/0/1] port trunk allow-pass vlan 10 20

[S3-GigabitEthernet0/0/1] quit

#配置R1、R2 的接口地址

[R1]interface GigabitEthernet0/0/3

[R1-GigabitEthernet0/0/3] ip address 172.16.1.10 255.255.255.0

[R1-GigabitEthernet0/0/3] quit

[R2]interface GigabitEthernet0/0/4

[R2-GigabitEthernet0/0/4] ip address 172.16.1.20 255.255.255.0

[R2-GigabitEthernet0/0/4] quit

#验证R1、R2 与网关的连通性

<S3>ping -c 1 172.16.1.10 PING 172.16.1.10: 56  data bytes, press CTRL_C to break Reply from 172.16.1.10: bytes=56 Sequence=1 ttl=255 time=110 ms

--- 172.16.1.10 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 110/110/110 ms

<S3>ping -c 1 172.16.1.20 PING 172.16.1.20: 56  data bytes, press CTRL_C to break Reply from 172.16.1.20: bytes=56 Sequence=1 ttl=255 time=80 ms

--- 172.16.1.20 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 80/80/80 ms R1、R2 与网关的连通性正常。
```

步骤 2 观察Sub-VLAN 之间的通信过程 本步骤将会在S3 的VLANIF 100 接口内开启ARP 代理，观察Sub-VLAN 之间的通信过程。

```cli
#R1 上测试与R2 之间的连通性

<R1>ping -c 1 172.16.1.20 PING 172.16.1.20: 56  data bytes, press CTRL_C to break Request time out

--- 172.16.1.20 ping statistics ---

1 packet(s) transmitted

0 packet(s) received
```

100.00% packet loss 此时R1 无法与R2 进行通信。

```cli
#观察R1、S3 的ARP 表项

<R1>display arp all

IP ADDRESS  MAC ADDRESS     EXPIRE(M) TYPE            INTERFACE   VPN-INSTANCE

VLAN/CEVLAN   PVC

------------------------------------------------------------------------------

172.16.1.10    5489-98bf-6225                   I -              GE0/0/3

172.16.1.254   4c1f-ccea-53ea          18        D-0            GE0/0/3

------------------------------------------------------------------------------ Total:2         Dynamic:1      Static:0     Interface:1
```

R1 上此时只能够学习到VLANIF 100 接口地址的ARP 表项。

```cli
<S3>display arp all

IP ADDRESS  MAC ADDRESS     EXPIRE(M) TYPE            INTERFACE   VPN-INSTANCE

VLAN/CEVLAN   PVC

------------------------------------------------------------------------------

172.16.1.254   4c1f-ccea-53ea                   I -               Vlanif100

172.16.1.10    5489-98bf-6225        15        D-0             GE0/0/1

172.16.1.20    5489-982a-0ad0        13        D-0             GE0/0/1

------------------------------------------------------------------------------ Total:3         Dynamic:2      Static:0     Interface:1 S3 上存在R1、R2 的ARP 表项，注意
```

此时VLANIF 100 自身的MAC 地址为4c1f-ccea-53ea 。

```cli
#S3 上开启VLANIF 100 的VLAN 间ARP 代理功能

[S3]interface Vlanif 100

[S3-Vlanif100] arp-proxy inter-sub-vlan-proxy enable

#S3 上开启debugging arp process、debugging arp packet，debugging arp-proxy 观察ARP 代
```

理过程 <S3>terminal debugging <S3>terminal monitor

```cli
<S3>debugging arp process <S3>debugging arp packet <S3>debugging arp-proxy

#R1 上再次测试与R2 的连通性

<R1>ping -c 1 172.16.1.20 PING 172.16.1.20: 56  data bytes, press CTRL_C to break Reply from 172.16.1.20: bytes=56 Sequence=1 ttl=254 time=190 ms

--- 172.16.1.20 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 190/190/190 ms
```

此时R1、R2 之间能够正常通信。

```cli
#查看S3 上debug 输出信息

<S3>
```

```cli
Jul 13 2020 14:44:04.730.1-08:00 S3 ARP/7/arp_rcv:Receive an ARP Packet, operation : 1, sender_eth_addr : 5489- 98bf-6225, sender_ip_addr : 172.16.1.10, target_eth_addr : 0000-0000-0000, target_ip_addr : 172.16.1.20 Jul 13 2020 14:44:04.730.2-08:00 S3 ARP/7/arp_info:ETHARP_ArpInput() Update an ARP entry, IP = 0xa0110ac. Jul 13 2020 14:44:04.730.3-08:00 S3 ARP/7/eth_proxy_reply:The interface Vlanif100 outputs a proxy reply, origin
```

```cli
VLAN ID is 10, type of proxy is inter-sub-vlan-proxy
```

```cli
Jul 13 2020 14:44:04.730.4-08:00 S3 ARP/7/arp_proxy:Send an ARP Proxy Packet, operation : 2, sender_eth_addr : 4c1f-ccea-53ea,sender_ip_addr : 172.16.1.20, target_eth_addr : 5489-98bf-6225, target_ip_addr : 172.16.1.10

Jul 13 2020 14:44:04.840.1-08:00 S3 ARP/7/arp_rcv:Receive an ARP Packet, operation : 1, sender_eth_addr : 5489- 982a-0ad0, sender_ip_addr : 172.16.1.20, target_eth_addr : 0000-0000-0000, target_ip_addr : 172.16.1.10 Jul 13 2020 14:44:04.840.2-08:00 S3 ARP/7/arp_info:ETHARP_ArpInput() Update an ARP entry, IP = 0x140110ac. Jul 13 2020 14:44:04.840.3-08:00 S3 ARP/7/eth_proxy_reply:The interface Vlanif100 outputs a proxy reply, origin
```

```cli
VLAN ID is 20, type of proxy is inter-sub-vlan-proxy
```

```cli
Jul 13 2020 14:44:04.840.4-08:00 S3 ARP/7/arp_proxy:Send an ARP Proxy Packet, operation : 2, sender_eth_addr : 4c1f-ccea-53ea,sender_ip_addr : 172.16.1.10, target_eth_addr : 5489-982a-0ad0, target_ip_addr : 172.16.1.20
#分步骤分析S3 的debug 输出信息
Jul 13 2020 14:44:04.730.1-08:00 S3 ARP/7/arp_rcv:Receive an ARP Packet, operation : 1, sender_eth_addr : 5489- 98bf-6225, sender_ip_addr : 172.16.1.10, target_eth_addr : 0000-0000-0000, target_ip_addr : 172.16.1.20 Jul 13 2020 14:44:04.730.2-08:00 S3 ARP/7/arp_info:ETHARP_ArpInput() Update an ARP entry, IP = 0xa0110ac. Jul 13 2020 14:44:04.730.3-08:00 S3 ARP/7/eth_proxy_reply:The interface Vlanif100 outputs a proxy reply, origin
```

```cli
VLAN ID is 10, type of proxy is inter-sub-vlan-proxy
```

```cli
Jul 13 2020 14:44:04.730.4-08:00 S3 ARP/7/arp_proxy:Send an ARP Proxy Packet, operation : 2, sender_eth_addr : 4c1f-ccea-53ea,sender_ip_addr : 172.16.1.20, target_eth_addr : 5489-98bf-6225, target_ip_addr : 172.16.1.10 S3 收到R1（172.16.1.10）发送的APR 请求，请求解析R2（172.16.1.20）的MAC 地址，S3 通过VLANIF 100 进行ARP 代理，对R1 的ARP 请求进行响应，此时ARP 报文中的源MAC 地址为4c1f-ccea-53ea（VLANIF 100 MAC），源IP 地址为172.16.1.20。
```

R1 收到该ARP 响应之后，发送ICMP 报文，目的IP 为172.16.1.20，目的MAC 为4c1f-ccea- 53ea（VLANIF 100 MAC），S3 收到之后转发该报文。

```cli
Jul 13 2020 14:44:04.840.1-08:00 S3 ARP/7/arp_rcv:Receive an ARP Packet, operation : 1, sender_eth_addr : 5489- 982a-0ad0, sender_ip_addr : 172.16.1.20, target_eth_addr : 0000-0000-0000, target_ip_addr : 172.16.1.10 Jul 13 2020 14:44:04.840.2-08:00 S3 ARP/7/arp_info:ETHARP_ArpInput() Update an ARP entry, IP = 0x140110ac. Jul 13 2020 14:44:04.840.3-08:00 S3 ARP/7/eth_proxy_reply:The interface Vlanif100 outputs a proxy reply, origin
```

```cli
VLAN ID is 20, type of proxy is inter-sub-vlan-proxy
```

```cli
Jul 13 2020 14:44:04.840.4-08:00 S3 ARP/7/arp_proxy:Send an ARP Proxy Packet, operation : 2, sender_eth_addr : 4c1f-ccea-53ea,sender_ip_addr : 172.16.1.10, target_eth_addr : 5489-982a-0ad0, target_ip_addr : 172.16.1.20 R2 收到来自R1 的ICMP 报文，为了能够响应该报文，发送针对R1（172.16.1.20）的ARP 请 求，S3 收到之后通过VLANIF 100 进行ARP 代理，对R2 的ARP 请求进行响应，此时ARP 报文中的源MAC 地址为4c1f-ccea-53ea（VLANIF 100 MAC），源IP 地址为172.16.1.10。
```

至此，R1、R2 上完成ARP 表项的学习，学习到的对端MAC 地址都为S3 VLANIF 100 接口的 MAC 地址。

```cli
#查看R1、R2 的ARP 表项

<R1>display arp all

IP ADDRESS  MAC ADDRESS     EXPIRE(M) TYPE            INTERFACE   VPN-INSTANCE

VLAN/CEVLAN   PVC

------------------------------------------------------------------------------

172.16.1.10    5489-98bf-6225                 I -                GE0/0/3

172.16.1.254   4c1f-ccea-53ea        3         D-0              GE0/0/3

172.16.1.20    4c1f-ccea-53ea        3         D-0              GE0/0/3

------------------------------------------------------------------------------ Total:3         Dynamic:2      Static:0     Interface:1

<R2>display arp all

IP ADDRESS  MAC ADDRESS     EXPIRE(M) TYPE            INTERFACE   VPN-INSTANCE

VLAN/CEVLAN   PVC

------------------------------------------------------------------------------

172.16.1.20    5489-982a-0ad0                 I -                GE0/0/4

172.16.1.254   4c1f-ccea-53ea        2         D-0              GE0/0/4

172.16.1.10    4c1f-ccea-53ea        2         D-0              GE0/0/4

------------------------------------------------------------------------------ Total:3         Dynamic:2      Static:0     Interface:1 R1、R2 上学习到的ARP 表项中对端的MAC 地址都为S3 VLANIF 100 的MAC 地址。
```

步骤 3 配置Sub-VLAN 与其他网络的三层通信

S1、S2、S3 上创建VLAN200，在S3 上创建VLANIF 200，用于模拟Sub-VLAN 与外部网络 的三层通信。

```cli
#创建VLAN200

[S1]vlan 200

[S2]vlan 200

[S3]vlan 200

#在S1、S3 的互联接口上放通VLAN 200

[S3]interface GigabitEthernet0/0/1

[S3-GigabitEthernet0/0/1] port trunk allow-pass vlan 200

[S3-GigabitEthernet0/0/1] quit

[S1]interface GigabitEthernet0/0/12

[S1-GigabitEthernet0/0/12] port trunk allow-pass vlan 200

[S1-GigabitEthernet0/0/12] quit

[S1]interface GigabitEthernet0/0/10

[S1-GigabitEthernet0/0/10] port link-type access

[S1-GigabitEthernet0/0/10] port default vlan 200

[S1-GigabitEthernet0/0/10] quit
```

注意S1 的GE0/0/10 接口配置为Access 模式。

```cli
#在S3 上创建VLANIF 200，并配置IP 地址为172.16.200.xx/24（x 为设备编号）

[S3]interface Vlanif200

[S3-Vlanif200] ip address 172.16.200.33 255.255.255.0

[S3-Vlanif200] quit

#在R1、R2 上配置静态路由前往外部网络

[R1]ip route-static 172.16.200.0 24 172.16.1.254

[R2]ip route-static 172.16.200.0 24 172.16.1.254
```

步骤 4 配置MUX VLAN 在S2 上部署MUX VLAN，配置VLAN 200 为Principal VLAN，配置VLAN 201 为Group

```cli
VLAN，配置VLAN 202 为Separate VLAN，配置R3、R4 的接口地址，验证MUX VLAN 隔
```

离效果。

```cli
#创建VLAN 201、202

[S2]vlan batch 201 202

#配置VLAN 200 为Principal VLAN，VLAN 201 为Group VLAN，VLAN 202 为Separate

VLAN

[S2]vlan 200

[S2-vlan200] mux-vlan

[S2-vlan200] subordinate separate 202

[S2-vlan200] subordinate group 201

[S2-vlan200] quit

#配置接口加入VLAN 并使能MUX VLAN 功能

[S2]interface GigabitEthernet0/0/10

[S2-GigabitEthernet0/0/10] port link-type access

[S2-GigabitEthernet0/0/10] port default vlan 200

[S2-GigabitEthernet0/0/10] port mux-vlan enable

[S2-GigabitEthernet0/0/10] quit

[S2]interface GigabitEthernet0/0/3

[S2-GigabitEthernet0/0/3] port link-type access

[S2-GigabitEthernet0/0/3] port default vlan 201

[S2-GigabitEthernet0/0/3] port mux-vlan enable

[S2-GigabitEthernet0/0/3]quit

[S2]interface GigabitEthernet0/0/4

[S2-GigabitEthernet0/0/4] port link-type access

[S2-GigabitEthernet0/0/4] port default vlan 202

[S2-GigabitEthernet0/0/4] port mux-vlan enable

[S2-GigabitEthernet0/0/4]quit

#检查MUX VLAN 配置结果

[S2]display mux-vlan
```

Principal Subordinate     Type        Interface -----------------------------------------------------------------------------

```cli
200       -            principal     GigabitEthernet0/0/10

200       202         separate      GigabitEthernet0/0/4

200       201         group        GigabitEthernet0/0/3

-----------------------------------------------------------------------------
```

```cli
#配置R3、R4 的接口地址

[R3]interface GigabitEthernet0/0/5

[R3-GigabitEthernet0/0/5] ip address 172.16.200.3 255.255.255.0

[R3-GigabitEthernet0/0/5] quit

[R4]interface GigabitEthernet0/0/5

[R4-GigabitEthernet0/0/5] ip address 172.16.200.4 255.255.255.0

[R4-GigabitEthernet0/0/5] quit

#配置R3、R4 的静态路由，实现与172.16.1.0/24 网段的通信

[R3]ip route-static 172.16.1.0 24 172.16.200.33

[R4]ip route-static 172.16.1.0 24 172.16.200.33

#检查连通性

<R3>ping -c 1 172.16.1.10 PING 172.16.1.10: 56  data bytes, press CTRL_C to break Reply from 172.16.1.10: bytes=56 Sequence=1 ttl=254 time=190 ms

--- 172.16.1.10 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 190/190/190 ms

<R3>ping -c 1 172.16.200.4 PING 172.16.200.4: 56  data bytes, press CTRL_C to break Request time out

--- 172.16.200.4 ping statistics ---

1 packet(s) transmitted

0 packet(s) received
```

100.00% packet loss 属于Group VLAN 的R3 能够通过Principal VLAN 与R1 进行通信，无法与属于Separate

```cli
VLAN 的R4 进行通信。

<R4>ping -c 1 172.16.1.10 PING 172.16.1.10: 56  data bytes, press CTRL_C to break Reply from 172.16.1.10: bytes=56 Sequence=1 ttl=254 time=190 ms

--- 172.16.1.10 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 190/190/190 ms

<R4>ping -c 1 172.16.200.3 PING 172.16.200.3: 56  data bytes, press CTRL_C to break Request time out

--- 172.16.200.3 ping statistics ---

1 packet(s) transmitted

0 packet(s) received
```

100.00% packet loss 属于Separate VLAN 的R4 能够通过Principal VLAN 与R1 进行通信，无法与属于Group

```cli
VLAN 的R3 进行通信。

<R1>ping -c 1 172.16.200.3 PING 172.16.200.3: 56  data bytes, press CTRL_C to break Reply from 172.16.200.3: bytes=56 Sequence=1 ttl=254 time=110 ms

--- 172.16.200.3 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 110/110/110 ms

<R1>ping -c 1 172.16.200.4 PING 172.16.200.4: 56  data bytes, press CTRL_C to break Reply from 172.16.200.4: bytes=56 Sequence=1 ttl=254 time=120 ms

--- 172.16.200.4 ping statistics ---

1 packet(s) transmitted

1 packet(s) received

0.00% packet loss round-trip min/avg/max = 120/120/120 ms R1 能够通过Principal VLAN 与Group VLAN、Separate VLAN 内的R3、R4 进行通信。
```

## 4.1.3 思考题

Super-VLAN 的VLANIF 接口开启VLAN 间ARP 代理之后，在什么情况下会对ARP 请求进行 代理响应？

## 4.1.4 配置参考

R1 设备配置

```cli
sysname R1

interface GigabitEthernet0/0/3

ip address 172.16.1.10 255.255.255.0

ip route-static 172.16.200.0 255.255.255.0 172.16.1.254
```

R2 设备配置

```cli
sysname R2

interface GigabitEthernet0/0/4

ip address 172.16.1.20 255.255.255.0

ip route-static 172.16.200.0 255.255.255.0 172.16.1.254

return
```

R3 设备配置

```cli
sysname R3

interface GigabitEthernet0/0/5

ip address 172.16.200.3 255.255.255.0

ip route-static 172.16.1.0 255.255.255.0 172.16.200.33

return
```

R4 设备配置

```cli
sysname R4

interface GigabitEthernet0/0/5

ip address 172.16.200.4 255.255.255.0

ip route-static 172.16.1.0 255.255.255.0 172.16.200.33

return
```

S1 设备配置

```cli
sysname S1

vlan batch 10 20 200

interface GigabitEthernet0/0/1
```

port link-type access port default vlan 10

```cli
interface GigabitEthernet0/0/2
```

port link-type access port default vlan 20

```cli
interface GigabitEthernet0/0/10
```

port link-type access port default vlan 200

```cli
interface GigabitEthernet0/0/12
```

port link-type trunk port trunk allow-pass vlan 10 20 200

```cli
return
```

S2 设备配置

```cli
sysname S2

vlan batch 200 to 202

vlan 200
```

mux-vlan subordinate separate 202 subordinate group 201

```cli
interface GigabitEthernet0/0/3
```

port link-type access port default vlan 201 port mux-vlan enable

```cli
interface GigabitEthernet0/0/4
```

port link-type access port default vlan 202 port mux-vlan enable

```cli
interface GigabitEthernet0/0/10
```

port link-type access port default vlan 200 port mux-vlan enable

```cli
ip route-static 172.16.1.0 255.255.255.0 172.16.200.3

return
```

S3 设备配置

```cli
sysname S3

vlan batch 10 20 100 200

vlan 100
```

aggregate-vlan access-vlan 10 20

```cli
interface Vlanif100

ip address 172.16.1.254 255.255.255.0
```

arp-proxy inter-sub-vlan-proxy enable

```cli
interface Vlanif200

ip address 172.16.200.33 255.255.255.0

interface GigabitEthernet0/0/1
```

port link-type trunk port trunk allow-pass vlan 10 20 200

```cli
return
```
