"""Counterexamples for the short-question source binder."""

import unittest

from modules.knowledge.short_observations import original_observation, short_record_request


class ShortOwnedRecordTests(unittest.TestCase):
    def test_retrospective_concrete_question_requires_one_owner_and_one_field(self):
        premise = 'Type 5 那例，R3 记下的 192.0.2.0/24 下一跳是多少？'
        self.assertIsNotNone(short_record_request(premise))
        for query in ('R3 看到什么？', 'R3 的下一跳是什么意思？', 'Type 5 的 R3 通常应当看到哪条前缀？',
                      'Type 5 那例，现场连接 R3 看一下下一跳是多少？',
                      'Type 5 那例，R3 原计划给 192.0.2.0/24 留下的下一跳是多少？',
                      'Type 5 那例，R1 和 R3 见到的 192.0.2.0/24 下一跳是多少？',
                      'Type 5 那例，R3 见到 192.0.2.0/24 和 192.0.3.0/24 的下一跳是多少？'):
            with self.subTest(query=query):
                self.assertIsNone(short_record_request(query))

    def test_observation_owner_and_target_are_bound_before_the_literal_field(self):
        asked = short_record_request('Type 5 那例，R3 记下的 192.0.2.0/24 的下一跳是多少？')
        self.assertEqual(original_observation(asked, 'Type 5 验证完成后，R3 读到 `192.0.2.0/24`，下一跳是 `192.0.2.1`。'), '192.0.2.1')
        for text in ('Type 5，R4 读到 192.0.2.0/24，下一跳 192.0.2.1。',
                     'Type 5，R4 从 R3 读到 192.0.2.0/24，下一跳 192.0.2.1。',
                     'Type 5，R3 读到 192.0.2.0/24 和 192.0.3.0/24，其中第二个下一跳 192.0.2.1。',
                     'Type 5，R3 读到 192.0.2.0/24。R4 读到 192.0.3.0/24，下一跳 192.0.3.1。',
                     'Type 5，R3 计划读到 192.0.2.0/24，下一跳 192.0.2.1。',
                     'Type 5，R3 如果读到 192.0.2.0/24，下一跳 192.0.2.1。',
                     'Type 5，R3 读到 192.0.2.0/24，下一跳 192.0.2.1。R3 读到 192.0.2.0/24，下一跳 192.0.2.2。',
                     'Type 5，R3 读到 192.0.2.0/24，下一跳 192.0.2.999。',
                     'Type 5，R3 的路由表列出 192.0.2.0/24，下一跳另见第 33 页。'):
            with self.subTest(text=text):
                self.assertIsNone(original_observation(asked, text))

    def test_phase_requires_reported_operation_and_matching_side(self):
        asked = short_record_request('续租申请后，AC2 记下的终端地址是什么？')
        self.assertEqual(original_observation(asked, '终端续租申请后 AC2 读到 192.0.2.8。'), '192.0.2.8')
        for text in ('终端续租申请前 AC2 读到 192.0.2.8。', '终端续租申请后计划 AC2 读到 192.0.2.8。',
                     '终端重新认证后 AC2 读到 192.0.2.8。', '终端续租申请后，配置为 192.0.2.8。'):
            with self.subTest(text=text):
                self.assertIsNone(original_observation(asked, text))


if __name__ == '__main__':
    unittest.main()
