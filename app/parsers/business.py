from app.utils.layout import Layout


class BusinessParser:

    def parse(self, layout: Layout):

        texts = layout.texts()

        data = {
            "type": "business_license"
        }

        keys = [
            "统一社会信用代码",
            "名称",
            "类型",
            "法定代表人",
            "注册资本",
            "成立日期",
            "营业期限",
            "住所",
            "经营范围"
        ]

        for i, line in enumerate(texts):

            for key in keys:

                if line.startswith(key):

                    value = line.replace(key, "").strip()

                    if value == "" and i + 1 < len(texts):
                        value = texts[i + 1]

                    data[key] = value

        return data