import re


def detect_type(texts):
    text = "".join(texts)
    if "公民身份号码" in text:
        return "id_front"
    if "签发机关" in text:
        return "id_back"
    if "统一社会信用代码" in text:
        return "business_license"
    return "unknown"


def parse_id_front(texts):
    text = "".join(texts)

    data = {
        "type": "id_front",
        "name": "",
        "gender": "",
        "nation": "",
        "birthday": "",
        "address": "",
        "id_number": ""
    }

    # 姓名
    m = re.search(r"姓名(.+?)(?:性别|$)", text)
    if m:
        data["name"] = m.group(1).strip()

    # 性别
    m = re.search(r"性别(男|女)", text)
    if m:
        data["gender"] = m.group(1)

    # 民族
    m = re.search(r"民族(\S+?)(?:出生|$)", text)
    if m:
        data["nation"] = m.group(1)

    # 出生
    m = re.search(r"出生(.+?)(?:住址|$)", text)
    if m:
        data["birthday"] = m.group(1).strip()

    # 住址
    m = re.search(r"住址(.+?)(?:公民身份号码|$)", text)
    if m:
        data["address"] = m.group(1).strip()

    # 身份证号
    m = re.search(r"(\d{17}[\dXx])", text)
    if m:
        data["id_number"] = m.group(1)

    return data


def parse_id_back(texts):
    text = "".join(texts)

    data = {
        "type": "id_back",
        "issue_authority": "",
        "valid_date": ""
    }

    m = re.search(r"签发机关(.+?)(?:有效期限|$)", text)
    if m:
        data["issue_authority"] = m.group(1).strip()

    m = re.search(r"有效期限(.+?)$", text)
    if m:
        data["valid_date"] = m.group(1).strip()

    return data


def parse_business_license(texts):
    text = "\n".join(texts)

    data = {"type": "business_license"}

    keys = [
        "统一社会信用代码",
        "名称",
        "类型",
        "住所",
        "法定代表人",
        "注册资本",
        "成立日期",
        "营业期限",
        "经营范围"
    ]

    lines = texts

    for i, line in enumerate(lines):
        for key in keys:
            if line.startswith(key):
                value = line.replace(key, "").strip()
                if value == "" and i + 1 < len(lines):
                    value = lines[i + 1].strip()
                data[key] = value

    return data


def parse(texts):
    tp = detect_type(texts)

    if tp == "id_front":
        return parse_id_front(texts)
    if tp == "id_back":
        return parse_id_back(texts)
    if tp == "business_license":
        return parse_business_license(texts)

    return {
        "type": "unknown",
        "texts": texts
    }