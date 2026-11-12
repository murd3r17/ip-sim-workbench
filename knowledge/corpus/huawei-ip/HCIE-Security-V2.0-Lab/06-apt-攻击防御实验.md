---
doc_id: "hcie-security-v2.0-lab-06"
title: "APT 攻击防御实验"
book: "HCIE-Security-V2.0-Lab"
book_title: "HCIE-Security V2.0 实验手册"
track: "security"
level: "hcie"
series: "security-v2"
doc_type: "lab"
source_pdf: "HCIE-Security V2.0 实验手册.pdf"
seq: 6
vendor: huawei
language: zh
quality: "high"
ingest: true
---
# APT 攻击防御实验

## 9.1 实验介绍

## 9.1.1 关于本实验

某公司园区网络中部署了服务器区域，为保护服务器免受APT 攻击，在园区网络中部署了 FireHunter 设备（沙箱）与防火墙进行联动。当攻击者向企业内网发起APT 攻击时，防火墙 从网络流量中识别并提取需要进行APT 检测的文件发送给沙箱。沙箱进行威胁检测，然后将 检测结果返回给防火墙实施阻断操作，防止该文件进入企业内网，保护企业内网免遭攻击。

## 9.1.2 实验目的

-  了解APT 攻击防御的使用场景
- 掌握APT 攻击防御的配置方法

## 9.1.3 实验组网介绍

> （原图：图9-1 APT 攻击防御实验拓扑图）

## 9.1.4 实验规划

公司服务器区域部署了Mail 服务器，为公司或客户提供Mail 服务。FW1 与FW2 部署在网 络出口处，配置双机热备进行设备冗余，并且FW1，FW2 与FireHunter 进行联动对发送到 服务器区域的流量进行APT 攻击检查。 运营商网络主要用于模拟公司出差员工或公司客户通过互联网访问公司服务器资源的场景。 实验设备信息 设备 端口 安全区域/IP地址 FW1 GE1/0/0 安全区域：dmz IP地址：10.1.5.21/24 GE1/0/2 安全区域：dmz1，区域优先级45 IP地址：10.1.7.21/24 GE1/0/3 安全区域：isp1，区域优先级15 IP地址：10.1.9.21/24 GE1/0/5 安全区域：dmz2，区域优先级40 IP地址：10.1.8.21/24 FW2 GE1/0/0 安全区域：dmz IP地址：10.1.5.22/24 GE1/0/2 安全区域：dmz1，区域优先级45 IP地址：10.1.7.22/24 GE1/0/3 安全区域：isp1，区域优先级15 IP地址：10.1.9.22/24 GE1/0/5 安全区域：dmz2，区域优先级40 IP地址：10.1.8.22/24 R1 Eth-trunk1 成员端口：GE0/0/1与GE0/0/2 IP地址：10.1.9.11/24 Eth1/0/1 10.1.40.11/24

R3 GE0/0/1 10.1.32.13/24 GE0/0/2 10.1.60.13/24 FireHunter Eth1 10.1.7.51/24 PC2 / 10.1.32.102/32 Mail服务器 / 10.1.5.109/32

## 9.2 实验任务配置

## 9.2.1 配置前提

各设备上的IP 地址无需配置。 路由器，交换机上的动态路由协议不需要配置，学员只需要在防火墙上进行操作。 参照实验1,3 的实验内容完成公司园区网络的安全区域，路由协议，双机热备以及NAT Server 的部署，本实验不再重复展示配置内容。

## 9.2.2 配置思路

1. 配置防火墙与FireHunter 联动。当防火墙收到发送给Mail 服务器的流量，将流量发送给 FireHunter 进行检测。 2. 配置防火墙APT 攻击防御。当FireHunter 发现攻击风险后通知防火墙进行阻断。

## 9.2.3 配置步骤

步骤 1 配置防火墙与FireHunter 联动

```cli

# 根据规划，在FW1 上配置安全区域，选择“网络>安全区域”，在安全区域列表中新建
DMZ1 区域，并将接口GE1/0/2 接入安全区域，如下图。

#在FW1 上配置IP 地址，选择“网络>接口”，在接口列表中配置GE1/0/2 接口IP 地址，如下图。

# 根据规划，在FW2 上配置IP 地址，选择“网络>接口”，在接口列表中配置GE1/0/2 接口IP 地址，如下图。

#在FW1 上配置与沙箱联动，选择“系统>配置>沙箱”，配置“本地沙箱”，沙箱IP 地址为10.1.7.51，使用HTTPS 协议尽心联动，API Key 密码为Huawei@123，如下图。

#配置安全策略，在FW1 上放行与FireHunter 联动的流量，如下图。

# 登录FireHunter，配置沙箱与FW1，FW2 进行联动，选在“配置>联动设备”，在联动设备列表中添加防火墙（FireHunter 上的联动API Key 默认为Huawei@123，不需要更改）如 下图。

# 联动成功后，如下图，状态为绿色圆点表明联动成功。
```

步骤 2 配置APT 防御策略

```cli

#在FW1 上配置APT 防御策略，对于使用电子邮件发送到园区网络中的可执行文件或压缩文件进行APT 检测，选择“对象>安全配置文件>APT 防御”，在APT 防御配置文件列表中， 配置如下图。

#在安全策略中调用APT 防御配置文件，选择“策略>安全策略>安全策略”，配置安全策略，如下图。

# 登录FireHunter，配置检测策略，选择“配置>检测策略”，配置完成后，点击“应用”下发检测策略，如下图。
## 9.3 结果验证
## 9.3.1 测试APT 检测效果

# 登录PC2，使用邮件给园区内网用户user1@huawei.com 发送一封邮件，添加沙箱测试文件为附件，如下图。

# 发送完成后，登录FireHunter，查看检测结果，选择“分析>场景分析>邮件分析”，如下图。

# 登录防火墙。选择“监控>日志>业务日志”，查看到防火墙的监测日志，如下图。
```

## 9.4 配置参考

## 9.4.1 FW1 的配置

```cli

sysname FW1
hrp enable hrp interface GigabitEthernet1/0/5 remote 10.1.8.22

interface GigabitEthernet1/0/0

undo shutdown

ip address 10.1.5.21 255.255.255.0

vrrp vrid 1 virtual-ip 10.1.5.254 active

vrrp virtual-mac enable
link-group 1 service-manage ping permit

interface GigabitEthernet1/0/2

undo shutdown

ip address 10.1.7.21 255.255.255.0
service-manage http permit service-manage https permit service-manage ping permit service-manage telnet permit

interface GigabitEthernet1/0/3

undo shutdown

ip address 10.1.9.21 255.255.255.0
link-group 1 service-manage ping permit

interface GigabitEthernet1/0/5

undo shutdown

ip address 10.1.8.21 255.255.255.0
link-group 1 service-manage ping permit

firewall zone dmz
set priority 50 add interface GigabitEthernet1/0/0

firewall zone name isp1 id 4
set priority 15 add interface GigabitEthernet1/0/3

firewall zone name dmz2 id 5
set priority 40 add interface GigabitEthernet1/0/5

firewall zone name dmz1 id 6
set priority 45 add interface GigabitEthernet1/0/2

ospf 1 router-id 21.21.21.21
area 0.0.0.0 network 10.1.5.0 0.0.0.255 network 10.1.6.0 0.0.0.255 network 10.1.9.0 0.0.0.255 network 10.1.10.0 0.0.0.255
profile type av name AntiVirus

undo http-detect

undo ftp-detect
smtp-detect action delete-attachment pop3-detect action delete-attachment imap-detect direction both action delete-attachment

undo nfs-detect

undo smb-detect
sandbox default type FireHunter

ip 10.1.7.51 port 5002
```

protocol https api-key Huawei@123 linkage enable file-set EXE max-size 2048 file-set GZIP max-size 2048 file-set OFFICE max-size 2048 file-set PDF max-size 2048 file-set PICTURE max-size 200 file-set WEB max-size 200

profile type aapt name APT_defense

```cli

undo sandbox-detect HTTP

undo sandbox-detect HTTPS

undo sandbox-detect FTP

undo sandbox-detect NFS

undo sandbox-detect SMB
file-type BAT CLASS PE32 JAR SWF RAR ZIP GZ file-type 7Z CAB BZIP2 TAR sandbox-type local

security-policy
rule name "Outbound_to_Mail Server" source-zone isp1 destination-zone dmz destination-address 10.1.5.109 mask 255.255.255.255 profile av AntiVirus profile aapt APT_defense action permit rule name FW1_FireHunter source-zone dmz1 source-zone local destination-zone dmz1 destination-zone local source-address 10.1.7.21 mask 255.255.255.255 source-address 10.1.7.51 mask 255.255.255.255 destination-address 10.1.7.21 mask 255.255.255.255 destination-address 10.1.7.51 mask 255.255.255.255 action permit rule name FW2_FireHunter source-zone dmz1 source-zone local destination-zone dmz1 destination-zone local source-address 10.1.7.22 mask 255.255.255.255 source-address 10.1.7.51 mask 255.255.255.255 destination-address 10.1.7.22 mask 255.255.255.255 destination-address 10.1.7.51 mask 255.255.255.255 action permit
return
```

## 9.4.2 FW2 的配置

```cli

sysname FW2
hrp enable hrp standby-device hrp interface GigabitEthernet1/0/5 remote 10.1.8.21

interface GigabitEthernet1/0/0

undo shutdown

ip address 10.1.5.22 255.255.255.0

vrrp vrid 1 virtual-ip 10.1.5.254 standby

vrrp virtual-mac enable
service-manage ping permit

interface GigabitEthernet1/0/2

undo shutdown

ip address 10.1.7.22 255.255.255.0
service-manage http permit service-manage https permit service-manage ping permit service-manage telnet permit

interface GigabitEthernet1/0/3

undo shutdown

ip address 10.1.9.22 255.255.255.0
service-manage ping permit

interface GigabitEthernet1/0/5

undo shutdown

ip address 10.1.8.22 255.255.255.0
service-manage ping permit

firewall zone dmz
set priority 50 add interface GigabitEthernet1/0/0

firewall zone name isp1 id 4
set priority 15 add interface GigabitEthernet1/0/3

firewall zone name dmz2 id 5
set priority 40 add interface GigabitEthernet1/0/5

firewall zone name dmz1 id 6
set priority 45 add interface GigabitEthernet1/0/2

ospf 1 router-id 22.22.22.22
area 0.0.0.0 network 10.1.5.0 0.0.0.255 network 10.1.6.0 0.0.0.255 network 10.1.9.0 0.0.0.255 network 10.1.10.0 0.0.0.255
profile type av name AntiVirus

undo http-detect

undo ftp-detect
smtp-detect action delete-attachment pop3-detect action delete-attachment imap-detect direction both action delete-attachment

undo nfs-detect

undo smb-detect
sandbox default type FireHunter

ip 10.1.7.51 port 5002
```

protocol https api-key Huawei@123 linkage enable file-set EXE max-size 2048 file-set GZIP max-size 2048 file-set OFFICE max-size 2048 file-set PDF max-size 2048 file-set PICTURE max-size 200 file-set WEB max-size 200

profile type aapt name APT_defense

```cli

undo sandbox-detect HTTP

undo sandbox-detect HTTPS

undo sandbox-detect FTP

undo sandbox-detect NFS

undo sandbox-detect SMB
file-type BAT CLASS PE32 JAR SWF RAR ZIP GZ file-type 7Z CAB BZIP2 TAR sandbox-type local

security-policy
rule name "Outbound_to_Mail Server" source-zone isp1 destination-zone dmz destination-address 10.1.5.109 mask 255.255.255.255 profile av AntiVirus profile aapt APT_defense action permit rule name FW2_FireHunter source-zone dmz1 source-zone local destination-zone dmz1 destination-zone local source-address 10.1.7.22 mask 255.255.255.255 source-address 10.1.7.51 mask 255.255.255.255 destination-address 10.1.7.22 mask 255.255.255.255 destination-address 10.1.7.51 mask 255.255.255.255 action permit
return
```
