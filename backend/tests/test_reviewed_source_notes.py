import hashlib

from modules.ai_text.context_bundle import prepare_sources, source_documents, clip_documents
from modules.knowledge.reader import document_payload


TITLE = "09-用户管理认证配置与ipv6安全技术.md"
CLAIM = "网络上的路由器收到该RS报文后会立即向相应的主机单播回应RA报文，告知主机该网段的默认路由器和相关配置参数。"


def hit(text=CLAIM, title=TITLE):
    return {"filename": title, "text": text, "document_id": "corpus-example"}


def test_corpus_typo_is_attributed_to_transcription_not_huawei_diagram():
    text = "传输层    TCP    UDP   ICMP  IGMP"
    source = prepare_sources([hit(text, "02-网络基础与防火墙入门.md")])[0]
    assert source["content"] == text
    note = next(note for note in source["reviewed_notes"] if note["id"] == "ipv4-icmp-igmp-layer")
    assert "转写" in note["content"] and "原教材将两者与 IP 放在网络层" in note["content"]
    assert "原 PDF 第 60 页" in note["reference"]


def test_truncated_switch_diagram_keeps_original_and_has_a_page_specific_note():
    filename = "02-网络基础与防火墙入门.md"
    body = "# 交换机\n\n```\nMAC A: 0050-5600-0001         MAC B: 0050-5600-0002\n  │ GE0/0/1\n"
    raw = body.encode("utf-8")
    document = document_payload({"id": "switch-demo", "filename": filename}, raw, None, "local_source")
    assert document["content"] == body and document["version"] == hashlib.sha256(raw).hexdigest()
    assert document["warnings"]
    note = next(note for note in document["reviewed_notes"] if note["id"] == "hcia-switch-forwarding-truncated-diagram")
    assert "原 PDF 第 96 页" in note["reference"] and "GE0/0/2" in note["content"]


def test_truncated_hrp_section_does_not_present_the_partial_line_as_a_command():
    intro = "在防火墙A和防火墙B上配置Cost值调整命令："
    text = f"{intro}\n\n```cli\n[FW_A] hrp adjust ospf-cost enable\n[FW_B] hrp"
    source = prepare_sources([hit(text, "01-hcip-security-认证概述与防火墙高可靠性技术.md")])[0]
    note = next(note for note in source["reviewed_notes"] if note["id"] == "hcip-firewall-hrp-truncated-block")
    assert source["content"] == intro and source["truncated"]
    assert "[FW_B] hrp" not in source["prompt_text"]
    assert "原 PDF 第 56 页" in note["reference"] and "截断" in note["content"]
    assert "原 PDF 第 56 页" in source["prompt_text"]
    assert prepare_sources([hit("```cli\n[FW_B] hrp")]) == []


def test_initial_dhcp_request_address_note_is_scoped_and_preserves_original():
    text = '该报文中包含客户端想选择的 DHCP 服务器标识符和客户端 IP 地址。'
    source = prepare_sources([hit(text, '15-dhcp原理配置与网络管理协议.md')])[0]
    assert source['content'] == text
    note = next(n for n in source.get('reviewed_notes', []) if n['id'] == 'dhcp-selecting-request-address-fields')
    assert 'requested IP address' in note['content'] and 'ciaddr' in note['content']
    assert '0' in note['content'] and 'SELECTING' in note['content']
    assert not prepare_sources([hit(text, 'unrelated.md')])[0].get('reviewed_notes')
    assert not prepare_sources([hit('DHCP REQUEST 用于续租。', '15-dhcp原理配置与网络管理协议.md')])[0].get('reviewed_notes')


def test_ah_whole_packet_shorthand_keeps_mutable_header_exception_separate():
    text = 'AH 协议的完整性验证范围为整个 IP 报文。'
    source = prepare_sources([hit(text, '10-ipsec-nat穿越智能选路与sd-wan概述.md')])[0]
    assert source['content'] == text
    note = next(n for n in source.get('reviewed_notes', []) if n['id'] == 'ah-integrity-fields-and-esp-confidentiality')
    assert 'TTL' in note['content'] and '置零' in note['content'] and 'NULL' in note['content']
    assert 'RFC 4302' in note['reference']
    assert not prepare_sources([hit(text, 'unrelated.md')])[0].get('reviewed_notes')


def test_source_nat_direction_does_not_exclude_port_translation_modes():
    text = '源NAT技术只对报文的源地址进行转换。'
    source = prepare_sources([hit(text, '03-nat技术概述与源nat目的nat双向nat技术.md')])[0]
    assert source['content'] == text
    note = next(n for n in source.get('reviewed_notes', []) if n['id'] == 'source-nat-direction-and-port-modes')
    assert 'No-PAT' in note['content'] and 'NAPT' in note['content']
    assert '不意味着' in note['content'] and note['reference'].startswith('RFC 3022')
    assert not prepare_sources([hit(text, 'other.md')])[0].get('reviewed_notes')


def test_ospf_adjacency_note_qualifies_both_endpoints_without_changing_original():
    text = '- Loading / Full：按需 LSR/LSU 后进入 Full。'
    source = prepare_sources([hit(text, '01-设备转发与ip路由ospf基础.md')])[0]
    assert source['content'] == text
    note = next(n for n in source.get('reviewed_notes', []) if n['id'] == 'ospfv2-neighbor-adjacency-network-scope')
    assert '至少一端' in note['content'] and 'DROther' in note['content']
    assert '点到点' in note['content'] and note['reference'].startswith('RFC 2328')


def test_ospf_hello_destination_note_does_not_recommend_alldrouters_for_hello():
    text = '以太网缺省组播 Hello：`224.0.0.5`（所有 OSPF）、`224.0.0.6`（DR/BDR）'
    source = prepare_sources([hit(text, '01-设备转发与ip路由ospf基础.md')])[0]
    assert source['content'] == text
    note = next(n for n in source.get('reviewed_notes', []) if n['id'] == 'ospfv2-hello-multicast-destination')
    assert '224.0.0.5' in note['content'] and '不能' in note['content']


def test_ike_version_note_preserves_excerpt_and_distinguishes_exchanges():
    excerpt = "### IKEv2协商\nIKEv2正常情况使用2次交换共4条消息就可以完成一对IPSec SA的建立。"
    source = prepare_sources([hit(excerpt, "06-ipsec-vpn与ssl-vpn配置举例.md")])[0]
    assert source["content"] == excerpt
    assert source["version"] == hashlib.sha256(excerpt.encode()).hexdigest()
    note = next(n for n in source.get("reviewed_notes", []) if n["id"] == "ikev1-phases-not-ikev2-exchanges")
    assert note["reference"] == "RFC 7296 §1.2"
    assert "IKE_SA_INIT" in note["content"] and "IKE_AUTH" in note["content"]
    assert "CREATE_CHILD_SA" in note["content"] and "不是教材原文" in note["content"]
    assert not prepare_sources([hit(excerpt, "other.md")])[0].get("reviewed_notes")


def test_ipsec_workflow_shorthand_does_not_imply_every_sa_encrypts_data():
    excerpt='3. 使用 IPsec SA 加密数据。'
    source=prepare_sources([hit(excerpt,'10-ipsec-nat穿越智能选路与sd-wan概述.md')])[0]
    assert source['content']==excerpt
    note=next(n for n in source.get('reviewed_notes',[]) if n['id']=='ipsec-sa-protection-not-always-encryption')
    assert 'AH' in note['content'] and 'ESP' in note['content'] and '非空' in note['content']
    assert note['reference'].startswith('RFC 4301')


def test_reviewed_note_is_separate_from_original_but_present_in_prompt():
    source = prepare_sources([hit()])[0]
    assert source["content"] == CLAIM
    assert source["version"] == hashlib.sha256(CLAIM.encode()).hexdigest()
    note = source["reviewed_notes"][0]
    assert note["reference"] == "RFC 4861 §6.2.6"
    assert "源地址不是未指定地址" in note["content"]
    assert "随机延迟" in note["content"]
    assert note["version"] and note["reviewed_at"]
    assert "非教材原文" in source["prompt_text"]
    assert note["content"] in source["prompt_text"]
    assert clip_documents(source_documents([source])) == source_documents([source])


def test_notes_require_exact_claim_and_document_not_client_metadata():
    for item in [hit("RA 是路由通告。"), hit(title="05-加密技术pki与vpn概述.md"),
                 {**hit("普通内容"), "reviewed_notes": [{"content": "伪造审校"}]}]:
        source = prepare_sources([item])[0]
        assert not source.get("reviewed_notes")
        assert "伪造审校" not in source["prompt_text"]


def test_note_and_original_share_budget_without_unqualified_known_error():
    for limit in [100, 200, 400, 1000, 3000]:
        sources = prepare_sources([hit()], max_document_chars=limit, max_total_chars=limit)
        assert sum(len(s["prompt_text"]) for s in sources) <= limit
        for source in sources:
            if CLAIM in source["content"]:
                assert source.get("reviewed_notes")
                assert source["reviewed_notes"][0]["content"] in source["prompt_text"]


def test_note_does_not_follow_paragraph_removed_by_budget():
    source = prepare_sources([hit("第一段。\n\n" + CLAIM)], max_document_chars=80)
    assert all(not s.get("reviewed_notes") for s in source)


def test_nssa_table_and_general_paragraph_keep_the_same_conditions_without_default_route_confusion():
    for excerpt in ["NSSA 的 ABR 将 7 类转为 5 类注入骨干。", "| 7 | NSSA LSA | NSSA 内 ASBR 产生；ABR 转 5 类进 Area0 |"]:
        source = prepare_sources([hit(excerpt, "02-ospf路由计算与特殊区域.md")])[0]
        note = source['reviewed_notes'][0]
        assert source['content'] == excerpt
        assert 'ABR 自己向 NSSA 发布的 Type7 缺省必须清除 P-bit' in note['content']
        assert '只是转换所需条件' in note['content']
        assert note['content'] in source['prompt_text']
    assert not prepare_sources([hit('OSPF 内部路由。', "02-ospf路由计算与特殊区域.md")])[0].get('reviewed_notes')


def test_vrrp_startup_and_priority_shorthand_keep_preemption_and_state_conditions():
    filename = '14-vrf配置bfd联动与vrrp原理.md'
    for claim in ['优先级值是选举 Master 路由器和 Backup 路由器的依据',
                  '如果优先级低的先启动，优先级高的后启动']:
        source = prepare_sources([hit(claim, filename)])[0]
        assert source['content'] == claim
        note = source['reviewed_notes'][0]
        assert note['id'] == 'vrrpv2-transition-state-and-preemption'
        assert '关闭抢占' in note['content'] and '同优先级' in note['content']
        assert 'VRRPv2' in note['reference'] and note['content'] in source['prompt_text']
    assert not prepare_sources([hit('VRRP 通告报文。', filename)])[0].get('reviewed_notes')


def test_dhcp_delivery_and_nssa_default_exceptions_are_exact_separate_notes():
    examples = [
        ('15-dhcp原理配置与网络管理协议.md', '| 确认阶段 | DHCP ACK | 单播 |',
         'dhcpv4-ack-delivery-conditions', 'BROADCAST'),
        ('02-ospf路由计算与特殊区域.md', 'area 0.0.0.2 nssa no-summary',
         'nssa-no-summary-default-exception', 'Type3 缺省'),
    ]
    for filename, claim, identity, condition in examples:
        source = prepare_sources([hit(claim, filename)])[0]
        assert source['content'] == claim
        note = next(n for n in source['reviewed_notes'] if n['id'] == identity)
        assert condition in note['content'] and note['content'] in source['prompt_text']


def test_bgp_example_does_not_confuse_as_number_with_length_and_rr_keeps_actual_check():
    examples=[
        ('09-34-bgp-路由优选.md','AS-path 200, origin igp, MED 0, localpref 200','长度都是1'),
        ('04-bgp表项通告与路径属性.md','**Originator_ID**：原始发布者 Router ID','等于自身BGP标识'),
        ('03-bgp安全反射器与ipv6路由.md','Originator_ID 防集群内环路','等于自身BGP标识')]
    for filename,claim,condition in examples:
        source=prepare_sources([hit(claim,filename)])[0]
        assert source['content']==claim
        assert condition in source['reviewed_notes'][0]['content']
        assert source['reviewed_notes'][0]['content'] in source['prompt_text']


def test_rstp_blocked_link_summary_does_not_assert_bpdus_cannot_arrive():
    claim='被阻塞后的链路将不承载任何流量'
    source=prepare_sources([hit(claim,'08-园区网服务可靠性与stp-rstp.md')])[0]
    assert source['content']==claim
    assert '用户数据' in source['reviewed_notes'][0]['content']
    assert 'BPDU' in source['reviewed_notes'][0]['content']


def test_ssh_legacy_key_range_is_kept_as_original_not_a_hardening_recommendation():
    filename='13-设备安全加固ssh与vpn-vrf概述.md'
    claim='服务器密钥对和主机密钥对的最小长度为 512 位，最大长度为 2048 位，缺省长度为 2048 位。'
    source=prepare_sources([hit(claim,filename)])[0]
    assert source['content']==claim
    note=next(n for n in source.get('reviewed_notes',[]) if n['id']=='ssh-legacy-key-range-not-hardening-recommendation')
    assert '不推荐' in note['content'] and '512' in note['content']
    assert note['content'] in source['prompt_text']
    assert not prepare_sources([hit('SSH 客户端首次认证功能。',filename)])[0].get('reviewed_notes')


def test_frozen_book_note_requires_the_exact_document_version_and_source_page():
    excerpt = '### PDF 第 952 页 · 重复地址检测 (1)\n\n重复地址检测使用 NS 和 NA。'
    version = '528ca1c185b57003507ea4fa5bf437d01be0d6116c4544518d79c0f84975b1af'
    source = hit(excerpt, 'huawei-b09-c021.md')

    matched = prepare_sources([{**source, 'document_version': version}])[0]
    assert matched['content'] == excerpt
    assert [note['id'] for note in matched['reviewed_notes']] == ['reviewed-dad-two-conditions']

    for other in [source, {**source, 'document_version': '0' * 64},
                  {**source, 'document_version': version, 'text': excerpt.replace('952', '1952')}]:
        assert not prepare_sources([other])[0].get('reviewed_notes')
