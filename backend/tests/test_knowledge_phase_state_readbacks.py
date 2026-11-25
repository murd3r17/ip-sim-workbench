"""Negative controls for two independent, source-timed state witnesses."""

from unittest import TestCase, main

from core.source_units import reading_units
from modules.knowledge.phase_state_readbacks import StateRequest, page_witnesses, requests


PRE = StateRequest('s2', 'bfd', '会话', '故障', 'before')
POST = StateRequest('s2', 'bfd', '会话', '故障', 'after')
TABLE = """~~~text
<S2>display bfd session all
Local Remote State Interface
----------------------------
1     2      Up    Eth10
3     4      Up    Eth12
Total: 2
~~~"""
MARK = '**故障前回读。** 本页保留本次数据。'


class PhaseStateTests(TestCase):
    def observe(self, phase, page):
        return tuple(page_witnesses(phase, page, units=reading_units(page)))

    def test_each_readback_owns_its_phase_and_values(self):
        before = f'{MARK}\n\n#在 S2 上检查 BFD 会话状态\n\n{TABLE}'
        after = '**故障后回读。** S2 的两个 BFD 会话由 Up 变为 Down。'
        self.assertEqual(self.observe(PRE, before), (('up', before),))
        self.assertEqual(self.observe(POST, after), (('down', after),))
        for identity, request, source in (
                ('opposite phase', POST, before),
                ('wrong device', PRE, before.replace('<S2>', '<S10>')),
                ('non-observation command', PRE, before.replace('display', 'configure')),
                ('orphaned output', PRE, before.replace('<S2>display bfd session all\n', '')),
                ('no on-page stage', PRE, TABLE),
                ('conflicting actual rows', PRE, before.replace('3     4      Up', '3     4      Down')),
                ('no association over separate paragraph', PRE, f'{MARK}\n\n匹配另一个命令用例。\n\n{TABLE}'),
                ('conditional prose', POST, after.replace('S2 的', '如果 S2 的')),
                ('wrong reported observer', POST, after.replace('S2 的', 'S1 的')),
                ('ambiguous stage', PRE, f'{MARK.replace("故障前", "故障前与故障后")}\n\n{TABLE}'),
                ('wrong state field', PRE, before.replace('State Interface', 'Mode Interface'))):
            with self.subTest(identity=identity):
                self.assertEqual(self.observe(request, source), ())

    def test_compares_only_same_named_measurement(self):
        left = '同一次实验中，故障前 S2 的 BFD 会话是什么状态'
        right = '故障后 S2 的 BFD 会话是什么状态'
        self.assertEqual(requests(f'{left}？{right}？', (left, right)), (PRE, POST))
        self.assertEqual(requests(f'{right}？{left}？', (right, left)), (POST, PRE))
        for other in (right.replace('S2', 'S1'), right.replace('BFD 会话', 'OSPF 邻居'),
                      right.replace('故障后', '故障前'), '现场连接设备，' + right, '预计' + right,
                      'PDF 第 33 页' + right):
            with self.subTest(other=other):
                self.assertEqual(requests(f'{left}？{other}？', (left, other)), ())


if __name__ == '__main__':
    main()
