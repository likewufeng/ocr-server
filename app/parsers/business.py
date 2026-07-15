"""
营业执照解析器 v6 - 完整最终版

已验证可正确解析的字段：
  - 统一社会信用代码（含OCR修正+校验）
  - 名称（处理OCR拆分）
  - 类型（处理OCR拆分）
  - 法定代表人（多策略+坐标扫描）
  - 注册资本
  - 成立日期
  - 住所/地址（处理"住"+"所"拆分、地址在右侧栏、OCR噪声字符）
  - 经营范围（去重、正确停止）
"""
import re
from statistics import median
from typing import Optional

from app.utils.layout import Layout


# ------------------------------------------------------------------ #
#  统一社会信用代码工具                                                #
# ------------------------------------------------------------------ #

_USCC_CHARSET = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCC_CHAR_INDEX = {ch: i for i, ch in enumerate(_USCC_CHARSET)}
_USCC_WEIGHTS = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]


def _uscc_check_digit(code17: str) -> Optional[str]:
    if len(code17) != 17:
        return None
    total = 0
    for ch, w in zip(code17, _USCC_WEIGHTS):
        if ch not in _USCC_CHAR_INDEX:
            return None
        total += _USCC_CHAR_INDEX[ch] * w
    return _USCC_CHARSET[(31 - total % 31) % 31]


def _validate_uscc(code: str) -> bool:
    if len(code) != 18:
        return False
    if not all(c in _USCC_CHARSET for c in code):
        return False
    return _uscc_check_digit(code[:17]) == code[17]


def fix_credit_code(raw: str) -> str:
    """
    OCR 信用代码纠错：
    - idx 2~7 纯数字位：字母转数字
    - 其余混合位：只修正常见非法字符
    """
    if len(raw) != 18 or _validate_uscc(raw):
        return raw

    chars = list(raw)

    digit_corr = {
        "I": "1", "O": "0", "S": "5", "Z": "2", "B": "8", "G": "6",
    }
    mixed_corr = {
        "I": "1", "O": "0", "S": "5", "V": "U", "Z": "2",
    }

    # 行政区划位
    for idx in range(2, 8):
        if chars[idx].isalpha():
            chars[idx] = digit_corr.get(chars[idx], chars[idx])

    # 其他位
    for idx in list(range(0, 2)) + list(range(8, 18)):
        if chars[idx] not in _USCC_CHARSET:
            chars[idx] = mixed_corr.get(chars[idx], chars[idx])

    # 校验位修正
    if all(c in _USCC_CHARSET for c in chars[:17]):
        expected = _uscc_check_digit("".join(chars[:17]))
        check_corr = {
            "I": "1", "O": "0", "S": "5", "V": "U", "Z": "2",
            "l": "1", "o": "0",
        }
        if expected and chars[17] != expected:
            if check_corr.get(chars[17], chars[17]) == expected:
                chars[17] = expected

    return "".join(chars)


# ------------------------------------------------------------------ #
#  主解析器                                                           #
# ------------------------------------------------------------------ #

class BusinessParser:

    def parse(self, layout: Layout):
        data = {
            "type": "business_license",
            "credit_code": "",
            "name": "",
            "type_name": "",
            "legal_person": "",
            "capital": "",
            "establish_date": "",
            "address": "",
            "business_scope": "",
        }

        all_lines = list(layout.all() or [])
        if not all_lines:
            return data

        all_lines.sort(key=lambda x: (x.top, x.left))

        doc_width = max(line.right for line in all_lines)
        doc_height = max(line.bottom for line in all_lines)
        line_heights = [max(1, line.bottom - line.top) for line in all_lines]
        base_h = int(median(line_heights)) if line_heights else 20

        # ---------------------------------------------------------- #
        #  基础几何工具                                                #
        # ---------------------------------------------------------- #

        def cx(line):
            return (line.left + line.right) / 2

        def cy(line):
            return (line.top + line.bottom) / 2

        def h(line):
            return max(1, line.bottom - line.top)

        def row_tol(line=None, scale: float = 1.0) -> int:
            ref = base_h
            if line is not None:
                ref = max(ref, h(line))
            return max(10, int(ref * scale))

        def strip_label(text: str, *labels: str) -> str:
            for label in labels:
                if label in text:
                    return text.replace(label, "", 1).lstrip(":：").strip()
            return text.strip()

        def find_exact(*texts: str):
            for line in all_lines:
                if line.text in texts:
                    return line
            return None

        def find_contains(*keywords: str):
            for line in all_lines:
                for kw in keywords:
                    if kw in line.text:
                        return line
            return None

        def find_all_contains(*keywords: str):
            result = []
            for line in all_lines:
                for kw in keywords:
                    if kw in line.text:
                        result.append(line)
                        break
            return result

        def same_row_right_blocks(anchor, tol: Optional[int] = None):
            """
            找 anchor 右侧、且大致同行的文本块。
            用中心点判断，允许轻微重叠。
            """
            _tol = tol if tol is not None else row_tol(anchor, 1.0)
            result = [
                line for line in all_lines
                if line is not anchor
                and abs(cy(line) - cy(anchor)) <= _tol
                and cx(line) > cx(anchor)
                and line.right > anchor.left
            ]
            result.sort(key=lambda x: (x.left, x.top))
            return result

        def blocks_below(anchor,
                         top_max: Optional[float] = None,
                         col_left: Optional[float] = None,
                         col_right: Optional[float] = None,
                         max_count: int = 50):
            """
            找 anchor 下方的块，按 top/left 排序。
            列过滤采用 overlap 模式。
            """
            _top_min = anchor.bottom
            _top_max = top_max if top_max is not None else doc_height
            _col_left = col_left if col_left is not None else 0
            _col_right = col_right if col_right is not None else doc_width

            result = [
                line for line in all_lines
                if line.top >= _top_min
                and line.top < _top_max
                and line.left < _col_right
                and line.right > _col_left
            ]
            result.sort(key=lambda x: (x.top, x.left))
            return result[:max_count]

        def find_boundary_top(after_top: float,
                              keywords,
                              col_left: Optional[float] = None,
                              col_right: Optional[float] = None) -> float:
            """
            找 after_top 之后、且列范围相交的最近边界关键词 top。
            """
            bound = doc_height
            _col_left = 0 if col_left is None else col_left
            _col_right = doc_width if col_right is None else col_right

            for line in all_lines:
                if line.top <= after_top:
                    continue
                if not (line.left < _col_right and line.right > _col_left):
                    continue
                if any(kw in line.text for kw in keywords):
                    bound = min(bound, line.top)
            return bound

        def is_label_like(text: str) -> bool:
            label_keywords = [
                "统一社会信用代码", "社会信用代码", "注册号",
                "名称", "名", "称",
                "类型", "类", "型",
                "注册资本", "注册资金",
                "成立日期", "注册日期", "设立日期",
                "法定代表人", "负责人",
                "住所", "住", "所", "营业场所", "经营场所", "注册地址",
                "经营范围", "登记机关",
            ]
            t = text.strip()
            return t in label_keywords or any(t == kw for kw in label_keywords)

        def is_person_name(text: str) -> bool:
            t = text.strip()
            if not (2 <= len(t) <= 10):
                return False
            if re.search(r"\d", t):
                return False
            bad_keywords = [
                "层", "楼", "路", "街", "号", "市", "区", "省",
                "镇", "村", "县", "道", "广场", "中心", "大厦",
            ]
            if any(kw in t for kw in bad_keywords):
                return False
            chinese_count = sum(1 for c in t if "\u4e00" <= c <= "\u9fff")
            return chinese_count >= 2

        def is_date_text(text: str) -> bool:
            t = text.strip()
            return bool(re.fullmatch(r"\d{4}年\d{2}月\d{2}日", t))

        def looks_like_capital(text: str) -> bool:
            t = text.strip()
            if not t:
                return False
            if is_date_text(t):
                return False
            return bool(re.search(r"[万亿圆元整壹贰叁肆伍陆柒捌玖拾佰仟零\d]", t))

        def clean_addr_text(text: str) -> str:
            """
            清理地址首部OCR噪声：
            - 去掉前导标点/字母
            - 去掉已知噪声汉字，如“斤”
            """
            t = text.strip()
            if not t:
                return t

            while t and not ("\u4e00" <= t[0] <= "\u9fff") and not t[0].isdigit():
                t = t[1:].strip()
            if not t:
                return t

            if t[0].isdigit():
                return t

            admin_suffixes = {
                "省", "市", "区", "县", "镇", "村", "乡", "街", "路",
                "道", "号", "楼", "层", "幢", "栋", "室", "期",
                "州", "盟", "旗",
            }
            if len(t) >= 2 and t[1] in admin_suffixes:
                return t

            known_noise = {
                "斤", "两", "克", "升", "斗", "丈", "尺", "寸", "分",
                "卜", "厂", "囗", "冂", "凵", "匚",
            }
            if t[0] in known_noise:
                t = t[1:].strip()

            return t

        def looks_like_address(text: str) -> bool:
            t = clean_addr_text(text)
            if len(t) < 4:
                return False
            addr_keywords = [
                "省", "市", "区", "县", "镇", "乡", "村",
                "路", "街", "号", "楼", "层", "室",
                "广场", "大道", "交叉口", "大厦", "中心",
            ]
            if any(kw in t for kw in addr_keywords):
                return True
            chinese_count = sum(1 for c in t if "\u4e00" <= c <= "\u9fff")
            return chinese_count >= 4 and bool(re.search(r"\d", t))

        def collect_row_sequence(blocks,
                                 gap_threshold: Optional[int] = None,
                                 skip_exact=None,
                                 strip_prefixes=()):
            """
            从同行右侧块中，收集连续的一段文本。
            遇到横向大间隔时停止，避免跨到另一个字段列。
            """
            if not blocks:
                return []

            _skip_exact = set(skip_exact or [])
            _gap = gap_threshold if gap_threshold is not None else max(30, base_h * 4)

            result = []
            prev = None

            for block in blocks:
                raw = (block.text or "").strip()
                if not raw:
                    prev = block
                    continue

                if prev is not None and block.left - prev.right > _gap:
                    break

                if raw in _skip_exact:
                    prev = block
                    continue

                text = raw
                for prefix in strip_prefixes:
                    if text.startswith(prefix):
                        text = text[len(prefix):].lstrip(":：").strip()
                        break

                if text:
                    result.append((block, text))

                prev = block

            return result

        def extract_row_value_by_label(label_keywords,
                                       validator=None,
                                       row_scale: float = 1.0):
            """
            典型行字段提取：
            1. 同块去标签
            2. 同行右侧取最左值
            """
            line = find_contains(*label_keywords)
            if not line:
                return ""

            for kw in label_keywords:
                if kw in line.text:
                    remain = strip_label(line.text, kw)
                    if remain and (validator is None or validator(remain)):
                        return remain

            rights = same_row_right_blocks(line, tol=row_tol(line, row_scale))
            for block in rights:
                text = (block.text or "").strip()
                if not text:
                    continue
                if validator is None or validator(text):
                    return text

            return ""

        # ---------------------------------------------------------- #
        #  统一社会信用代码                                            #
        # ---------------------------------------------------------- #

        def extract_credit_code() -> str:
            # 先扫所有块，优先返回通过校验的
            fallback = ""
            for line in all_lines:
                for m in re.finditer(r"[0-9A-Z]{18}", line.text or ""):
                    candidate = fix_credit_code(m.group())
                    if _validate_uscc(candidate):
                        return candidate
                    if not fallback:
                        fallback = candidate

            # 再全文回退
            if fallback:
                return fallback

            joined = "".join(line.text or "" for line in all_lines)
            m = re.search(r"[0-9A-Z]{18}", joined)
            return fix_credit_code(m.group()) if m else ""

        data["credit_code"] = extract_credit_code()

        # ---------------------------------------------------------- #
        #  名称                                                        #
        # ---------------------------------------------------------- #

        def extract_name() -> str:
            # 情况1：完整标签在同一个块
            for kw in ("名称", "名 称"):
                line = find_contains(kw)
                if line:
                    remain = strip_label(line.text, kw)
                    if remain:
                        return remain
                    row_parts = collect_row_sequence(
                        same_row_right_blocks(line, tol=row_tol(line, 1.0))
                    )
                    if row_parts:
                        return "".join(text for _, text in row_parts)

            # 情况2：拆成 “名” + “称” + 值
            name_label = find_exact("名")
            if name_label:
                row_parts = collect_row_sequence(
                    same_row_right_blocks(name_label, tol=row_tol(name_label, 1.0)),
                    skip_exact={"称"},
                    strip_prefixes=("称",),
                )
                if row_parts:
                    values = []
                    for _, text in row_parts:
                        if text and not is_label_like(text):
                            values.append(text)
                    if values:
                        return "".join(values)

            return ""

        data["name"] = extract_name()

        # ---------------------------------------------------------- #
        #  类型                                                        #
        # ---------------------------------------------------------- #

        def extract_type() -> str:
            # 情况1：完整标签
            for kw in ("类型", "类 型"):
                line = find_contains(kw)
                if line:
                    remain = strip_label(line.text, kw)
                    if remain:
                        return remain
                    row_parts = collect_row_sequence(
                        same_row_right_blocks(line, tol=row_tol(line, 1.0))
                    )
                    if row_parts:
                        vals = [text for _, text in row_parts if not is_label_like(text)]
                        if vals:
                            return "".join(vals)

            # 情况2：拆成 “类” + “型” + 值
            type_label = find_exact("类")
            if type_label:
                row_parts = collect_row_sequence(
                    same_row_right_blocks(type_label, tol=row_tol(type_label, 1.0)),
                    skip_exact={"型"},
                    strip_prefixes=("型",),
                )
                if row_parts:
                    vals = [text for _, text in row_parts if not is_label_like(text)]
                    if vals:
                        return "".join(vals)

            return ""

        data["type_name"] = extract_type()

        # ---------------------------------------------------------- #
        #  法定代表人                                                  #
        # ---------------------------------------------------------- #

        def extract_legal_person() -> str:
            line = find_contains("法定代表人", "负责人")
            if not line:
                return ""

            for kw in ("法定代表人", "负责人"):
                if kw in line.text:
                    remain = strip_label(line.text, kw)
                    if remain and is_person_name(remain):
                        return remain

            rights = same_row_right_blocks(line, tol=row_tol(line, 1.0))
            for block in rights:
                text = (block.text or "").strip()
                if is_person_name(text):
                    return text

            # 回退：下方近邻
            for block in blocks_below(
                line,
                top_max=line.bottom + base_h * 4,
                col_left=line.left - base_h,
                col_right=line.right + base_h * 8,
                max_count=5,
            ):
                text = (block.text or "").strip()
                if is_person_name(text):
                    return text

            return ""

        data["legal_person"] = extract_legal_person()

        # ---------------------------------------------------------- #
        #  注册资本 / 成立日期                                         #
        # ---------------------------------------------------------- #

        data["capital"] = extract_row_value_by_label(
            ("注册资本", "注册资金"),
            validator=looks_like_capital,
            row_scale=1.0,
        )

        data["establish_date"] = extract_row_value_by_label(
            ("成立日期", "注册日期", "设立日期"),
            validator=is_date_text,
            row_scale=1.0,
        )

        # ---------------------------------------------------------- #
        #  地址                                                        #
        # ---------------------------------------------------------- #

        def extract_address() -> str:
            """
            地址优先级：
            A. 完整标签：住所 / 营业场所 / 经营场所 / 注册地址
            B. 单独“所”标签（适配上一份样本）
            C. 单独“住”标签（适配当前这份样本）
            """
            addr_parts = []
            addr_anchor = None

            def collect_address_from_label(label_line, skip_exact=None, strip_prefixes=(), row_scale=1.2):
                if not label_line:
                    return None, None

                rights = same_row_right_blocks(label_line, tol=row_tol(label_line, row_scale))
                row_parts = collect_row_sequence(
                    rights,
                    gap_threshold=max(30, base_h * 4),
                    skip_exact=skip_exact,
                    strip_prefixes=strip_prefixes,
                )

                # 找第一个像地址的块
                for block, text in row_parts:
                    if looks_like_address(text):
                        return clean_addr_text(text), block

                # 若没有明显地址特征，则返回第一个非空块
                for block, text in row_parts:
                    if text:
                        return clean_addr_text(text), block

                return None, None

            # A. 完整标签
            full_addr_line = find_contains("住所", "营业场所", "经营场所", "注册地址")
            if full_addr_line:
                for kw in ("住所", "营业场所", "经营场所", "注册地址"):
                    if kw in full_addr_line.text:
                        remain = strip_label(full_addr_line.text, kw)
                        if remain:
                            addr_parts.append(clean_addr_text(remain))
                            addr_anchor = full_addr_line
                            break

                if not addr_parts:
                    first_text, first_block = collect_address_from_label(full_addr_line)
                    if first_text:
                        addr_parts.append(first_text)
                        addr_anchor = first_block

            # B. 优先尝试“所”
            if not addr_parts:
                suo_line = find_exact("所")
                if suo_line:
                    first_text, first_block = collect_address_from_label(
                        suo_line,
                        skip_exact={"所"},
                        strip_prefixes=("所",),
                        row_scale=1.3,
                    )
                    if first_text:
                        addr_parts.append(first_text)
                        addr_anchor = first_block

            # C. 再尝试“住”
            if not addr_parts:
                zhu_line = find_exact("住")
                if zhu_line:
                    rights = same_row_right_blocks(zhu_line, tol=max(35, row_tol(zhu_line, 1.4)))
                    row_parts = collect_row_sequence(
                        rights,
                        gap_threshold=max(30, base_h * 4),
                        skip_exact={"所"},
                        strip_prefixes=("所",),
                    )

                    for block, text in row_parts:
                        cleaned = clean_addr_text(text)
                        # 关键：住标签回退时，要求块在右半区，避免误拿左侧其它字段
                        if block.left >= doc_width * 0.35 and looks_like_address(cleaned):
                            addr_parts.append(cleaned)
                            addr_anchor = block
                            break

            if not addr_parts or not addr_anchor:
                return ""

            # 继续往下收集同列连续地址行
            addr_col_left = max(0, addr_anchor.left - base_h * 2)
            addr_col_right = doc_width

            boundary_top = find_boundary_top(
                addr_anchor.top,
                keywords=["登记机关", "市场监督", "国家企业信用信息公示系统网址", "国家市场监督管理总局监制"],
                col_left=addr_col_left,
                col_right=addr_col_right,
            )

            stop_keywords = [
                "登记机关", "市场监督",
                "国家企业信用信息公示系统网址", "http", "https",
            ]

            prev = addr_anchor
            seen = {id(addr_anchor)}

            for block in blocks_below(
                addr_anchor,
                top_max=boundary_top,
                col_left=addr_col_left,
                col_right=addr_col_right,
                max_count=10,
            ):
                if id(block) in seen:
                    continue

                text = (block.text or "").strip()
                if not text:
                    continue

                # 同列连续性：如果竖向间隔太大，停止，避免吃到下方噪声碎片
                if block.top - prev.bottom > max(25, base_h * 3):
                    break

                # 停止词
                if any(kw in text for kw in stop_keywords):
                    break

                # 日期行停止
                if is_date_text(text) or re.fullmatch(r"[\d年月日\s]+", text):
                    break

                # 竖排/异常高小碎片，忽略
                if (block.bottom - block.top) > base_h * 2.2 and len(text) <= 2:
                    break

                addr_parts.append(clean_addr_text(text))
                prev = block
                seen.add(id(block))

            return "".join(addr_parts)

        data["address"] = extract_address()

        # ---------------------------------------------------------- #
        #  经营范围                                                    #
        # ---------------------------------------------------------- #

        def extract_business_scope() -> str:
            scope_line = find_contains("经营范围")
            if not scope_line:
                return ""

            scope_parts = []
            seen_ids = {id(scope_line)}

            # 1. 同块文本
            if "经营范围" in scope_line.text:
                remain = strip_label(scope_line.text, "经营范围")
                if remain:
                    scope_parts.append(remain)

            # 2. 同行右侧：只取“左侧主栏”连续块，避免吃到右侧地址
            row_blocks = same_row_right_blocks(scope_line, tol=max(20, row_tol(scope_line, 1.0)))
            row_seq = collect_row_sequence(
                row_blocks,
                gap_threshold=max(30, base_h * 4),
            )

            scope_anchor = None
            if row_seq:
                # 取第一段作为起始
                scope_anchor = row_seq[0][0]
                for block, text in row_seq:
                    if text:
                        scope_parts.append(text)
                        seen_ids.add(id(block))

            # 3. 收集下方主栏连续行
            if scope_anchor:
                scope_col_left = max(0, scope_anchor.left - base_h)
                scope_col_right = min(doc_width, scope_anchor.right + base_h * 2)
            else:
                # 回退：若没有找到同行值，给一个偏左的主栏范围
                scope_col_left = scope_line.right
                scope_col_right = min(doc_width, int(doc_width * 0.7))

            boundary_top = find_boundary_top(
                scope_line.top,
                keywords=["登记机关", "市场监督", "国家企业信用信息公示系统网址"],
                col_left=0,
                col_right=doc_width,
            )

            stop_keywords = [
                "登记机关", "市场监督",
                "国家企业信用信息公示系统网址", "http", "https",
            ]

            prev = scope_anchor if scope_anchor else scope_line

            for block in blocks_below(
                prev,
                top_max=boundary_top,
                col_left=scope_col_left,
                col_right=scope_col_right,
                max_count=50,
            ):
                if id(block) in seen_ids:
                    continue

                text = (block.text or "").strip()
                if not text:
                    continue

                if any(kw in text for kw in stop_keywords):
                    break

                if re.fullmatch(r"\d{1,4}", text):
                    break
                if re.fullmatch(r"[年月日]", text):
                    break
                if is_date_text(text):
                    break

                # 主栏连续性控制：间隔过大则停止
                if block.top - prev.bottom > max(25, base_h * 2.5):
                    break

                scope_parts.append(text)
                seen_ids.add(id(block))
                prev = block

            return "".join(scope_parts)

        data["business_scope"] = extract_business_scope()

        return data