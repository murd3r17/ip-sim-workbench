---
doc_id: "hcie-datacom-v1.0-lab-16"
title: "10.2 NETCONF 配置实验"
book: "HCIE-Datacom-V1.0-Lab"
book_title: "HCIE-Datacom V1.0 实验手册"
track: "datacom"
level: "hcie"
series: "datacom-v1"
doc_type: "lab"
source_pdf: "HCIE-Datacom V1.0 实验手册.pdf"
seq: 16
vendor: huawei
language: zh
quality: "high"
ingest: true
---

# 10.2 NETCONF 配置实验

## 10.2.1 实验介绍

10.2.1.1 学习目标

- 实现通过ncclient 下发配置
- 实现通过paramiko 登录设备

10.2.1.2 实验组网介绍

图10-2 NETCONF 配置实验 本实验使用ACC_1 与PC1 进行，配置ACC_1 的VLANIF1 接口IP 地址为192.168.100.254/24， PC1 地址配置为192.168.100.1/24，通过PC1 编写脚本实现通过NETCONF 协议下发配置。

## 10.2.2 实验任务

10.2.2.1 配置思路

1. 完成ACC_1 的基础配置。
2. 完成ACC_1 的SSH 配置。
3. 编码脚本开启设备的NETCONF 功能，之后通过NETCONF 下发配置。
4. 脚本解析。

10.2.2.2 配置步骤

步骤 1 ACC_1 的基础配置 配置ACC_1 的互联IP 地址。

```cli
#设备命名。
```

略

```cli
#配置VLANIF1 接口IP 地址。

[ACC_1]interface Vlanif1

[ACC_1-Vlanif1] ip address 192.168.100.254 255.255.255.0

[ACC_1-Vlanif1] quit

#检查与PC1 之间的连通性。

[ACC_1]ping 192.168.100.1

PING 192.168.100.1: 56  data bytes, press CTRL_C to break Reply from 192.168.100.1: bytes=56 Sequence=1 ttl=128 time=1 ms Reply from 192.168.100.1: bytes=56 Sequence=2 ttl=128 time=1 ms Reply from 192.168.100.1: bytes=56 Sequence=3 ttl=128 time=1 ms Reply from 192.168.100.1: bytes=56 Sequence=4 ttl=128 time=1 ms Reply from 192.168.100.1: bytes=56 Sequence=5 ttl=128 time=1 ms

--- 192.168.100.1 ping statistics ---

5 packet(s) transmitted

5 packet(s) received

0.00% packet loss round-trip min/avg/max = 1/1/1 ms 可以正常通信。
```

步骤 2 SSH 配置 在ACC_1 上完成SSH 的基础配置。

```cli
#使能服务器端的STelnet 功能及配置VTY 用户界面。

[ACC_1] stelnet server enable

[ACC_1] ssh server-source all-interface

[ACC_1] user-interface vty 0 4

[ACC_1-ui-vty0-4] authentication-mode aaa

[ACC_1-ui-vty0-4] protocol inbound ssh

[ACC_1-ui-vty0-4] user privilege level 15

[ACC_1-ui-vty0-4] quit

#创建本地用户python，配置用户服务方式为SSH。

[ACC_1] aaa

[ACC_1-aaa] local-user python password irreversible-cipher Huawei@123

[ACC_1-aaa] local-user python privilege level 15

[ACC_1-aaa] local-user python service-type ssh

[ACC_1-aaa] local-aaa-user password policy administrator

[ACC_1-aaa-lupp-admin] undo password alert original

[ACC_1-aaa] quit

#关闭后首次登录不再提示修改密码。

#创建SSH 用户，配置认证方式为使用密码，配置服务方式为Stelnet。

[ACC_1] ssh user python

Info: Succeeded in adding a new SSH user.

[ACC_1] ssh user python authentication-type password

[ACC_1] ssh user python service-type stelnet
```

步骤 3 脚本编写 通过paramiko 登录设备，之后调用本地的配置脚本，开启设备的NETCONF 功能，之后通过 ncclient 使用NETCONF 配置设备的GE0/0/2 接口的描述信息为Config by NETCONF。

```cli
#本地的配置脚本。
```

system-view aaa local-user netconf password irreversible-cipher Huawei@123 local-user netconf privilege level 15 local-user netconf service-type api quit netconf source ip interface Vlanif 1 port 830 quit 新建名为”NETCONF”的txt 文件，之后在脚本中调用。

```cli
#安装ncclient。

[C:\~]$ pip3 install ncclient

#在CMD 中使用pip3 安装ncclient。

#完整代码。

# -*- coding: utf-8 -*-

```

from ncclient import manager from ncclient import operations import paramiko import time

```cli
#设备参数

ip = '192.168.100.254'
```

ssh_user = 'python' ssh_password = '<REDACTED>' netconf_port = '830'

netconf_user = 'netconf' netconf_password = '<REDACTED>' filename=r'C:\Users\PC1\Documents\Key\NETCONF\NETCONF.txt'

```cli
#定义类ssh，用于配置设备NETCONF
```

class ssh(): def ssh_connect(ip,username,password): ssh = paramiko.client.SSHClient() ssh.set_missing_host_key_policy(paramiko.client.AutoAddPolicy()) ssh.connect(hostname=ip,port=22,username=username,password=password) print(ip+' login succesfully') return ssh

def ssh_config(file,ip,username,password): a = ssh.ssh_connect(ip,username,password) cli = a.invoke_shell() cli.send('screen-length 0 temporary\n') time.sleep(0.5)

f = open(file,'r') config_list = f.readlines() for i in config_list: cli.send(i) time.sleep(0.5)

dis_this = cli.recv(999999).decode() print (dis_this) a.close()

```cli
#定义函数huawei_connect，用于建立NETCONF 连接

def huawei_connect(host, port, user, password): return manager.connect(host=host, port=port, username=user, password=password, hostkey_verify = False, device_params={'name': "huawei"}, allow_agent = False, look_for_keys = False)

#NETCONF 发送XML 数据，配置设备接口IP 地址
```

CREATE_INTERFACE = '''<config>

```cli
<if:interfaces xmlns:if="urn:ietf:params:xml:ns:yang:ietf-interfaces">

<if:interface>

<if:name>GigabitEthernet0/0/2</if:name>

<if:description>Config by NETCONF</if:description>

<if:type xmlns:iana-if-type="urn:ietf:params:xml:ns:yang:iana-if-type">iana-if- type:ethernetCsmacd</if:type>

<if:enabled>true</if:enabled>

<if:link-up-down-trap-enable>disabled</if:link-up-down-trap-enable>

</if:interface>

</if:interfaces>

</config>'''

#主函数，顺序执行
```

if __name__ == '__main__': ssh.ssh_config(filename,ip,ssh_user,ssh_password) m = huawei_connect(ip,netconf_port,netconf_user,netconf_password) m.edit_config(target='running',config=CREATE_INTERFACE)

```cli
#编译器执行。

#输出结果。

192.168.100.254 login succesfully

Info: The max number of VTY users is 10, and the number of current VTY users on line is 2. The current login time is 2021-09-01 16:16:45+08:00. Info: Lastest accessed IP: 192.168.100.1  Time: 2021-09-01 16:16:05+08:00  Failed: 0  Password will expire in: -
Info: Smart-upgrade is currently disabled. Enable Smart-upgrade to get recommended version information.
<ACC_1>screen-length 0 temporary Info: The configuration takes effect on the current user terminal interface only. <ACC_1>system-view Enter system view, return user view with Ctrl+Z.

[ACC_1] aaa

[ACC_1-aaa] local-user netconf password irreversible-cipher Huawei@123

Info: Add a new user.

[ACC_1-aaa] local-user netconf privilege level 15

Info: After changing the rights (including the password, access type, FTP directory, HTTP directory, and level) of a local user, the rights of users already online do not change. The change takes effect to users who go online after the change.

[ACC_1-aaa] local-user netconf service-type api

[ACC_1-aaa] quit

[ACC_1] netconf

[ACC_1-netconf] source ip interface Vlanif 1 port 830

[ACC_1-netconf] quit

#登录设备查看ACC_1 的GE0/0/2 接口信息。

[ACC_1]interface GigabitEthernet 0/0/2

[ACC_1-GigabitEthernet0/0/2]dis this

interface GigabitEthernet0/0/2
```

description Config by NETCONF

```cli
undo enable snmp trap updown
```

已正常配置接口备注。 NETCONF 配置下发成功。 步骤 4 脚本解析 接下来进行脚本解析。

```cli
#导入模块。

# -*- coding: utf-8 -*-

```

from ncclient import manager from ncclient import operations import paramiko

import time 默认情况下，anaconda 不包含ncclient，需手动安装，安装完anaconda 后已自动安装了 pip3，在Windows 的cmd 中即可直接安装。

```cli
[C:\~]$ pip3 install ncclient
```

Collecting ncclient Downloading ncclient-0.6.12.tar.gz (106 kB) Requirement already satisfied: setuptools>0.6 in c:\users\pc1\anaconda3\lib\site-packages (from ncclient) (52.0.0.post20210125) Requirement already satisfied: paramiko>=1.15.0 in c:\users\pc1\anaconda3\lib\site-packages (from ncclient) (2.7.2) Requirement already satisfied: lxml>=3.3.0 in c:\users\pc1\anaconda3\lib\site-packages (from ncclient) (4.6.3) Requirement already satisfied: six in c:\users\pc1\anaconda3\lib\site-packages (from ncclient) (1.15.0) Requirement already satisfied: bcrypt>=3.1.3 in c:\users\pc1\anaconda3\lib\site-packages (from paramiko>=1.15.0->ncclient) (3.2.0) Requirement already satisfied: cryptography>=2.5 in c:\users\pc1\anaconda3\lib\site-packages (from paramiko>=1.15.0->ncclient) (3.4.7) Requirement already satisfied: pynacl>=1.0.1 in c:\users\pc1\anaconda3\lib\site-packages (from paramiko>=1.15.0->ncclient) (1.4.0) Requirement already satisfied: cffi>=1.1 in c:\users\pc1\anaconda3\lib\site-packages (from bcrypt>=3.1.3->paramiko>=1.15.0->ncclient) (1.14.5) Requirement already satisfied: pycparser in c:\users\pc1\anaconda3\lib\site-packages (from cffi>=1.1->bcrypt>=3.1.3->paramiko>=1.15.0->ncclient) (2.20) Building wheels for collected packages: ncclient Building wheel for ncclient (setup.py): started Building wheel for ncclient (setup.py): finished with status 'done' Created wheel for ncclient: filename=ncclient-0.6.12-py2.py3-none-any.whl size=83781 sha256=61d2fe8cc5de8a4698902851204759a5c5debc5f01cde3c85e0b47bebe5dfabb Stored in directory: c:\users\pc1\appdata\local\pip\cache\wheels\b2\ea\95\9bdf798bf88d883a5ee9536d8a483042030d182ab252953b9 d Successfully built ncclient Installing collected packages: ncclient Successfully installed ncclient-0.6.12

```cli
#定义设备参数变量。

ip = '192.168.100.254'
```

ssh_user = 'python' ssh_password = '<REDACTED>' netconf_port = '830' netconf_user = 'netconf' netconf_password = '<REDACTED>' filename=r'C:\Users\PC1\Documents\Key\NETCONF\NETCONF.txt' 定义变量对应设备的参数，分别为主机IP、SSH 用户、SSH 密码、NETCONF 端口、NETCONF 用 户名、NETCONF 密码和本地文件名。

```cli
#申明名称为ssh 的类。
```

class ssh(): 类中包含两个方法（函数），ssh_connect()和ssh_config()，分别用于建立SSH 连接和发送配 置。

```cli
#定义方法ssh_connect。

def ssh_connect(ip,username,password): ssh = paramiko.client.SSHClient() ssh.set_missing_host_key_policy(paramiko.client.AutoAddPolicy()) ssh.connect(hostname=ip,port=22,username=username,password=password) print(ip+' login succesfully') return ssh ssh 类中定义第一个方法ssh_connect(ip,username,password)，输入三个参数为SSH 的IP、用户 名和密码。此函数封装paramiko 的方法，用于创建SSH 会话，详细解释参考前面章节。

#定义方法ssh_config。

def ssh_config(file,ip,username,password): a = ssh.ssh_connect(ip,username,password) cli = a.invoke_shell() cli.send('screen-length 0 temporary\n') time.sleep(0.5)

f = open(file,'r') config_list = f.readlines() for i in config_list: cli.send(i) time.sleep(0.5)
```

dis_this = cli.recv(999999).decode() print (dis_this) close() ssh 类中第二个方法ssh_config(file,ip,username,password)。定义四个参数分别为，配置文件路 径、SSH 的IP、用户名和密码。 其中ssh_config()通过调用ssh_connect()连接到设备后再发送配置命令。使用open 函数打开本 地NETCONF.txt 文件，逐行写入SSH 通道。最后查看和设备的交互过程，关闭会话。

```cli
#定义函数huawei_connect。

def huawei_connect(host, port, user, password): return manager.connect(host=host, port=port, username=user, password=password,
```

hostkey_verify = False, device_params={'name': "huawei"}, allow_agent = False, look_for_keys = False) 定义函数huawei_connect(host, port, user, password)。函数输入四个参数为NETCONF 主机的 IP、端口、NETCONF 用户名和密码。函数返回ncclient 的manager.connect 的方法。 Manager.connect 作用是建立NETCONF 连接。参数由RFC4741 定义，其中device_params 对于 华为设备有两个选择。可以配置为huawei 或者huaweiyang，分别对应IETF YANG 和华为的 YANG 模型。

```cli
#构建XML 文件。
```

CREATE_INTERFACE = '''<config>

```cli
<if:interfaces xmlns:if="urn:ietf:params:xml:ns:yang:ietf-interfaces">

<if:interface>

<if:name>GigabitEthernet0/0/2</if:name>

<if:description>Config by NETCONF</if:description>

<if:type xmlns:iana-if-type="urn:ietf:params:xml:ns:yang:iana-if-type">iana-if- type:ethernetCsmacd</if:type>

<if:enabled>true</if:enabled>

<if:link-up-down-trap-enable>disabled</if:link-up-down-trap-enable>

</if:interface>

</if:interfaces>

</config>''' NETCONF 通过XML 文件传递配置信息。XML 是一种非常常用的文本格式，可以<>不断嵌套展 开数据。完整的NETCONF 会话有传输层、消息层、操作层和内容层。在当前XML 配置文件中 传递的仅包含操作层和内容层。 NETCONF 基本操作包括get-config、get、edit-config、copy-config、delete-config、lock、 unlock、close-session 和kill session。例如本例的操作层信息为edit-config，对应具体operation 属性为merge，在数据库中修改存在或不存在的目标数据，如果目标数据不存在则创建，如果 目标数据存在则修改。 NETCONF 内容层则为对具体参数的修改。本例中配置接口GE0/0/2 的description，具体XML 格式可以参考设备的产品手册中“NETCONF YANG API 参考”部分。

#运行主函数。
```

if __name__ == '__main__': ssh.ssh_config(filename,ip,ssh_user,ssh_password) m = huawei_connect(ip,netconf_port,netconf_user,netconf_password) m.edit_config(target='running',config=CREATE_INTERFACE) 运行主函数。

首先执行ssh.ssh_config(filename,ip,ssh_user,ssh_password)，调用ssh 类下ssh_config 方法。输 入参数为步骤2 中定义的变量。 然后执行huawei_connect(ip,netconf_port,netconf_user,netconf_password)赋值给m。输入 NETCONF 参数，建立NETCONF 连接。 最后执行m.edit_config(target='running',config=CREATE_INTERFACE)。将构造的XML 配置文件通 过edit_config 方法发送到设备running 配置文件。

## 10.2.3 思考题

以NETCONF 查询设备信息和SNMP 有什么区别？
