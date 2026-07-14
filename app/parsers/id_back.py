import re

from app.utils.layout import Layout


class IDBackParser:

    def parse(self, layout: Layout):

        data = {
            "type": "id_back",
            "authority": "",
            "valid_date": ""
        }

        # ---------- 签发机关 ----------

        authority_line = layout.find("签发机关")

        if authority_line:

            # 情况1：签发机关公安局
            text = authority_line.text.replace("签发机关", "").strip()

            if text:
                data["authority"] = text

            # 情况2：右侧
            if not data["authority"]:

                rights = layout.right_of(authority_line, tolerance=40)

                for item in rights:

                    if not item.text.strip():
                        continue

                    if "有效期限" in item.text:
                        break

                    data["authority"] += item.text

            # 情况3：下一行
            if not data["authority"]:

                for item in layout.below(authority_line):

                    if not item.text.strip():
                        continue

                    if "有效期限" in item.text:
                        break

                    data["authority"] = item.text.strip()
                    break

        # ---------- 有效期限 ----------

        valid_line = layout.find("有效期限")

        if valid_line:
            # 统一的日期模式：支持多种格式
            # 格式1: 2019.06.24-2039.06.24
            # 格式2: 2019-06-24-2039-06-24
            # 格式3: 20190624-20390624
            # 格式4: 2019.06.24 至 2039.06.24
            # 格式5: 20190624 至 20390624
            date_pattern = r"\d{4}[.\-]?\d{2}[.\-]?\d{2}\s*[-—至]\s*\d{4}[.\-]?\d{2}[.\-]?\d{2}"

            m = re.search(date_pattern, valid_line.text)

            if m:
                # 标准化日期格式：统一为 YYYY.MM.DD-YYYY.MM.DD
                raw_date = m.group()
                data["valid_date"] = self._normalize_date(raw_date)

            else:

                rights = layout.right_of(valid_line, tolerance=40)

                text = "".join(
                    i.text
                    for i in rights
                    if i.text.strip()
                )

                m = re.search(date_pattern, text)

                if m:
                    raw_date = m.group()
                    data["valid_date"] = self._normalize_date(raw_date)

                else:

                    for item in layout.below(valid_line):

                        if not item.text.strip():
                            continue

                        m = re.search(date_pattern, item.text)

                        if m:
                            raw_date = m.group()
                            data["valid_date"] = self._normalize_date(raw_date)
                            break

        return data

    def _normalize_date(self, date_str: str) -> str:
        """
        标准化日期格式
        输入: 20190624-2039.06.24, 2019.06.24-2039.06.24, 2019-06-24-2039-06-24 等
        输出: 2019.06.24-2039.06.24
        """
        # 将连续的数字插入分隔符
        def format_date_part(part: str) -> str:
            # 如果已经有分隔符，直接返回
            if '.' in part or '-' in part:
                return part
            # 格式化为 YYYY.MM.DD
            if len(part) == 8:  # YYYYMMDD
                return f"{part[:4]}.{part[4:6]}.{part[6:8]}"
            return part
        
        # 分割日期范围
        if '至' in date_str:
            separator = '至'
        elif '-' in date_str:
            separator = '-'
        else:
            separator = None
        
        if separator:
            start, end = date_str.split(separator, 1)
            start = format_date_part(start.strip())
            end = format_date_part(end.strip())
            return f"{start}-{end}"
        
        return date_str
