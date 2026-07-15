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
from typing import Optional

from app.utils.layout import Layout


# ------------------------------------------------------------------ #
#  统一社会信用代码工具                                                #
# ------------------------------------------------------------------ #

_USCC_CHARSET = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCC_CHAR_INDEX = {ch: i for i, ch in enumerate(_USCC_CHARSET)}
_USCC_WEIGHTS = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]


def _uscc_check_digit(code17: str) -> Optional[str]:
    """计算第18位校验字符，若前17位含非法字符返回None"""
    if len(code17) != 17:
        return None
    total = 0
    for ch, w in zip(code17, _USCC_WEIGHTS):
        if ch not in _USCC_CHAR_INDEX:
            return None
        total += _USCC_CHAR_INDEX[ch] * w
    return _USCC_CHARSET[(31 - total % 31) % 31]


def _validate_uscc(code: str) -> bool:
    """验证18位统一社会信用代码（含校验位）"""
    if len(code) != 18 or not all(c in _USCC_CHARSET for c in code):
        return False
    return _uscc_check_digit(code[:17]) == code[17]


def fix_credit_code(raw: str) -> str:
    """
    对18位信用代码进行OCR修正。

    修正策略：
    - 行政区划位（idx 2-7）：纯数字位，字母→数字
    - 混合位（idx 0-1, 8-17）：修正不在字符集中的字符
    - 校验位（idx 17）：若前17位合法且校验位是易混字符，自动修正
    """
    if len(raw) != 18 or _validate_uscc(raw):
        return raw

    chars = list(raw)

    # 行政区划位（idx 2-7）：强制转数字
    digit_corr = {'I': '1', 'O': '0', 'S': '5', 'Z': '2', 'B': '8', 'G': '6'}
    for idx in range(2, 8):
        if chars[idx].isalpha():
            chars[idx] = digit_corr.get(chars[idx], chars[idx])

    # 混合位（idx 0-1, 8-17）：修正非法字符
    mixed_corr = {'I': '1', 'O': '0', 'S': '5', 'V': 'U', 'Z': '2'}
    for idx in list(range(0, 2)) + list(range(8, 18)):
        if chars[idx] not in _USCC_CHARSET:
            chars[idx] = mixed_corr.get(chars[idx], chars[idx])

    # 校验位自动修正
    if all(c in _USCC_CHARSET for c in chars[:17]):
        expected = _uscc_check_digit("".join(chars[:17]))
        check_corr = {
            'I': '1', 'O': '0', 'S': '5', 'V': 'U', 'Z': '2',
            'l': '1', 'o': '0',
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

        all_lines = layout.all()
        if not all_lines:
            return data

        doc_width = max(line.right for line in all_lines)
        doc_height = max(line.bottom for line in all_lines)

        # ---------------------------------------------------------- #
        #  坐标工具函数                                                #
        #  不依赖Layout高层API，直接基于坐标过滤，行为可预期           #
        # ---------------------------------------------------------- #

        def blocks_same_row_right_of(anchor, row_tolerance: int = 40):
            """
            返回与anchor同行且在其右侧的块，按left升序。

            "右侧"定义：块的中心x > anchor的中心x，且块与anchor有水平接触
            （line.right > anchor.left），处理OCR块轻微重叠的情况。
            """
            anchor_cy = (anchor.top + anchor.bottom) / 2
            anchor_cx = (anchor.left + anchor.right) / 2
            result = [
                line for line in all_lines
                if line is not anchor
                and abs((line.top + line.bottom) / 2 - anchor_cy) <= row_tolerance
                and (line.left + line.right) / 2 > anchor_cx
                and line.right > anchor.left
            ]
            result.sort(key=lambda x: x.left)
            return result

        def blocks_below(anchor,
                         top_max: float = None,
                         col_left: float = None,
                         col_right: float = None,
                         max_count: int = 30):
            """
            返回anchor下方的块，按top升序。

            列范围过滤使用overlap模式：块与[col_left, col_right]有交集即通过，
            比严格的left/right过滤更宽松，适合地址、经营范围等可能换行缩进的内容。
            """
            _top_min = anchor.bottom
            _top_max = top_max if top_max is not None else doc_height
            _col_left = col_left if col_left is not None else 0
            _col_right = col_right if col_right is not None else doc_width

            result = [
                line for line in all_lines
                if line.top >= _top_min
                and line.top < _top_max
                and line.left < _col_right   # overlap：块左边在目标区域左边界左侧
                and line.right > _col_left   # overlap：块右边在目标区域右边界右侧
            ]
            result.sort(key=lambda x: x.top)
            return result[:max_count]

        def find_boundary_top(anchor, *keywords: str) -> float:
            """
            在anchor下方查找关键词行，返回最近一个的top坐标作为下边界。
            若未找到，返回doc_height。
            """
            bound = doc_height
            for kw in keywords:
                line = layout.find(kw)
                if line and line.top > anchor.top:
                    bound = min(bound, line.top)
            return bound

        # ---------------------------------------------------------- #
        #  通用辅助                                                    #
        # ---------------------------------------------------------- #

        def strip_label(text: str, *labels: str) -> str:
            """从文本中去除标签前缀及冒号"""
            for label in labels:
                if label in text:
                    return text.replace(label, "", 1).lstrip(":：").strip()
            return text.strip()

        def is_person_name(text: str) -> bool:
            """
            判断文本是否像人名。
            条件：2-10字符，至少2个汉字，无数字，无地址特征词。
            """
            t = text.strip()
            if not (2 <= len(t) <= 10):
                return False
            if re.search(r'\d', t):
                return False
            addr_keywords = [
                "层", "楼", "路", "街", "号", "市", "区", "省",
                "镇", "村", "县", "道", "广场", "大厦", "中心",
            ]
            if any(kw in t for kw in addr_keywords):
                return False
            chinese_count = sum(1 for c in t if '\u4e00' <= c <= '\u9fff')
            return chinese_count >= 2

        def clean_addr_text(text: str) -> str:
            """
            清理地址文本开头的OCR噪声字符。

            处理流程：
            1. 剥离开头的非汉字非数字字符（标点、字母等）
            2. 数字开头直接返回（门牌号）
            3. 第2字是行政词 → 第1字是合法地名，不截断
            4. 第1字在已知噪声字符集中 → 截断
            """
            t = text.strip()
            if not t:
                return t

            # 步骤1：剥离非汉字非数字前缀
            while t and not ('\u4e00' <= t[0] <= '\u9fff') and not t[0].isdigit():
                t = t[1:].strip()
            if not t:
                return t

            # 步骤2：数字开头直接返回
            if t[0].isdigit():
                return t

            # 步骤3：第2字是行政词 → 合法起始，不截断
            _ADMIN_SUFFIXES = {
                '省', '市', '区', '县', '镇', '村', '乡', '街', '路',
                '道', '号', '楼', '层', '幢', '栋', '室', '期',
                '州', '盟', '旗',
            }
            if len(t) >= 2 and t[1] in _ADMIN_SUFFIXES:
                return t

            # 步骤4：已知噪声字符（量词、偏旁部首等）
            _KNOWN_NOISE = {
                '斤', '两', '克', '升', '斗', '丈', '尺', '寸', '分',
                '卜', '厂', '囗', '冂', '凵', '匚',
            }
            if t[0] in _KNOWN_NOISE:
                t = t[1:].strip()

            return t

        def get_right_value(label: str, tolerance: int = 250) -> str:
            """
            获取标签右侧的值。
            优先从同一文本块中提取，其次找右侧相邻块。
            """
            label_line = layout.find(label)
            if not label_line:
                return ""
            # 同块：去除标签后有剩余内容
            remaining = strip_label(label_line.text, label)
            if remaining:
                return remaining
            # 右侧块
            right = layout.nearest_right(label_line, tolerance=tolerance)
            if right:
                return right.text.strip()
            return ""

        def get_right_value_any(*labels: str, tolerance: int = 250) -> str:
            """遍历候选标签，返回第一个非空结果"""
            for label in labels:
                v = get_right_value(label, tolerance)
                if v:
                    return v
            return ""

        # ---------------------------------------------------------- #
        #  统一社会信用代码                                            #
        # ---------------------------------------------------------- #

        def extract_credit_code() -> str:
            # P1：标签定位（最精确）
            raw = get_right_value_any(
                "统一社会信用代码", "社会信用代码", "注册号",
                tolerance=300,
            )
            if raw:
                m = re.search(r"[0-9A-Z]{18}", raw)
                if m:
                    return fix_credit_code(m.group())

            # P2：逐行扫描，优先返回通过校验的
            fallback = ""
            for line in all_lines:
                m = re.search(r"[0-9A-Z]{18}", line.text)
                if m:
                    candidate = fix_credit_code(m.group())
                    if _validate_uscc(candidate):
                        return candidate
                    if not fallback:
                        fallback = candidate
            if fallback:
                return fallback

            # P3：全文拼接回退（有跨行误匹配风险）
            joined = "".join(line.text for line in all_lines)
            m = re.search(r"[0-9A-Z]{18}", joined)
            return fix_credit_code(m.group()) if m else ""

        data["credit_code"] = extract_credit_code()

        # ---------------------------------------------------------- #
        #  名称                                                        #
        #  处理OCR拆分："名称值"、"名 称值"、"名"+"称值"              #
        # ---------------------------------------------------------- #

        def extract_name() -> str:
            candidates = []

            for label in ("名称", "名 称"):
                v = get_right_value(label, tolerance=250)
                if v:
                    candidates.append(v)

            # 处理"名"+"称xxx"拆分
            name_label = layout.find("名")
            if name_label:
                right = layout.nearest_right(name_label, tolerance=250)
                if right:
                    if right.text.startswith("称"):
                        v = right.text[1:].lstrip(":：").strip()
                        if v:
                            candidates.append(v)
                    else:
                        candidates.append(right.text.strip())

            return max(candidates, key=len) if candidates else ""

        data["name"] = extract_name()

        # ---------------------------------------------------------- #
        #  类型                                                        #
        #  处理OCR拆分："类型值"、"类 型值"、"类"+"型值"              #
        # ---------------------------------------------------------- #

        def extract_type() -> str:
            candidates = []

            for label in ("类型", "类 型"):
                v = get_right_value(label, tolerance=250)
                if v:
                    candidates.append(v)

            # 处理"类"+"型xxx"拆分
            type_label = layout.find("类")
            if type_label:
                right = layout.nearest_right(type_label, tolerance=250)
                if right:
                    if right.text.startswith("型"):
                        v = right.text[1:].lstrip(":：").strip()
                        if v:
                            candidates.append(v)
                    else:
                        candidates.append(right.text.strip())  # 注意：写入candidates

            return max(candidates, key=len) if candidates else ""

        data["type_name"] = extract_type()

        # ---------------------------------------------------------- #
        #  法定代表人 / 负责人                                         #
        #  多策略：同块 → Layout API → 坐标扫描同行 → 坐标扫描下方    #
        # ---------------------------------------------------------- #

        def extract_legal_person() -> str:
            legal_label = layout.find_any("法定代表人", "负责人")
            if not legal_label:
                return ""

            # 策略1：同一文本块（标签+值在同一OCR块）
            for kw in ("法定代表人", "负责人"):
                if kw in legal_label.text:
                    v = strip_label(legal_label.text, kw)
                    if v and is_person_name(v):
                        return v

            # 策略2：Layout API nearest_right
            right = layout.nearest_right(legal_label, tolerance=300)
            if right and is_person_name(right.text.strip()):
                return right.text.strip()

            # 策略3：坐标扫描同行右侧（API失效时的备选）
            for block in blocks_same_row_right_of(legal_label, row_tolerance=40):
                if is_person_name(block.text.strip()):
                    return block.text.strip()

            # 策略4：坐标扫描下方同列
            for block in blocks_below(
                legal_label,
                col_left=legal_label.left - 50,
                col_right=legal_label.right + 300,
                max_count=3,
            ):
                if is_person_name(block.text.strip()):
                    return block.text.strip()

            return ""

        data["legal_person"] = extract_legal_person()

        # ---------------------------------------------------------- #
        #  注册资本 / 成立日期                                         #
        # ---------------------------------------------------------- #

        data["capital"] = get_right_value_any(
            "注册资本", "注册资金",
            tolerance=250,
        )
        data["establish_date"] = get_right_value_any(
            "成立日期", "注册日期", "设立日期",
            tolerance=250,
        )

        # ---------------------------------------------------------- #
        #  住所 / 地址                                                 #
        #                                                              #
        #  已知难点（来自实际OCR数据）：                               #
        #  · "住所"被拆成"住"(left=208)和"所"(left=2328)两个块        #
        #  · 地址在文档右侧栏(left≈2372)，与"所"块有37px水平重叠      #
        #  · 地址第一行开头有OCR噪声字符"斤"                           #
        #                                                              #
        #  策略A：找到完整"住所"标签 → 取右侧内容                      #
        #  策略B：找"住"块 → 找"所"块 → 取"所"块同行右侧内容          #
        #         锚点设为地址内容块（非"所"块），确保下方查找正确      #
        # ---------------------------------------------------------- #

        def extract_address() -> str:
            addr_parts = []
            addr_anchor = None  # 地址内容的起始块（非标签块）

            # ── 策略A：完整标签定位 ──────────────────────────────────
            addr_label = layout.find_any("住所", "营业场所", "经营场所", "注册地址")
            if addr_label:
                for kw in ("住所", "营业场所", "经营场所", "注册地址"):
                    if kw in addr_label.text:
                        v = strip_label(addr_label.text, kw)
                        if v:
                            addr_parts.append(clean_addr_text(v))
                        break

                if not addr_parts:
                    right = layout.nearest_right(addr_label, tolerance=500)
                    if right and right.text.strip():
                        addr_parts.append(clean_addr_text(right.text))
                        addr_anchor = right  # 锚点是内容块

                if not addr_anchor:
                    addr_anchor = addr_label

            # ── 策略B："住"+"所"拆分处理 ─────────────────────────────
            if not addr_label:
                zhu_label = layout.find("住")
                suo_label = None

                if zhu_label:
                    # 查找"所"块（text == "所" 或以"所"开头）
                    for line in all_lines:
                        if line is zhu_label:
                            continue
                        if line.text == "所" or line.text.startswith("所"):
                            suo_label = line
                            break

                    if suo_label:
                        # 找"所"块同行右侧的内容块
                        # 使用 blocks_same_row_right_of（中心点判断，处理轻微重叠）
                        same_row = blocks_same_row_right_of(
                            suo_label,
                            row_tolerance=40,
                        )

                        if same_row:
                            # 取最左边的块作为地址第一段
                            first_block = same_row[0]
                            first_text = clean_addr_text(first_block.text)
                            if first_text:
                                addr_parts.append(first_text)
                            # 关键：锚点设为地址内容块，而非"所"块
                            # 这样 blocks_below 才能从第一行之后向下找
                            addr_anchor = first_block
                        else:
                            # "所"块本身包含地址内容（如"所郑州市..."）
                            rest = clean_addr_text(
                                suo_label.text.lstrip("所:：").strip()
                            )
                            if rest:
                                addr_parts.append(rest)
                            addr_anchor = suo_label

            if not addr_anchor:
                return ""

            # ── 确定下边界 ───────────────────────────────────────────
            bottom_bound = find_boundary_top(
                addr_anchor,
                "经营范围", "登记机关", "市场监督", "法定代表人", "负责人",
            )

            # ── 收集后续地址行 ───────────────────────────────────────
            # 列范围：以锚点left为基准，向左允许200px偏移，右侧不限
            addr_col_left = addr_anchor.left - 200
            addr_col_right = doc_width

            stop_kw = [
                "经营范围", "类型", "登记机关", "市场监督",
                "国家企业", "法定代表人", "负责人", "注册资本",
            ]

            seen = {id(addr_anchor)}
            for block in blocks_below(
                addr_anchor,
                top_max=bottom_bound,
                col_left=addr_col_left,
                col_right=addr_col_right,
                max_count=5,
            ):
                if id(block) in seen:
                    continue
                if any(kw in block.text for kw in stop_kw):
                    break
                # 纯数字/日期行（登记日期区域）
                if re.fullmatch(r'[\d年月日\s]+', block.text.strip()):
                    break
                seen.add(id(block))
                addr_parts.append(block.text.strip())

            return "".join(addr_parts)

        data["address"] = extract_address()

        # ---------------------------------------------------------- #
        #  经营范围                                                    #
        #                                                              #
        #  难点：                                                      #
        #  · 同行右侧块与下方块可能重复收集                             #
        #  · 登记机关后的年份数字行需要停止                             #
        #                                                              #
        #  策略：seen_ids去重 + 坐标扫描替代链式nearest_below          #
        # ---------------------------------------------------------- #

        def extract_business_scope() -> str:
            scope_line = layout.find("经营范围")
            if not scope_line:
                return ""

            scope_parts = []
            seen_ids = {id(scope_line)}

            def add_block(line, text: str):
                """去重后加入结果"""
                lid = id(line)
                if lid not in seen_ids and text.strip():
                    seen_ids.add(lid)
                    scope_parts.append(text.strip())

            # 同块内容（"经营范围"与值在同一OCR块）
            if "经营范围" in scope_line.text:
                v = strip_label(scope_line.text, "经营范围")
                if v:
                    scope_parts.append(v)

            # 同行右侧块
            for item in layout.right_of(scope_line, tolerance=40):
                add_block(item, item.text)

            # 下边界：登记机关或文档底部
            scope_bottom = find_boundary_top(scope_line, "登记机关", "市场监督")

            # 列范围：以scope_line为基准（overlap模式）
            scope_col_left = scope_line.left - 50
            scope_col_right = scope_line.right + 100

            stop_kw = [
                "登记机关", "市场监督",
                "国家企业信用信息公示系统", "http://", "https://",
            ]

            for block in blocks_below(
                scope_line,
                top_max=scope_bottom,
                col_left=scope_col_left,
                col_right=scope_col_right,
                max_count=30,
            ):
                if id(block) in seen_ids:
                    continue
                if any(w in block.text for w in stop_kw):
                    break
                # 孤立数字行（年份）
                if re.fullmatch(r'\d{1,4}', block.text.strip()):
                    break
                # 单个日期字符
                if re.fullmatch(r'[年月日]', block.text.strip()):
                    break
                add_block(block, block.text)

            return "".join(scope_parts)

        data["business_scope"] = extract_business_scope()

        return data