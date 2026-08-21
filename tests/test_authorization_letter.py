import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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

    def test_personal_letter_response_does_not_include_seal(self):
        result = self.parser.to_dict({"delegator": "吴烽"})
        self.assertNotIn("seal", result["data"])


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

    def test_signature_region_is_saved_as_artifact(self):
        image = np.full((120, 600, 3), 255, dtype=np.uint8)
        result = self.service._signature_from_region(
            image, 1, [10, 20, 200, 100], "test"
        )
        with TemporaryDirectory() as directory:
            saved = self.service._save_signature_artifact(
                result, image, Path(directory), "delegator", 1
            )
            self.assertEqual(saved["artifact"], "page_001_delegator_signature_01.jpg")
            self.assertTrue((Path(directory) / saved["artifact"]).exists())

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

    def test_horizontal_id_page_is_split_into_front_and_back(self):
        image = np.full((500, 1000, 3), 255, dtype=np.uint8)
        ocr_result = {
            "texts": [
                "姓名吴烽",
                "性别男民族汉",
                "出生1991年8月15日",
                "住址河南省渑池县",
                "公民身份号码411221199108152534",
                "中华人民共和国",
                "居民身份证",
                "签发机关渑池县公安局",
                "有效期限2019.06.24-2039.06.24",
            ],
            "boxes": [
                [80, 100, 220, 130],
                [80, 140, 260, 170],
                [80, 180, 300, 210],
                [80, 220, 300, 250],
                [80, 280, 380, 310],
                [580, 80, 840, 120],
                [580, 130, 850, 170],
                [580, 240, 850, 270],
                [580, 290, 900, 320],
            ],
        }
        regions = self.service._split_id_regions(image, ocr_result)
        self.assertEqual(set(regions), {"id_front", "id_back"})
        self.assertLess(regions["id_front"][1][2], regions["id_back"][1][0])

    def test_field_roi_accepts_only_checksum_valid_id_number(self):
        self.assertEqual(
            self.service._field_value_from_ocr(
                "delegator_id", ["411221199108152534"]
            ),
            "411221199108152534",
        )
        self.assertEqual(
            self.service._field_value_from_ocr(
                "delegator_id", ["410105201703060622"]
            ),
            "",
        )

    def test_invalid_id_candidate_can_be_retained_for_manual_review(self):
        value = "410105201703060622"
        self.assertEqual(len(value), 18)
        self.assertFalse(self.service._is_valid_id_number(value))

    def test_handwritten_role_roi_rejects_body_text_as_name(self):
        self.assertEqual(
            self.service._field_value_from_ocr(
                "trustee", ["委托人因办理CA数字证书相关业务需要，兹委托受托人李身份"]
            ),
            "",
        )
        self.assertEqual(
            self.service._field_value_from_ocr("trustee", ["受托人李四身份证号"]),
            "李四",
        )

    def test_address_roi_rejects_neighboring_field_labels(self):
        self.assertEqual(
            self.service._field_value_from_ocr(
                "delegator_address", ["身份证号码：410105住址：郑州市某区某路"]
            ),
            "郑州市某区某路",
        )

    def test_low_confidence_name_requests_clean_variant(self):
        self.assertTrue(
            self.service._field_needs_variant(
                "delegator", "吴锋张", {"scores": [0.7586]}
            )
        )

    def test_tight_template_roi_keeps_handwritten_trustee_name_isolated(self):
        image = np.zeros((2105, 1488, 3), dtype=np.uint8)
        regions = self.service._ocr_field_regions(
            image,
            {
                "texts": [
                    "委托人：吴锋张",
                    "委托人因办理CA数字证书相关业务需要，兹委托受托人李身份",
                ],
                "boxes": [[199, 212, 616, 321], [208, 566, 1258, 632]],
            },
        )
        self.assertEqual(regions["delegator"], [327, 199, 624, 336])
        self.assertEqual(regions["trustee"], [1078, 536, 1205, 652])
        self.assertEqual(
            self.service._field_value_from_ocr("trustee", ["李四"]), "李四"
        )
        self.assertEqual(
            self.service._field_value_from_ocr("trustee", ["人李四"]), "李四"
        )
        self.assertEqual(
            self.service._field_value_from_ocr("trustee", ["李四", "委托人办"]),
            "李四",
        )


if __name__ == "__main__":
    unittest.main()
