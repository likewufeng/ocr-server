# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-13 17:04:48
#LastEditTime: 2026-07-14 11:18:41
#LastEditors: WuFeng <763467339@qq.com>
#Description: 授权书解析器
#FilePath: /ocr-server/app/parsers/authorization_letter.py
#Copyright 版权声明
#
"""
授权委托书 PDF 解析器

专门用于解析授权委托书 PDF 文件，提取关键信息：
- 委托人
- 委托人身份证
- 地址
- 受托人
- 受托人身份证
- 有效期
- 签署日期
- 受托人签字（手写签名）
- 受托人身份证正反面
"""

import re
from typing import Optional, Dict, Any
from PyPDF2 import PdfReader
import pdf2image
import os
import tempfile


class AuthorizationLetterParser:
    """授权委托书解析器"""
    
    def __init__(self, ocr_service=None):
        self.ocr_service = ocr_service
    
    def extract_text_from_pdf(self, pdf_path: str) -> list[str]:
        """
        从PDF中提取文本内容
        返回每页的文本列表
        """
        try:
            reader = PdfReader(pdf_path)
            texts = []
            for page in reader.pages:
                text = page.extract_text()
                texts.append(text if text else "")
            return texts
        except Exception as e:
            raise ValueError(f"无法读取PDF文件: {e}")
    
    def extract_images_from_pdf(self, pdf_path: str) -> list:
        """
        从PDF中提取图片
        返回图片对象列表
        """
        try:
            images = pdf2image.convert_from_path(pdf_path)
            return images
        except Exception as e:
            # 如果pdf2image失败，返回空列表
            return []
    
    def parse_text_content(self, text: str) -> Dict[str, Any]:
        """
        解析文本内容，提取关键信息
        """
        result = {
            "delegator": None,           # 委托人
            "delegator_id": None,        # 委托人身份证
            "delegator_address": None,   # 委托人地址
            "delegator_phone": None,     # 委托人联系电话
            "trustee": None,             # 受托人
            "trustee_id": None,          # 受托人身份证
            "validity_period": None,     # 有效期
            "signing_date": None,        # 签署日期
            "trustee_signature": None,   # 受托人签字
        }
        
        # 1. 提取委托人
        delegator_match = re.search(r'委托人[：:]{1,2}[_\s]*([^_\n]+)', text)
        if delegator_match:
            result["delegator"] = delegator_match.group(1).strip()
        
        # 2. 提取所有身份证号码
        all_id_numbers = re.findall(r'([0-9Xx]{15,18})', text)
        
        # 3. 提取委托人身份证（通常在"身份证号码："后面）
        delegator_id_match = re.search(r'身份证号码[：:]{0,2}[_\s]*([0-9Xx]{15,18})', text)
        if delegator_id_match:
            result["delegator_id"] = delegator_id_match.group(1).strip()
        elif all_id_numbers:
            # 如果没有明确的委托人身份证，取第一个
            result["delegator_id"] = all_id_numbers[0]
        
        # 4. 提取受托人身份证
        # 从"受托人...身份证号"模式中提取
        trustee_id_match = re.search(r'受托人[^\n]*?身份证号[\s]*([0-9Xx]{15,18})', text)
        if trustee_id_match:
            result["trustee_id"] = trustee_id_match.group(1).strip()
        elif len(all_id_numbers) >= 2 and not result["trustee_id"]:
            # 如果找到了多个身份证号，第二个可能是受托人
            for id_num in all_id_numbers:
                if id_num != result.get("delegator_id"):
                    result["trustee_id"] = id_num
                    break
        
        # 5. 提取委托人地址
        address_match = re.search(r'住址[：:]{1,2}[_\s]*([^_\n]+)', text)
        if address_match:
            result["delegator_address"] = address_match.group(1).strip()
        
        # 6. 提取委托人联系电话
        phone_match = re.search(r'联系电话[：:]{1,2}[_\s]*([0-9\-]{7,15})', text)
        if phone_match:
            result["delegator_phone"] = phone_match.group(1).strip()
        
        # 7. 提取受托人
        trustee_match = re.search(r'受托人[：:]{1,2}[_\s]*([^_\n]+)', text)
        if not trustee_match:
            # 尝试从"委托受托人"提取
            trustee_match = re.search(r'委托.*?受托人[（\(]?([^）\)_\n]+)', text)
        if not trustee_match:
            # 尝试从"受托人张三"这样的模式
            trustee_match = re.search(r'受托人([^\d_]{2,5})', text)
        if trustee_match:
            result["trustee"] = trustee_match.group(1).strip()
        
        # 8. 提取有效期（使用直接数字提取）
        if '有效期' in text or '有效期限' in text:
            start_idx = text.find('有效期')
            if start_idx >= 0:
                # 从有效期开始往后找
                substring = text[start_idx:start_idx+300]
                # 提取所有数字
                all_numbers = re.findall(r'\d+', substring)
                if len(all_numbers) >= 6:
                    # 格式通常是：年 月 日 年 月 日
                    try:
                        start_year = all_numbers[0]
                        start_month = all_numbers[1]
                        start_day = all_numbers[2]
                        end_year = all_numbers[3]
                        end_month = all_numbers[4]
                        end_day = all_numbers[5]
                        result["validity_period"] = {
                            "start_date": f"{start_year}-{start_month.zfill(2)}-{start_day.zfill(2)}",
                            "end_date": f"{end_year}-{end_month.zfill(2)}-{end_day.zfill(2)}"
                        }
                    except IndexError:
                        pass
        
        # 9. 提取签署日期
        if '签署日期' in text:
            start_idx = text.find('签署日期')
            if start_idx >= 0:
                substring = text[start_idx:start_idx+100]
                all_numbers = re.findall(r'\d+', substring)
                if len(all_numbers) >= 3:
                    try:
                        year = all_numbers[0]
                        month = all_numbers[1]
                        day = all_numbers[2]
                        result["signing_date"] = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                    except IndexError:
                        pass
        
        return result
    
    def parse_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """
        解析授权委托书 PDF 文件
        
        Args:
            pdf_path: PDF 文件路径
        
        Returns:
            解析结果字典
        """
        result = {
            "delegator": None,
            "delegator_id": None,
            "delegator_address": None,
            "delegator_phone": None,
            "trustee": None,
            "trustee_id": None,
            "validity_period": None,
            "signing_date": None,
            "trustee_signature": None,
            "trustee_id_front": None,
            "trustee_id_back": None,
            "pages": [],
            "raw_text": "",
        }
        
        # 1. 提取文本内容
        try:
            page_texts = self.extract_text_from_pdf(pdf_path)
            result["pages"] = page_texts
            result["raw_text"] = "\n".join(page_texts)
            
            # 解析所有页的文本
            for text in page_texts:
                page_result = self.parse_text_content(text)
                # 合并结果
                for key, value in page_result.items():
                    if value and not result[key]:
                        result[key] = value
        except Exception as e:
            result["error"] = f"文本提取失败: {e}"
        
        # 2. 提取图片内容（用于签名和身份证扫描件）
        # 由于第三页是扫描图片，需要 OCR 识别
        # 但考虑到内存限制，我们暂时标记为需要人工确认
        try:
            # 使用 PyMuPDF 提取图片
            import fitz
            doc = fitz.open(pdf_path)
            
            # 检查第三页是否有图片
            if len(doc) > 2:
                page = doc[2]
                image_list = page.get_images(full=True)
                if image_list:
                    # 第三页有图片，标记为需要人工确认
                    result["trustee_signature"] = "需要人工确认签名"
                    result["trustee_id_front"] = "需要人工确认身份证正面"
                    result["trustee_id_back"] = "需要人工确认身份证反面"
            
            doc.close()
        except ImportError:
            # 如果没有安装 fitz，跳过图片提取
            result["warning"] = "PyMuPDF 未安装，无法检测图片内容"
        except Exception as e:
            result["warning"] = f"图片检测失败: {e}"
        
        # 3. 后处理：清理数据
        result = self.postprocess_result(result)
        
        return result
    
    def postprocess_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        后处理结果，清理和格式化数据
        """
        # 格式化身份证号码
        if result.get("delegator_id"):
            result["delegator_id"] = result["delegator_id"].upper()
        if result.get("trustee_id"):
            result["trustee_id"] = result["trustee_id"].upper()
        
        # 格式化地址
        if result.get("delegator_address"):
            result["delegator_address"] = result["delegator_address"].replace("_", "")
        
        # 格式化姓名
        if result.get("delegator"):
            result["delegator"] = result["delegator"].replace("_", "").strip()
        if result.get("trustee"):
            result["trustee"] = result["trustee"].replace("_", "").strip()
        
        return result
    
    def to_dict(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        将结果转换为标准格式
        """
        return {
            "status": "success" if not result.get("error") else "partial",
            "data": {
                "delegator": result.get("delegator"),
                "delegator_id": result.get("delegator_id"),
                "delegator_address": result.get("delegator_address"),
                "delegator_phone": result.get("delegator_phone"),
                "trustee": result.get("trustee"),
                "trustee_id": result.get("trustee_id"),
                "validity_period": result.get("validity_period"),
                "signing_date": result.get("signing_date"),
                "trustee_signature": result.get("trustee_signature"),
                "trustee_id_front": result.get("trustee_id_front"),
                "trustee_id_back": result.get("trustee_id_back"),
            },
            "metadata": {
                "pages_count": len(result.get("pages", [])),
                "error": result.get("error"),
                "warning": result.get("warning"),
            }
        }
