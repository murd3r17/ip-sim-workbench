"""Plan a compact visible answer from explicit character limits, without cutting it."""
import re

_LIMITS = [
    re.compile(r'(\d{1,4})\s*(?:个)?(?:字|字符)\s*(?:以?内|以下)'),
    re.compile(r'(?:不超过|最多|至多|少于)\s*(\d{1,4})\s*(?:个)?(?:字|字符)'),
]


def character_limit(question):
    values=[int(m.group(1)) for pattern in _LIMITS for m in pattern.finditer(str(question or ''))]
    return min((n for n in values if 20<=n<=2000),default=None)


def length_instruction(question):
    limit=character_limit(question)
    if limit is None:
        return ''
    target=max(15,int(limit*.65))
    return (f'\n\n本题正文上限为{limit}字符（汉字、英文、数字、标点、引用编号和换行均计入）。'
            f'写作目标约{target}字符，留足余量，完成后核对长度再交付。'
            '先保留回答所问的结论、必要条件、真实入口及支持结论的引用；'
            '合并重复的限制说明，删除未询问的例子、标题、复述和结语。'
            '不要靠截掉句尾、引用或必要条件满足长度，也不输出字数核对过程。')


def report_length_instruction(field_limits):
    valid={key:value for key,value in (field_limits or {}).items()
           if key in {'summary','report_text'} and type(value) is int and 20<=value<=4000}
    if not valid:
        return ''
    rows=[f'{key}字段上限{limit}字符，写作目标约{int(limit*.65)}字符'
          for key,limit in valid.items()]
    return ('\n\n正文长度按解析后的字段分别计算，JSON键名和其他字段不占该字段配额：'
            +'；'.join(rows)+'。保留对象关系、主要文本差异、必要条件和证据缺口；'
            '同一限制合并说明一次，不加入无证据的原因或无关检查清单。'
            'report_text可独立阅读，不能省去跨设备/仅文本/凭据无法判断等真正适用的边界；'
            '不要机械截尾，不输出字数统计或规划。')
