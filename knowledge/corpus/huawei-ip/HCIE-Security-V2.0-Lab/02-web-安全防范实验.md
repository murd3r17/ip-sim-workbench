---
doc_id: "hcie-security-v2.0-lab-02"
title: "Web 安全防范实验"
book: "HCIE-Security-V2.0-Lab"
book_title: "HCIE-Security V2.0 实验手册"
track: "security"
level: "hcie"
series: "security-v2"
doc_type: "lab"
source_pdf: "HCIE-Security V2.0 实验手册.pdf"
seq: 2
vendor: huawei
language: zh
quality: "high"
ingest: true
---
# Web 安全防范实验

## 2.1 实验介绍

## 2.1.1 关于本实验

某公司在网络边界处部署了防火墙作为安全网关，内网DMZ 区域部署Web 服务器对外提供 Web 服务。为保护Web 服务器安全，在Web 服务器前端部署WAF 设备。

## 2.1.2 实验目的

-  掌握WAF 的应用场景
- 掌握WAF 的配置方法

## 2.1.3 实验组网介绍

> （原图：图2-1  Web 安全防范实验拓扑图）

## 2.1.4 实验规划

公司网络中部署了一台Web 服务器，对外提供Web 服务，所以需要在FW3 上配置NAT Server 进行地址映射。 为保护Web 服务安全，在Web 服务器前端部署WAF 设备，WAF 设备以透明接入的方式部 署在网络中。 PC2 模拟互联网上的攻击者，在访问Web 服务器时，发动SQL 注入攻击。

实验设备信息：

| 设备 | 端口 | 安全区域/IP地址 |
|------|------|-----------------|
| FW3 | GE1/0/0 | untrust / 10.1.70.23/24 |
| FW3 | GE1/0/1 | dmz / 10.1.22.23/24 |
| R3 | GE0/0/1 | 10.1.32.13/24 |
| R3 | GE0/0/2 | 10.1.60.13/24 |
| PC2 | / | 10.1.32.102/32 |
| Web服务器 | / | 10.1.22.104/32 |

## 2.2 实验任务配置

## 2.2.1 配置前提

各设备上的IP 地址无需配置。 路由器上的路由协议不需要配置，学员只需要在防火墙上进行操作。

## 2.2.2 配置思路

1. 配置安全域和路由，在FW3 上将相应接口加入安全域，并配置去往Internet 的默认路 由。 2. 配置NAT Server，在FW3 上将Web Server 的私网地址映射成为公网地址。 3. 配置WAF 设备，在WAF 设备上配置策略，防御SQL 注入攻击。

## 2.2.3 配置步骤

步骤 1 配置安全域和路由 根据实验规划，将FW3 上的接口加入相应的安全域，并配置一条默认路由，下一跳为互联网 地址10.1.70.2。

```cli

#在FW3 上选择“网络>接口>安全区域”，点击相应安全区域的编辑按钮，将接口接入安全区域，如下图。

#配置完成后，选择“网络>接口”，检查配置信息如下。

#在FW3 上配置去往Internet 的默认路由，下一跳为10.1.70.2。

#在FW3 上选择“网络>路由>静态路由”，在静态路由列表中，配置默认路由，如下图。
```

步骤 2 配置NAT Server 在FW3 上配置NAT Server，将私网地址10.1.22.104 映射为公网地址10.1.70.104。

```cli

#在FW3 上选择“策略>NAT 策略>服务器映射”。在服务器映射列表中点击“新建”，设置参数，如下图。
#配置完成后，在FW3 上配置安全策略，放行Internet 客户访问分支Web 服务器的流量。

#在FW3 上选择“策略>安全策略>安全策略”。在安全策略列表中点击“新建安全策略”，设置参数，如下图。
```

步骤 3 配置WAF 在WAF 设备上配置策略，保护内网Web 服务器的安全。

```cli
#在WAF 上配置名为Web Server 的规则组。选择“策略>规则组>新建规则组”，规则模板调用“预设规则”，如图所示。

#配置完成后，修改预设规则，选中配置的“Web Server”规则，在“注入攻击”中，启用代码注入和命令行注入，如下图。

# 启用后，如下图，并“应用更改”。

#配置的Web Server 规则组，默认仅用于检测，需要将该规则组启用后，才能进行攻击防御，点击“配置”按钮进行修改。

#将规则引擎改为“启用”后，点击“保存更改”，如下图。

#配置保护站点，对于访问Web 服务器的流量应用配置的规则引擎。选择“配置>保护站点>添加保护站点”，如下图。

#配置保护站点信息如下图，调用上述步骤中配置的策略规则，其他参数保持不变，最后点击“保存”。

#配置完成后，需要再次点击“应用更改”，如下图。
```

## 2.3 结果验证

## 2.3.1 测试WAF 功能

登录PC2，模拟攻击者访问Web 服务器。

```cli

#在PC2 上打开浏览器，输入连接http://10.1.70.104/web/index.html，查看能否正常访问，如下图。

# 上图表明，正常访问可以连接到Web Server。

#在PC2 上链接中加入SQL 注入的语句，模拟注入攻击，如下图，查看能够正常访问。

# 上图表明，访问被阻断。

# 登录WAF 设备，选择“日志>应用防护日志”，查看到WAF 上阻断访问流量的日志，如下图。

# 点击日志记录，查看具体信息如下。
```

## 2.4 配置参考

## 2.4.1 FW3 的配置

```cli

sysname FW3

interface GigabitEthernet1/0/0

undo shutdown

ip address 10.1.70.23 255.255.255.0
service-manage ping permit

interface GigabitEthernet1/0/1

undo shutdown

ip address 10.1.22.23 255.255.255.0
service-manage ping permit

firewall zone untrust
set priority 5 add interface GigabitEthernet1/0/0

firewall zone dmz
set priority 50 add interface GigabitEthernet1/0/1

ip route-static 0.0.0.0 0.0.0.0 10.1.70.2

nat server Web_Server zone untrust global 10.1.70.104 inside 10.1.22.104 no-
reverse unr-route

security-policy
rule name "Outbound_to_Web Server" source-zone untrust destination-zone dmz destination-address 10.1.22.104 mask 255.255.255.255 action permit
return
```
