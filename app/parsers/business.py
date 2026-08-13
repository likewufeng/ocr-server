"""
营业执照解析器 v6 - 完整最终版

已验证可正确解析的字段：
  - 统一社会信用代码或旧版注册号（含OCR修正+校验）
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
from app.utils.ocr_corrections import normalize_known_admin_text


# ------------------------------------------------------------------ #
#  企业编号工具                                                        #
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
    raw = (raw or "").strip().upper()
    if len(raw) != 18 or _validate_uscc(raw):
        return raw

    chars = list(raw)

    digit_corr = {
        "I": "1", "O": "0", "S": "5", "Z": "2", "B": "8", "G": "6",
    }
    mixed_corr = {
        "I": "1", "O": "0", "S": "5", "V": "U", "Z": "2",
    }

    for idx in range(2, 8):
        if chars[idx].isalpha():
            chars[idx] = digit_corr.get(chars[idx], chars[idx])

    for idx in list(range(0, 2)) + list(range(8, 18)):
        if chars[idx] not in _USCC_CHARSET:
            chars[idx] = mixed_corr.get(chars[idx], chars[idx])

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


def fix_legacy_registration_number(raw: str) -> str:
    """规范化三证合一前的 15 位营业执照注册号。"""
    compact = re.sub(r"\s+", "", (raw or "").strip().upper())
    if len(compact) != 15:
        return compact

    corrections = {
        "O": "0", "I": "1", "L": "1", "S": "5", "Z": "2", "B": "8", "G": "6",
    }
    return "".join(corrections.get(char, char) for char in compact)


def _validate_legacy_registration_number(code: str) -> bool:
    """旧版营业执照注册号必须为 15 位纯数字。"""
    return bool(re.fullmatch(r"\d{15}", code or ""))


def is_valid_credit_code(raw: str) -> bool:
    """校验统一社会信用代码或旧版注册号。

    为保持接口兼容，旧版营业执照的 15 位注册号也填入 ``credit_code``。
    """
    return _validate_uscc(fix_credit_code(raw or "")) or _validate_legacy_registration_number(
        fix_legacy_registration_number(raw or "")
    )


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

        def same_row_right_blocks(anchor, tol: Optional[int] = None):
            """
            找 anchor 右侧、且大致同行的文本块。
            使用中心点判断，允许轻微重叠。
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
            找 anchor 下方的块。
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
            找 after_top 之后最近的边界关键词 top。
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
            t = (text or "").strip()
            return t in label_keywords

        def is_person_name(text: str) -> bool:
            t = (text or "").strip()
            if not (2 <= len(t) <= 10):
                return False
            if re.search(r"\d", t):
                return False
            if looks_like_capital(t):
                return False
            bad_keywords = [
                "层", "楼", "路", "街", "号", "市", "区", "省",
                "镇", "村", "县", "道", "广场", "中心", "大厦",
                "公司", "企业", "名称", "类型", "住所", "法定", "代表",
                "负责人", "注册", "资本", "成立", "日期", "营业", "期限",
                "经营", "范围",
            ]
            if any(kw in t for kw in bad_keywords):
                return False
            chinese_count = sum(1 for c in t if "\u4e00" <= c <= "\u9fff")
            return chinese_count >= 2

        def is_date_text(text: str) -> bool:
            t = re.sub(r"\s+", "", (text or "").strip())
            return bool(re.fullmatch(r"\d{4}年\d{1,2}月\d{1,2}日", t))

        def normalize_chinese_date(text: str) -> str:
            normalized = re.sub(r"\s+", "", (text or "").strip())
            m = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", normalized)
            if not m:
                return normalized
            year, month, day = m.groups()
            return f"{year}年{int(month):02d}月{int(day):02d}日"

        def looks_like_capital(text: str) -> bool:
            t = (text or "").strip()
            if not t:
                return False
            if is_date_text(t):
                return False
            # 单个“万”“陆”等字既可能是人名，也可能是金额的一部分。金额
            # 判断至少需要数字、货币单位，或连续两个中文金额数字，不能仅凭
            # 一个中文数字排除合法的法定代表人姓名。
            return bool(re.search(
                r"\d|[圆元整]|[壹贰叁肆伍陆柒捌玖拾佰仟零]{2,}", t
            ))

        def looks_like_company_name(text: str) -> bool:
            t = (text or "").strip()
            if len(t) < 4:
                return False
            if re.search(r"\d", t):
                return False
            company_suffixes = [
                "有限公司", "有限责任公司", "股份有限公司", "集团有限公司",
                "公司", "合伙企业", "个人独资企业", "农民专业合作社",
            ]
            return any(suffix in t for suffix in company_suffixes)

        def looks_like_business_name(text: str) -> bool:
            t = (text or "").strip()
            if looks_like_company_name(t):
                return True
            if len(t) < 4 or re.search(r"\d", t):
                return False
            individual_suffixes = (
                "网店", "商店", "经营部", "服务部", "工作室", "店", "坊", "厂",
            )
            return any(t.endswith(suffix) for suffix in individual_suffixes)

        def extract_company_type(text: str) -> str:
            """Extract a legal entity type from OCR text that may contain nearby fields."""
            t = (text or "").strip()
            type_names = (
                "其他有限责任公司", "有限责任公司", "股份有限公司", "个人独资企业",
                "合伙企业", "农民专业合作社", "个体工商户", "非公司企业法人",
                "全民所有制", "分公司",
            )
            pattern = r"({})(?:[（(][^（）()]{{0,40}}[）)])?".format(
                "|".join(re.escape(name) for name in type_names)
            )
            match = re.search(pattern, t)
            return match.group(0) if match else ""

        def looks_like_company_type(text: str) -> bool:
            """仅用于补偿“类型”标签漏字后的候选值校验。"""
            return bool(extract_company_type(text))

        def clean_addr_text(text: str) -> str:
            """
            清理地址首部OCR噪声：
            - 去掉前导标点/字母
            - 去掉已知噪声汉字，如“斤”
            """
            t = (text or "").strip()
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

        def normalize_business_scope_text(text: str) -> str:
            t = (text or "").strip()
            corrections = {
                "许可项日": "许可项目",
                "许可项H": "许可项目",
                "许可项口": "许可项目",
                "批准的项H": "批准的项目",
                "批准的项口": "批准的项目",
                "经相关部门批准后方可": "经相关部门批准后方可",
                "和关部门": "相关部门",
                "计机": "计算机",
                "销件": "销售",
                "仿息": "信息",
                "信总": "信息",
                "工联网": "互联网",
                "工连网": "互联网",
                "数燃": "数据",
                "智使": "智能",
                "不合教育": "不含教育",
                "技术资询": "技术咨询",
            }
            for wrong, right in corrections.items():
                t = t.replace(wrong, right)
            # 营业执照经营范围末尾常见固定表述。仅修复 OCR 漏掉开括号和
            # “依”字的明确模式，不对普通业务正文做猜测性文字替换。
            t = re.sub(r"(?<!依)法须经批准的项目", "（依法须经批准的项目", t)
            return t

        def collect_row_sequence(blocks,
                                 gap_threshold: Optional[int] = None,
                                 skip_exact=None,
                                 strip_prefixes=()):
            """
            从同行右侧块中收集连续文本。
            遇到横向大间隔时停止，避免跨列串字段。
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

        def find_label_anchor(label_keywords):
            """Find a label, including labels split into adjacent OCR blocks."""
            line = find_contains(*label_keywords)
            if line:
                matched = next(label for label in label_keywords if label in line.text)
                return line, {id(line)}, matched, ""

            for anchor in all_lines:
                anchor_text = (anchor.text or "").strip()
                if not anchor_text:
                    continue
                blocks = [anchor] + same_row_right_blocks(
                    anchor, tol=row_tol(anchor, 0.35)
                )
                previous = None
                fragments = []
                merged = ""
                for block in blocks:
                    text = (block.text or "").strip()
                    if not text:
                        continue
                    if previous is not None and block.left - previous.right > max(30, base_h * 4):
                        break
                    merged += text
                    fragments.append(block)
                    for label in label_keywords:
                        if label == merged:
                            return anchor, {id(item) for item in fragments}, label, ""
                        if merged.startswith(label):
                            return (
                                anchor,
                                {id(item) for item in fragments},
                                label,
                                merged[len(label):],
                            )
                    if not any(label.startswith(merged) for label in label_keywords):
                        break
                    previous = block

            return None, set(), "", ""

        def extract_row_value_by_label(label_keywords,
                                       validator=None,
                                       row_scale: float = 1.0):
            """
            典型行字段提取：
            1. 同块去标签
            2. 同行右侧取第一个满足条件的值
            """
            line, label_fragment_ids, matched_label, inline_value = find_label_anchor(
                label_keywords
            )
            if not line:
                return ""

            if inline_value and (validator is None or validator(inline_value)):
                return inline_value

            if matched_label in line.text:
                remain = strip_label(line.text, matched_label)
                if remain and (validator is None or validator(remain)):
                    return remain

            rights = same_row_right_blocks(line, tol=row_tol(line, row_scale))
            for block in rights:
                if id(block) in label_fragment_ids:
                    continue
                text = (block.text or "").strip()
                if not text:
                    continue
                if validator is None or validator(text):
                    return text

            return ""

        # ---------------------------------------------------------- #
        #  地址前缀推断/补全                                            #
        # ---------------------------------------------------------- #

        def infer_province_from_name(name: str) -> str:
            """
            从企业名称前缀推断省份，如：
            河南省吉米特信息技术有限公司 -> 河南省
            """
            if not name:
                return ""
            m = re.match(r"^([\u4e00-\u9fff]{2,6}省)", name.strip())
            return m.group(1) if m else ""

        def infer_city_from_credit_code(code: str) -> str:
            """
            从统一社会信用代码推断地级市。
            这里只放了当前常见的河南映射，可按需扩展。
            """
            if not code or len(code) < 8:
                return ""

            admin_code = code[2:8]

            city_map = {
                "410100": "郑州市",
                "410300": "洛阳市",
                "410500": "安阳市",
                "410700": "新乡市",
                "410800": "焦作市",
                "410900": "濮阳市",
                "411000": "许昌市",
                "411100": "漯河市",
                "411200": "三门峡市",
                "411300": "南阳市",
                "411400": "商丘市",
                "411500": "信阳市",
                "411600": "周口市",
                "411700": "驻马店市",
                "419001": "济源市",
            }
            return city_map.get(admin_code, "")

        def collect_nearby_address_fragments(addr_anchor, boundary_top: float):
            """
            收集地址锚点附近的短碎片，用于补全：
            郑东 + 新 -> 郑东新区
            """
            if not addr_anchor:
                return []

            candidates = []
            col_left = max(0, addr_anchor.left - base_h * 2)
            col_right = doc_width

            for line in all_lines:
                if line is addr_anchor:
                    continue
                if line.top < addr_anchor.top - base_h * 2:
                    continue
                if line.top >= boundary_top:
                    continue
                if not (line.left < col_right and line.right > col_left):
                    continue

                text = (line.text or "").strip()
                if not text:
                    continue
                if len(text) > 4:
                    continue
                if not all('\u4e00' <= c <= '\u9fff' for c in text):
                    continue
                if text in {"住", "所", "经营范围", "登记机关"}:
                    continue

                candidates.append((line, text))

            seen = set()
            result = []
            for _, text in sorted(candidates, key=lambda x: (x[0].top, x[0].left)):
                if text not in seen:
                    seen.add(text)
                    result.append(text)
            return result

        def complete_address_prefix(address: str, name: str, credit_code: str, nearby_fragments) -> str:
            """
            对已提取的地址做前缀补全：
            - 公司名推断省份
            - 信用代码推断城市
            - OCR碎片推断区县（如 郑东 + 新 -> 郑东新区）
            """
            addr = (address or "").strip()
            if not addr:
                return addr

            province = infer_province_from_name(name)
            city = infer_city_from_credit_code(credit_code)

            district = ""
            frags = set(nearby_fragments or [])

            if "郑东新区" in frags:
                district = "郑东新区"
            elif "郑东" in frags and ("新" in frags or "新区" in frags or "东新区" in frags):
                district = "郑东新区"

            prefix = ""
            if province and not addr.startswith(province):
                prefix += province
            has_province_prefix = bool(re.match(r"^[\u4e00-\u9fff]{2,6}省", addr))
            if city and city not in addr and (prefix or not has_province_prefix):
                prefix += city
            if district and district not in addr:
                prefix += district

            return prefix + addr

        # ---------------------------------------------------------- #
        #  统一社会信用代码 / 三证合一前注册号                         #
        # ---------------------------------------------------------- #

        def extract_credit_code() -> str:
            # 三证合一前营业执照使用 15 位纯数字“注册号”。只有检测到该
            # 标签时才接收 15 位数字，避免将日期、电话等误判为企业编号。
            registration_labels = ("注册号", "注册号码")
            legacy_registration = ""
            for line in all_lines:
                compact = re.sub(r"\s+", "", line.text or "")
                label = next((item for item in registration_labels if item in compact), None)
                if label is None:
                    continue

                candidates = [compact.split(label, 1)[1]]
                candidates.extend(block.text or "" for block in same_row_right_blocks(line))
                for text in candidates:
                    match = re.search(
                        r"[0-9OILSZBG]{15}", re.sub(r"\s+", "", text.upper())
                    )
                    if not match:
                        continue
                    candidate = fix_legacy_registration_number(match.group())
                    if _validate_legacy_registration_number(candidate):
                        legacy_registration = candidate
                        break

                if legacy_registration:
                    break

            # 18 位统一社会信用代码有校验位，可安全地从全图搜索；但不能
            # 将“证照编号”等任意 18 位数字作为信用代码返回。
            labeled_fallback = ""
            for line in all_lines:
                compact = re.sub(r"\s+", "", line.text or "")
                is_uscc_label_line = any(
                    label in compact for label in ("统一社会信用代码", "社会信用代码", "信用代码")
                )
                for match in re.finditer(r"[0-9A-Za-z]{18}", compact):
                    candidate = fix_credit_code(match.group())
                    if _validate_uscc(candidate):
                        return candidate
                    if is_uscc_label_line and not labeled_fallback:
                        labeled_fallback = candidate

            if labeled_fallback:
                return labeled_fallback

            return legacy_registration

        data["credit_code"] = extract_credit_code()

        # ---------------------------------------------------------- #
        #  名称                                                        #
        # ---------------------------------------------------------- #

        def extract_name() -> str:
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

            name_label = find_exact("名")
            if name_label:
                # “名称”被拆为左侧高框“名”和右侧“称+企业名称”时，优先
                # 使用带“称”前缀的同栏文本，避免高框容差误纳入下一行“类型”。
                for block in same_row_right_blocks(name_label, tol=row_tol(name_label, 1.0)):
                    raw = (block.text or "").strip()
                    if not raw.startswith("称"):
                        continue
                    candidate = raw[1:].lstrip(":：").strip()
                    if looks_like_business_name(candidate):
                        return candidate

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

            name_boundary_top = find_boundary_top(
                0,
                keywords=["法定代表人", "负责人", "住所", "经营范围"],
            )
            for line in all_lines:
                text = (line.text or "").strip()
                if not text or line.top >= name_boundary_top:
                    continue
                if text.startswith("称"):
                    candidate = text[1:].lstrip(":：").strip()
                    if looks_like_business_name(candidate):
                        return candidate
                if looks_like_business_name(text) and not is_label_like(text):
                    return text

            return ""

        data["name"] = extract_name()

        # ---------------------------------------------------------- #
        #  类型                                                        #
        # ---------------------------------------------------------- #

        def extract_type() -> str:
            for kw in ("类型", "类 型"):
                line = find_contains(kw)
                if line:
                    remain = strip_label(line.text, kw)
                    candidate = extract_company_type(remain)
                    if candidate:
                        return candidate
                    row_parts = collect_row_sequence(
                        same_row_right_blocks(line, tol=row_tol(line, 1.0))
                    )
                    if row_parts:
                        vals = [text for _, text in row_parts if not is_label_like(text)]
                        candidate = extract_company_type("".join(vals))
                        if candidate:
                            return candidate

            # “类型”可能拆成“类”+“型”+值，也可能只识别出“型”+值。
            for label_text in ("类", "型"):
                type_label = find_exact(label_text)
                if not type_label:
                    continue
                row_parts = collect_row_sequence(
                    same_row_right_blocks(type_label, tol=row_tol(type_label, 1.0)),
                    skip_exact={"型"} if label_text == "类" else set(),
                    strip_prefixes=("型",) if label_text == "类" else (),
                )
                if row_parts:
                    vals = [text for _, text in row_parts if not is_label_like(text)]
                    candidate = extract_company_type("".join(vals))
                    if candidate:
                        return candidate

            # OCR 偶尔会把“类型”中的“类”漏掉，例如：
            # “型有限责任公司（自然人独资）”。仅接受合法企业类型，避免误取正文。
            for line in all_lines:
                text = (line.text or "").strip()
                match = re.match(r"^[型类](?:\s*型)?[\s:：]*(.+)$", text)
                if not match:
                    continue
                candidate = extract_company_type(match.group(1))
                if candidate:
                    return candidate

            for line in all_lines:
                candidate = extract_company_type(line.text)
                if candidate:
                    return candidate

            return ""

        data["type_name"] = extract_type()

        # ---------------------------------------------------------- #
        #  法定代表人                                                  #
        # ---------------------------------------------------------- #

        def extract_legal_person() -> str:
            line = find_contains("法定代表人", "负责人", "经营者")
            if not line:
                return ""

            for kw in ("法定代表人", "负责人", "经营者"):
                if kw in line.text:
                    remain = strip_label(line.text, kw)
                    if remain and is_person_name(remain):
                        return remain

            rights = same_row_right_blocks(line, tol=row_tol(line, 1.0))
            for block in rights:
                text = (block.text or "").strip()
                if is_person_name(text):
                    return text

                # 浅色姓名有时会与企业名称水印叠加，OCR 结果表现为
                # “姓名 + 企业名称末尾”。已得到企业名称时，剥离重叠后缀后
                # 仅在剩余内容符合姓名规则时采用。
                company_name = (data.get("name") or "").strip()
                if company_name:
                    max_prefix = min(10, len(text) - 2)
                    for prefix_length in range(2, max_prefix + 1):
                        suffix = text[prefix_length:]
                        candidate = text[:prefix_length]
                        if len(suffix) >= 4 and company_name.endswith(suffix) and is_person_name(candidate):
                            return candidate

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
            ("注册资本", "注册资金", "生册资本"),
            validator=looks_like_capital,
            row_scale=1.0,
        )

        data["establish_date"] = extract_row_value_by_label(
            ("成立日期", "注册日期", "设立日期"),
            validator=is_date_text,
            row_scale=1.0,
        )
        data["establish_date"] = normalize_chinese_date(data["establish_date"])

        # ---------------------------------------------------------- #
        #  地址                                                        #
        # ---------------------------------------------------------- #

        def extract_address() -> str:
            """
            地址优先级：
            A. 完整标签：住所 / 营业场所 / 经营场所 / 注册地址
            B. 单独“所”标签
            C. 单独“住”标签

            最后再做一次前缀补全：
            - 名称推断省份
            - 信用代码推断城市
            - OCR碎片推断郑东新区
            """
            addr_parts = []
            addr_anchor = None

            def collect_address_from_label(label_line, skip_exact=None, strip_prefixes=(), row_scale=1.2):
                if not label_line:
                    return None, None

                rights = same_row_right_blocks(label_line, tol=row_tol(label_line, row_scale))
                # 地址首行和续行可能轻微上下重叠，且续行左边界偶尔比首行
                # 早 1-2 像素。优先选择与“住所”标签中心线最接近的块，避免
                # 将第二行误当作首行。
                rights.sort(key=lambda block: (abs(cy(block) - cy(label_line)), block.left))
                row_parts = collect_row_sequence(
                    rights,
                    gap_threshold=max(30, base_h * 4),
                    skip_exact=skip_exact,
                    strip_prefixes=strip_prefixes,
                )

                for block, text in row_parts:
                    cleaned = clean_addr_text(text)
                    if looks_like_address(cleaned):
                        return cleaned, block

                for block, text in row_parts:
                    cleaned = clean_addr_text(text)
                    if cleaned:
                        return cleaned, block

                return None, None

            # A. 完整标签
            full_addr_line = find_contains("住所", "营业场所", "经营场所", "注册地址")
            if full_addr_line:
                for kw in ("住所", "营业场所", "经营场所", "注册地址"):
                    if kw in full_addr_line.text:
                        remain = strip_label(full_addr_line.text, kw)
                        if remain:
                            cleaned = clean_addr_text(remain)
                            if cleaned:
                                addr_parts.append(cleaned)
                                addr_anchor = full_addr_line
                            break

                if not addr_parts:
                    first_text, first_block = collect_address_from_label(full_addr_line)
                    if first_text:
                        addr_parts.append(first_text)
                        addr_anchor = first_block

            # B. 尝试“所”
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

            # OCR 可能把“住”漏掉，并把“所”和地址识别在同一个文本框中。
            if not addr_parts:
                for line in all_lines:
                    text = (line.text or "").strip()
                    if not re.match(r"^所(?:[\s:：]+)?", text):
                        continue
                    cleaned = clean_addr_text(
                        re.sub(r"^所(?:[\s:：]+)?", "", text, count=1)
                    )
                    if looks_like_address(cleaned):
                        addr_parts.append(cleaned)
                        addr_anchor = line
                        break

            # 某些竖排表头会把“所”并入“型所”等文本框。前面未找到完整
            # 住所标签时，允许从含“所”的表头块向右寻找第一个地址值。
            if not addr_parts:
                for line in all_lines:
                    if "所" not in (line.text or ""):
                        continue
                    first_text, first_block = collect_address_from_label(line)
                    if first_text and looks_like_address(first_text):
                        addr_parts.append(first_text)
                        addr_anchor = first_block
                        break

            # C. 尝试“住”
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
                        if block.left >= doc_width * 0.35 and looks_like_address(cleaned):
                            addr_parts.append(cleaned)
                            addr_anchor = block
                            break

            # OCR 也可能把“所”漏掉，并把“住”和地址识别在同一个文本框中。
            if not addr_parts:
                for line in all_lines:
                    text = (line.text or "").strip()
                    if not re.match(r"^住[\s:：]+", text):
                        continue
                    cleaned = clean_addr_text(
                        re.sub(r"^住[\s:：]+", "", text, count=1)
                    )
                    if looks_like_address(cleaned):
                        addr_parts.append(cleaned)
                        addr_anchor = line
                        break

            if not addr_parts or not addr_anchor:
                return ""

            addr_col_left = max(0, addr_anchor.left - base_h * 2)
            addr_col_right = doc_width

            boundary_top = find_boundary_top(
                addr_anchor.top,
                keywords=[
                    "经营范围", "登记机关", "市场监督",
                    "市场监",
                    "组成形式",
                    "法定代表人", "负责人", "注册资本", "注册资金",
                    "成立日期", "注册日期", "设立日期", "类型",
                    "国家企业信用信息公示系统网址", "国家市场监督管理总局监制",
                ],
                col_left=addr_col_left,
                col_right=addr_col_right,
            )

            # 标签和值可能上下错位几个像素，例如法人标签的 top 晚于其
            # 右侧姓名。只在住所边界内收窄，并排除地址当前行，避免把
            # 同行另一列的地址文本误当成下一字段边界。
            for boundary_line in all_lines:
                boundary_text = (boundary_line.text or "").strip()
                if boundary_line.top <= addr_anchor.top:
                    continue
                if not (boundary_line.left < addr_col_right and boundary_line.right > addr_col_left):
                    continue
                if not any(keyword in boundary_text for keyword in (
                    "经营范围", "登记机关", "市场监督", "法定代表人", "负责人",
                    "市场监",
                    "组成形式",
                    "注册资本", "注册资金", "成立日期", "注册日期", "设立日期", "类型",
                )):
                    continue
                same_row_tops = [
                    candidate.top
                    for candidate in all_lines
                    if candidate.top > addr_anchor.top
                    and abs(cy(candidate) - cy(boundary_line)) <= row_tol(boundary_line, 0.35)
                ]
                if same_row_tops:
                    boundary_top = min(boundary_top, min(same_row_tops))

            stop_keywords = [
                "经营范围", "登记机关", "市场监督",
                "市场监",
                "组成形式",
                "法定代表人", "负责人", "注册资本", "注册资金",
                "法定代表", "注册资", "成立日", "注册日", "设立日", "类型",
                "国家企业信用信息公示系统网址", "http", "https",
            ]
            stop_values = [
                value for value in (
                    data.get("type_name"),
                    data.get("legal_person"),
                    data.get("capital"),
                    data.get("establish_date"),
                ) if value
            ]
            scope_start_keywords = ("一般项目", "许可项目", "许可项", "经营项目")

            prev = addr_anchor
            seen = {id(addr_anchor)}
            # 同一“住所”标签的拆分块不应成为地址续行，例如“住”在上一行、
            # “所”在地址正文之后才被 OCR 返回的情况。
            for label_fragment in all_lines:
                if (label_fragment.text or "").strip() not in {"住", "所"}:
                    continue
                if abs(cy(label_fragment) - cy(addr_anchor)) <= row_tol(addr_anchor, 1.5):
                    seen.add(id(label_fragment))
            seen_texts = {clean_addr_text(part) for part in addr_parts if part}

            # 地址续行经常与首行上下重叠，例如首行 bottom=276、续行
            # top=274。blocks_below 要求 top >= 首行 bottom，会把这种
            # 合法续行漏掉。地址专用收集允许轻微重叠，但仍沿用字段边界、
            # 垂直间距和停止关键词约束，避免跨字段串入。
            address_continuations = [
                block for block in all_lines
                if id(block) not in seen
                and block.top > addr_anchor.top
                and block.top < boundary_top
                and block.left < addr_col_right
                and block.right > addr_col_left
            ]
            address_continuations.sort(key=lambda block: (block.top, block.left))

            for block in address_continuations[:10]:
                if id(block) in seen:
                    continue

                text = (block.text or "").strip()
                if not text:
                    continue

                if is_label_like(text):
                    continue

                # 副本页码可能以独立“（1）”块紧邻地址出现，不能把它拼入
                # 住所；同一正文块内的“1幢（8）”不走这里，会被保留。
                if re.fullmatch(r"[（(]\d{1,3}[）)]", text):
                    continue

                if block.top - prev.bottom > max(25, base_h * 3):
                    break

                if any(kw in text for kw in stop_keywords):
                    break

                if any(kw in text for kw in scope_start_keywords):
                    break

                if is_date_text(text) or re.fullmatch(r"[\d年月日\s]+", text):
                    break

                if (block.bottom - block.top) > base_h * 2.2 and len(text) <= 2:
                    continue

                cleaned = clean_addr_text(text)
                if cleaned:
                    if any(value in cleaned for value in stop_values):
                        break
                    if cleaned in seen_texts:
                        continue
                    addr_parts.append(cleaned)
                    seen_texts.add(cleaned)
                    prev = block
                    seen.add(id(block))

            address = "".join(addr_parts)
            # 旧版副本常将页码“（1）”贴在地址 OCR 文本块末尾。该模式是
            # 页码而非地址正文；其他括号数字（如“1幢（8）”）必须保留。
            address = re.sub(r"[（(]1[）)]$", "", address)
            nearby_fragments = collect_nearby_address_fragments(addr_anchor, boundary_top)
            address = complete_address_prefix(
                address=address,
                name=data.get("name", ""),
                credit_code=data.get("credit_code", ""),
                nearby_fragments=nearby_fragments,
            )

            return normalize_known_admin_text(address)

        data["address"] = extract_address()

        # ---------------------------------------------------------- #
        #  经营范围                                                    #
        # ---------------------------------------------------------- #

        def extract_business_scope() -> str:
            scope_line, scope_label_ids, _, _ = find_label_anchor(
                ("经营范围", "经营范", "经营围")
            )
            if not scope_line:
                return ""

            scope_parts = []
            seen_ids = set(scope_label_ids)

            scope_label = next(
                (
                    label for label in ("经营范围", "经营范", "经营围")
                    if label in scope_line.text
                ),
                "",
            )
            if scope_label:
                remain = strip_label(scope_line.text, scope_label)
                if remain:
                    scope_parts.append(remain)

            stop_keywords = [
                "登记机关", "登记机", "市场监督",
                "国家企业信用信息公示系统网址", "http", "https",
            ]

            scope_candidates = []
            min_top = scope_line.top - row_tol(scope_line, 0.8)
            min_left = scope_line.right - base_h * 2
            # 使用经营范围首行正文的右边界确定内容栏。固定按整图比例截断会在
            # 双栏版式中把左栏长文本的后续行误判为右栏，从而截断经营范围。
            same_row_values = [
                block for block in same_row_right_blocks(scope_line, tol=row_tol(scope_line, 0.8))
                if id(block) not in seen_ids
                and (block.text or "").strip()
                and not is_label_like((block.text or "").strip())
            ]
            first_scope_value = next(
                (
                    block for block in same_row_values
                    if block.left >= scope_line.right - base_h * 2
                ),
                None,
            )
            content_right = first_scope_value.right if first_scope_value else scope_line.right
            max_left = min(doc_width, content_right + base_h * 2)

            boundary_top = find_boundary_top(
                scope_line.top,
                keywords=["登记机关", "登记机", "市场监督", "国家企业信用信息公示系统网址", "变更"],
                col_left=min_left,
                col_right=max_left,
            )

            for block in all_lines:
                if id(block) in seen_ids:
                    continue
                if block.top < min_top or block.top >= boundary_top:
                    continue
                if block.right <= min_left or block.left >= max_left:
                    continue

                text = (block.text or "").strip()
                if not text:
                    continue

                # OCR 常把“经/营/范/围”“住/所”等标签拆成独立块；这些块
                # 位于经营范围同行时不能拼进正文。
                if is_label_like(text) or text in {"经", "营", "范", "围"}:
                    continue

                # 竖排登记机关、市场监督等水印块可能与正文在纵向重叠。它们
                # 通常远高于正常文字行且较短，不能作为经营范围内容。
                if h(block) > max(base_h * 2.5, 60) and len(text) < 20:
                    continue

                if (
                    block.bottom < scope_line.top
                    and not any(kw in text for kw in ("一般项目", "许可项目", "许可项", "项目"))
                ):
                    continue

                if any(kw in text for kw in stop_keywords):
                    continue

                # 地址续行可能与“经营范围”标签同高，且位于另一栏；这类
                # 文本已经被地址解析器收集，不应混入经营范围。
                if text and text in data.get("address", ""):
                    continue

                if re.fullmatch(r"\d{1,4}", text):
                    continue
                if re.fullmatch(r"[年月日]", text):
                    continue
                if is_date_text(text):
                    continue

                scope_candidates.append(block)

            # 同一视觉行的 OCR 块可能有不同高度，按顶部排序会把右侧块排到
            # 左侧正文前。中心点更能还原人眼阅读顺序。
            scope_candidates.sort(key=lambda block: (cy(block), block.left))

            prev = None
            for block in scope_candidates:
                text = (block.text or "").strip()
                if not text:
                    continue

                if prev is not None and block.top - prev.bottom > max(25, base_h * 2.8):
                    break

                scope_parts.append(text)
                prev = block

            return normalize_business_scope_text("".join(scope_parts))

        data["business_scope"] = extract_business_scope()

        return data
