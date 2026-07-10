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

            m = re.search(
                r"\d{4}[.\-]\d{2}[.\-]\d{2}\s*[-—至]\s*\d{4}[.\-]\d{2}[.\-]\d{2}",
                valid_line.text
            )

            if m:

                data["valid_date"] = m.group()

            else:

                rights = layout.right_of(valid_line, tolerance=40)

                text = "".join(
                    i.text
                    for i in rights
                    if i.text.strip()
                )

                m = re.search(
                    r"\d{4}[.\-]\d{2}[.\-]\d{2}\s*[-—至]\s*\d{4}[.\-]\d{2}[.\-]\d{2}",
                    text
                )

                if m:
                    data["valid_date"] = m.group()

                else:

                    for item in layout.below(valid_line):

                        if not item.text.strip():
                            continue

                        m = re.search(
                            r"\d{4}[.\-]\d{2}[.\-]\d{2}\s*[-—至]\s*\d{4}[.\-]\d{2}[.\-]\d{2}",
                            item.text
                        )

                        if m:
                            data["valid_date"] = m.group()
                            break

        return data