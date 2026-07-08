import re

from app.utils.layout import Layout


class IDBackParser:

    def parse(self, layout: Layout):

        text = "".join(layout.texts())

        data = {
            "type": "id_back",
            "issue_authority": "",
            "valid_date": ""
        }

        m = re.search(r"签发机关(.+?)(有效期限|$)", text)
        if m:
            data["issue_authority"] = m.group(1).strip()

        m = re.search(r"有效期限(.+)", text)
        if m:
            data["valid_date"] = m.group(1).strip()

        return data