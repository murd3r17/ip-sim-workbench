"""Distinguish explicit forecast output from original observed records."""

import re


_SECTION_PREFIX = re.compile(r"^(?:步骤\s*[0-9一二三四五六七八九十]+|\d+(?:[.．]\d+)*)(?:[.．、:：\s]+)")
_LEADING = re.compile(r"^(?:此处|以下|下面|下列|本段|本表)?(?:仅|只)?(?:列出|提供|展示|为|是)?\s*")
_PLAN = re.compile(r"(?:预期|预计|设想|预测)(?:的)?(?:命令)?(?:输出|回显|结果)"
                   r"(?:示意|样式|样例|模板|如下)?(?:[，,；。]\s*(?:尚未|未|还没)(?:实测|采集|取得|验证|读回|执行))?"
                   r"|(?:仅为|用作|参考)?(?:输出|回显)(?:模板|示意)(?:如下)?")
_ACTUAL = re.compile(r"(?:实际|实测|原书实录|已取得)(?:的)?(?:命令)?(?:输出|回显|读回|记录|结果)(?:如下)?"
                     r"|(?:读取|核对)(?:本次|当前|实际)的?(?:路由表|状态表|回显|读回|输出)")


def output_status(text: str) -> str:
    """Return a status only for a complete caption or heading that declares it."""
    label = text.strip(" \t*#：:。.；;")
    label = _LEADING.sub("", _SECTION_PREFIX.sub("", label)).strip()
    if _PLAN.fullmatch(label):
        return "planned"
    return "observed" if _ACTUAL.fullmatch(label) else ""


def planned_output(path: tuple, caption: str = "") -> bool:
    """The nearest explicit qualifier owns this source unit."""
    if local := output_status(caption):
        return local == "planned"
    return next((status == "planned" for _, title, _ in reversed(path) if (status := output_status(title))), False)


def planned_unit(kind: str) -> bool:
    return kind.startswith("planned_")
