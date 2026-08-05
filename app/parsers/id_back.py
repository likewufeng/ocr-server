import re
from datetime import date

from app.utils.layout import Layout
from app.utils.ocr_corrections import normalize_known_admin_text


class IDBackParser:
    def _normalize_authority(self, text: str) -> str:
        if not text:
            return ""

        return normalize_known_admin_text(text)

    def parse(self, layout: Layout):

        data = {
            "type": "id_back",
            "authority": "",
            "valid_date": ""
        }

        all_lines = layout.all() or []

        # ---------- 签发机关 ----------

        authority_line = layout.find("签发机关")

        if authority_line:

            # 情况1：同块，例如：签发机关郑州市公安局
            text = authority_line.text.replace("签发机关", "", 1).strip()
            if text:
                data["authority"] = self._normalize_authority(text)

            # 情况2：右侧
            if not data["authority"]:
                # 有些图片中“签发机关”标签框会和签发机关内容框轻微重叠，
                # 不能只依赖 right_of 的“完全在右侧”条件。
                rights = [
                    item for item in layout.same_row(authority_line, tolerance=40)
                    if item is not authority_line
                    and item.center_x > authority_line.center_x
                ]
                authority_parts = []

                for item in rights:
                    t = (item.text or "").strip()
                    if not t:
                        continue
                    if "有效期限" in t:
                        break
                    authority_parts.append(t)

                if authority_parts:
                    data["authority"] = self._normalize_authority("".join(authority_parts))

            # 情况3：下方
            if not data["authority"]:
                for item in layout.below(authority_line):
                    t = (item.text or "").strip()
                    if not t:
                        continue
                    if "有效期限" in t:
                        break
                    data["authority"] = self._normalize_authority(t)
                    break

        # 情况4：全文回退
        if not data["authority"]:
            full_text = "".join(layout.texts() or []).replace(" ", "").replace("\n", "")
            m = re.search(r"签发机关(.+?)(有效期限|$)", full_text)
            if m:
                data["authority"] = self._normalize_authority(m.group(1).strip())

        # ---------- 有效期限 ----------

        valid_line = layout.find("有效期限")

        if valid_line:

            # 情况1：同块
            raw = self._extract_valid_date_from_text(valid_line.text)
            if raw:
                data["valid_date"] = raw

            # 情况2：右侧
            if not data["valid_date"]:
                rights = layout.right_of(valid_line, tolerance=40)
                text = "".join(
                    (i.text or "").strip()
                    for i in rights
                    if (i.text or "").strip()
                )
                raw = self._extract_valid_date_from_text(text)
                if raw:
                    data["valid_date"] = raw

            # 情况3：下方
            if not data["valid_date"]:
                for item in layout.below(valid_line):
                    t = (item.text or "").strip()
                    if not t:
                        continue
                    raw = self._extract_valid_date_from_text(t)
                    if raw:
                        data["valid_date"] = raw
                        break

        # 情况4：全文回退
        if not data["valid_date"]:
            full_text = "".join(layout.texts() or []).replace(" ", "").replace("\n", "")
            data["valid_date"] = self._extract_valid_date_from_text(full_text)

        return data

    def _extract_valid_date_from_text(self, text: str) -> str:
        """
        从文本中提取有效期限，并标准化为：
        YYYY.MM.DD-YYYY.MM.DD
        或
        YYYY.MM.DD-长期
        """
        if not text:
            return ""

        t = text.strip()
        t = t.replace(" ", "")
        t = t.replace("—", "-").replace("–", "-").replace("－", "-")
        t = t.replace("至", "-")
        t = (
            t.replace("．", ".")
            .replace("。", ".")
            .replace("·", ".")
            .replace(",", ".")
            .replace("，", ".")
        )
        t = t.replace("有效期限", "")

        # 1) 先匹配：YYYYMMDD / YYYY.MM.DD / YYYY-MM-DD 这几种
        #    结束部分支持 日期 或 长期
        patterns = [
            # 2019.06.24-2039.06.24 / 2019-06-24-2039-06-24 / 20190624-20390624
            r"(\d{4}[.\-]?\d{2}[.\-]?\d{2})-(\d{4}[.\-]?\d{2}[.\-]?\d{2}|长期)",
            # 中文日期格式：2019年06月24日-2039年06月24日 / 2019年06月24日至长期
            r"(\d{4}年\d{1,2}月\d{1,2}日)-?(\d{4}年\d{1,2}月\d{1,2}日|长期)",
        ]

        for pattern in patterns:
            m = re.search(pattern, t)
            if m:
                start = self._normalize_one_date(m.group(1))
                end = self._normalize_one_date(m.group(2))
                if start and end:
                    return f"{start}-{end}"

        # 2) 再尝试更宽松匹配（适配 OCR 把连接符吃掉的场景）
        #    例如：2019062420390624
        m = re.search(r"(\d{8})(\d{8})", t)
        if m:
            start = self._normalize_one_date(m.group(1))
            end = self._normalize_one_date(m.group(2))
            if start and end:
                return f"{start}-{end}"

        return ""

    def _normalize_one_date(self, s: str) -> str:
        """
        把单个日期标准化为 YYYY.MM.DD
        支持：
        - 20190624
        - 2019.06.24
        - 2019-06-24
        - 2019年06月24日
        - 长期
        """
        if not s:
            return ""

        s = s.strip()
        if s == "长期":
            return s

        # 中文格式
        m = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
        if m:
            y, mo, d = m.groups()
            return self._format_valid_date(y, mo, d)

        # 支持纯数字、完整分隔和 OCR 漏掉其中一个分隔符的混合格式，
        # 例如 200410.27 / 2004.10-27 / 20041027。
        m = re.fullmatch(r"(\d{4})[.\-]?(\d{1,2})[.\-]?(\d{1,2})", s)
        if m:
            y, mo, d = m.groups()
            return self._format_valid_date(y, mo, d)

        return ""

    @staticmethod
    def _format_valid_date(year: str, month: str, day: str) -> str:
        try:
            normalized = date(int(year), int(month), int(day))
        except ValueError:
            return ""
        return f"{normalized.year:04d}.{normalized.month:02d}.{normalized.day:02d}"
