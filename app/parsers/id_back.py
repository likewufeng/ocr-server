import re

from app.utils.layout import Layout


class IDBackParser:

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
                data["authority"] = text

            # 情况2：右侧
            if not data["authority"]:
                rights = layout.right_of(authority_line, tolerance=40)
                authority_parts = []

                for item in rights:
                    t = (item.text or "").strip()
                    if not t:
                        continue
                    if "有效期限" in t:
                        break
                    authority_parts.append(t)

                if authority_parts:
                    data["authority"] = "".join(authority_parts)

            # 情况3：下方
            if not data["authority"]:
                for item in layout.below(authority_line):
                    t = (item.text or "").strip()
                    if not t:
                        continue
                    if "有效期限" in t:
                        break
                    data["authority"] = t
                    break

        # 情况4：全文回退
        if not data["authority"]:
            full_text = "".join(layout.texts() or []).replace(" ", "").replace("\n", "")
            m = re.search(r"签发机关(.+?)(有效期限|$)", full_text)
            if m:
                data["authority"] = m.group(1).strip()

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
        t = t.replace("．", ".").replace("。", ".").replace("·", ".")
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
            return f"{y}.{int(mo):02d}.{int(d):02d}"

        # 纯数字 YYYYMMDD
        m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
        if m:
            y, mo, d = m.groups()
            return f"{y}.{mo}.{d}"

        # 点 / 横线格式
        m = re.fullmatch(r"(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})", s)
        if m:
            y, mo, d = m.groups()
            return f"{y}.{int(mo):02d}.{int(d):02d}"

        return ""