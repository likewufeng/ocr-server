import unittest

import cv2
import numpy as np

from app.parsers.authorization_letter import AuthorizationLetterParser
from app.services.authorization_letter_service import AuthorizationLetterService


class AuthorizationLetterParserTest(unittest.TestCase):
    def setUp(self):
        self.parser = AuthorizationLetterParser()

    def test_parse_multiline_template_fields(self):
        text = """
授权委托书
委托人：_________吴烽_______________
身份证号码：_________411221199108152534_______________
住址：_____郑东新区正商博雅广场1 号楼15 层___________________
联系电话：___18503983676_____________________
委托人因办理业务需要，兹委托受托人
张三
（身份证号
410105199204152423
）作为委托人的授权代理人。
本授权委托书的有效期限自__2023__年_3_月_2_日起至
_2029___年_4_月_25_日止。
签署日期：__2026____年___4___月____15__日
附件：受托人身份证明文件
"""
        result = self.parser.parse_text_content(text)
        self.assertEqual(result["delegator"], "吴烽")
        self.assertEqual(result["delegator_id"], "411221199108152534")
        self.assertEqual(result["delegator_address"], "郑东新区正商博雅广场1号楼15层")
        self.assertEqual(result["delegator_phone"], "18503983676")
        self.assertEqual(result["trustee"], "张三")
        self.assertEqual(result["trustee_id"], "410105199204152423")
        self.assertEqual(
            result["validity_period"],
            {"start_date": "2023-03-02", "end_date": "2029-04-25"},
        )
        self.assertEqual(result["signing_date"], "2026-04-15")


class AuthorizationLetterEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.service = AuthorizationLetterService()

    def test_blank_signature_line_is_not_detected(self):
        image = np.full((120, 600, 3), 255, dtype=np.uint8)
        cv2.line(image, (30, 65), (560, 65), (0, 0, 0), 2)
        result = self.service._signature_from_region(
            image, 1, [0, 0, 600, 120], "test"
        )
        self.assertEqual(result["status"], "not_detected")

    def test_handwritten_strokes_are_detected(self):
        image = np.full((120, 600, 3), 255, dtype=np.uint8)
        cv2.line(image, (30, 75), (560, 75), (0, 0, 0), 2)
        points = np.array(
            [[150, 70], [170, 25], [185, 68], [210, 35], [225, 72]],
            dtype=np.int32,
        )
        cv2.polylines(image, [points], False, (0, 0, 0), 4)
        result = self.service._signature_from_region(
            image, 1, [0, 0, 600, 120], "test"
        )
        self.assertEqual(result["status"], "detected")

    def test_attachment_identity_mismatch_is_reported(self):
        parsed = {
            "delegator_id": "411221199108152534",
            "trustee": "张三",
            "trustee_id": "410105199204152423",
        }
        front = {
            "data": {
                "type": "id_front",
                "name": "吴烽",
                "id_number": "411221199108152534",
            }
        }
        checks = self.service._build_consistency_checks(parsed, front, None)
        statuses = {item["code"]: item["status"] for item in checks}
        self.assertEqual(statuses["trustee_name_matches_id_front"], "failed")
        self.assertEqual(statuses["trustee_id_matches_id_front"], "failed")
        self.assertEqual(statuses["attachment_matches_delegator_not_trustee"], "failed")


if __name__ == "__main__":
    unittest.main()
