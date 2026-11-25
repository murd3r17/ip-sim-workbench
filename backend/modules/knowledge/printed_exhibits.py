"""Bind a printed table row and its original immediately adjoining legend."""

from dataclasses import dataclass
import re

from core.source_units import reading_units
from .query_focus import compact_text


_TABLE = re.compile(r"(?:图(?:示|例)?的(?:配套)?表|图(?:示|例)?配套的表)(?:里|中|内|格)?[，,\s]*"
                    r"(?P<row>[\u3400-\u9fffA-Za-z0-9 /_-]{2,16}?)\s*"
                    r"(?P<action>互联|连接|对接|联通|负责|包含|覆盖|部署|对应)\s*(?:什么|哪些|哪[个项条一])")
_COLOR = r"(?:(?:红|黄|蓝|绿|黑|白|灰|紫|橙)(?:色)?)?"
_SYMBOL = rf"{_COLOR}(?:虚线|实线|线|箭头|色块|方框|圆点)"
_NOTATION = re.compile(rf"{_COLOR}(?:点划线|点线|虚线|实线|箭头|色块|方框|圆点)")
_LEGEND_ASK = re.compile(rf"图(?:中|里|上|例中)(?:的)?\s*(?P<symbol>{_SYMBOL})\s*(?:说明|表示|代表|对应|标注)"
                         r"\s*(?:什么|哪些|哪[个项条一])")
_ORIGINAL_EXAMPLE = re.compile(r"例图|原图|图示|原书[^|\n]{0,14}(?:示例|例图)")
_OTHER_EXHIBIT = re.compile(r"另一(?:图|表|组)|另一(?:张|幅)(?:图|表)?|上一(?:图|表|张|页)|下一(?:图|表|张|页)|预计|计划")
_WHICH_MARK = re.compile(r"(?:这|那)(?:张|幅)(?P<title>[^，。？！；]{2,24}?图)\s*"
                         r"(?:用|采用)(?:了)?(?:哪(?:一)?种|什么)(?:图例|标记|记号|线型|线条|符号)"
                         r"(?:来)?(?:画出|表示|标出|标注|标识|代表)\s*(?P<relation>[^，。？！；]{2,24})$")
_FORM = r"(?:单据?|清单|表格?|记录|报告|截图)"
_WHO_WROTE = re.compile(rf"^(?P<form>[^，。？！；]{{2,24}}?{_FORM})(?:上面|中|里)?(?:是)?"
                        r"(?:由)?(?:谁|哪一位)(?:实际)?(?:填写|填|记录|签发|生成)(?:的)?$")
_OTHER_PERSON = re.compile(r"^(?:那张|该)?(?:表|单(?:据)?|记录)(?:里|中|上)?(?:提到|出现|列出|写着)?(?:的)?"
                           r"另一(?:个)?(?:人|方|位|台设备|台)(?:也)?(?:是|算)(?:这张|该)?"
                           r"(?:填单|填写|记录|签发|观察)(?:人|方|者|设备)(?:吗|么)?$")
_EXHIBIT_RELATION = re.compile(r"(?:表示|标记|代表|对应|标注|标出|标识|描绘)")
_FIGURE_TITLE = re.compile(r"^(?:图\s*\d[\d.－-]*\s*[:：、.．-]?\s*|(?:原书)?(?:图题|附图|图名)\s*[:：]\s*)")
_FORM_TITLE = re.compile(r"^(?:表\s*\d[\d.－-]*\s*[:：、.．-]?\s*|(?:原书)?(?:表题|表名)\s*[:：]\s*)")
_EXHIBIT_UNCERTAIN = re.compile(r"计划|预计|预期|模板|样表|示例格式|草稿|假设|如果|(?:拟|应|待|将)(?:填|观测|记录|标注)")
_AUTHOR_FIELDS = frozenset({"填写人", "填单人", "填表人", "记录人", "记录者", "记录方", "签发人", "生成方", "观察者", "观察方"})
_OBJECT_FIELDS = frozenset({"交接对象", "接收人", "核对对象", "被观察对象", "观察对象", "记录对象", "被记录对象"})


@dataclass(frozen=True)
class PrintedExhibit:
    row: str
    action: str
    symbol: str
    table_question: str
    figure_question: str


@dataclass(frozen=True)
class ExhibitAttribution:
    figure: str
    relation: str
    form: str
    questions: tuple[str, str, str]


def exhibit_attribution_request(clauses: tuple[str, ...]) -> ExhibitAttribution | None:
    """Separate a named diagram's notation from the named record's author and subject."""
    if len(clauses) not in {2, 3} or _OTHER_EXHIBIT.search("。".join(clauses)):
        return None
    figure, *record = clauses
    if len(record) == 1:
        record = re.split(r"[，,]", record[0], maxsplit=1)
    if len(record) != 2:
        return None
    authorship, subject = map(str.strip, record)
    mark, owner = _WHICH_MARK.search(figure), _WHO_WROTE.fullmatch(authorship)
    if mark and owner and _OTHER_PERSON.fullmatch(subject):
        return ExhibitAttribution(mark["title"], mark["relation"], owner["form"], (figure, authorship, subject))
    return None


def _title(text):
    return text.strip().lstrip("#").strip().strip("*").strip().rstrip("。；")


def _table_attribution(text, unit):
    header = text[slice(*unit.table_header)].splitlines()[0]
    rows = [header, *(text[slice(*row)] for row in unit.table_rows)]
    cells = [tuple(cell.strip().strip("`").strip("*") for cell in row.strip().strip("|").split("|")) for row in rows]
    fields, *data = cells
    author = [index for index, field in enumerate(fields) if field in _AUTHOR_FIELDS]
    subject = [index for index, field in enumerate(fields) if field in _OBJECT_FIELDS]
    if len(author) != 1 or len(subject) != 1 or any(len(row) != len(fields) for row in data):
        return False
    pairs = {(row[author[0]], row[subject[0]]) for row in data}
    return len(pairs) == 1 and all(re.fullmatch(r"[\w\u3400-\u9fff][\w\u3400-\u9fff /-]{0,28}", item)
                                   for pair in pairs for item in pair)


def complete_exhibit_attribution(text: str, request: ExhibitAttribution) -> str | None:
    """Recover a contiguous original figure caption and separately attributed table."""
    spans = reading_units(text)
    found = []
    wanted_figure, wanted_form = map(compact_text, (request.figure, request.form))
    for figure, legend, title, table in zip(spans, spans[1:], spans[2:], spans[3:]):
        if table.kind != "table" or not table.table_header or not table.table_rows:
            continue
        figure_title = _FIGURE_TITLE.sub("", _title(text[figure.start:figure.end]), count=1)
        table_title = _FORM_TITLE.sub("", _title(text[title.start:title.end]), count=1)
        if compact_text(figure_title) != wanted_figure or compact_text(table_title) != wanted_form:
            continue
        caption = text[legend.start:legend.end]
        window = text[figure.start:table.end].strip()
        if not 20 <= len(window) <= 1400 or _OTHER_EXHIBIT.search(window) or _EXHIBIT_UNCERTAIN.search(window):
            continue
        if not re.search(r"^\s*\**(?:本图|该图|图中|图上|图例)", caption):
            continue
        claims = [line for line in re.split(r"[。；！？\n]", caption)
                  if compact_text(request.relation) in compact_text(line) and _EXHIBIT_RELATION.search(line)
                  and len(_NOTATION.findall(line)) == 1
                  and not re.search(r"不(?:表示|标记|代表|对应)|未(?:标注|画出)", line)]
        if len(claims) == 1 and _table_attribution(text, table):
            found.append(window)
    return found[0] if len(found) == 1 else None


def printed_exhibit_request(clauses: tuple[str, ...]) -> PrintedExhibit | None:
    if len(clauses) != 2 or _OTHER_EXHIBIT.search("。".join(clauses)):
        return None
    table, legend = _TABLE.search(clauses[0]), _LEGEND_ASK.search(clauses[1])
    if table and legend:
        return PrintedExhibit(table["row"], table["action"], legend["symbol"], *clauses)
    return None


def complete_printed_exhibit(text: str, request: PrintedExhibit) -> str | None:
    """Return exactly one complete source window with both independently named items."""
    found = []
    for unit in reading_units(text):
        if unit.kind != "table" or not unit.table_header or not unit.table_rows or not unit.explanation:
            continue
        header = text[slice(*unit.table_header)]
        legend = text[slice(*unit.explanation)]
        if not _ORIGINAL_EXAMPLE.search(header) or _OTHER_EXHIBIT.search(legend):
            continue
        meaning = re.compile(rf"^\s*\**图(?:中|里|上|例中)(?:的)?\s*{re.escape(request.symbol)}"
                             r"\s*(?:显示|表示|代表|对应|标出)\s*[^。；\n]{3,}")
        if not meaning.search(legend):
            continue
        rows = [text[start:end].strip().strip("|").split("|") for start, end in unit.table_rows]
        selected = [cells for cells in rows if compact_text(cells[0]) == compact_text(request.row)]
        if len(selected) != 1 or not any(request.action in cell for cell in selected[0][1:]):
            continue
        window = text[unit.start:unit.explanation[1]].strip()
        if 20 <= len(window) <= 1300:
            found.append(window)
    return found[0] if len(found) == 1 else None
