# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-13 17:04:40
#LastEditTime: 2026-07-14 09:30:16
#LastEditors: WuFeng <763467339@qq.com>
#Description: 授权书接口
#FilePath: /ocr-server/app/api/authorization_letter.py
#Copyright 版权声明
#
"""
授权委托书 PDF 解析 API

提供授权委托书 PDF 文件的解析接口，提取关键信息。
"""

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import tempfile
import os

from app.schemas.response import ApiResponse
from app.parsers.authorization_letter import AuthorizationLetterParser
from app.services.ocr_service import ocr_service

router = APIRouter(prefix="/authorization", tags=["Authorization Letter"])

# 创建解析器实例
parser = AuthorizationLetterParser(ocr_service=ocr_service)


@router.post("/letter/parse")
async def parse_authorization_letter(file: UploadFile = File(...)):
    """
    解析授权委托书 PDF 文件
    
    接受 PDF 文件上传，提取以下关键信息：
    - 委托人
    - 委托人身份证
    - 委托人地址
    - 委托人联系电话
    - 受托人
    - 受托人身份证
    - 有效期
    - 签署日期
    - 受托人签字（需要人工确认）
    - 受托人身份证正反面（需要人工确认）
    
    返回结构化 JSON 数据。
    """
    # 创建临时文件
    suffix = file.filename.split(".")[-1].lower()
    
    # 验证文件类型
    if suffix != "pdf":
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")
    
    # 保存临时文件
    with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    
    try:
        # 解析 PDF
        result = parser.parse_pdf(tmp_path)
        
        # 格式化结果
        formatted_result = parser.to_dict(result)
        
        return ApiResponse.success(formatted_result)
        
    except Exception as e:
        return ApiResponse.error(f"解析失败: {str(e)}")
    finally:
        # 清理临时文件
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass


@router.post("/letter/parse-text")
async def parse_authorization_letter_text(text: str):
    """
    解析授权委托书文本内容
    
    接受文本内容，提取关键信息。
    适用于已经提取出文本的 PDF。
    """
    try:
        # 直接解析文本
        result = parser.parse_text_content(text)
        formatted_result = parser.to_dict({"data": result, "metadata": {}})
        return ApiResponse.success(formatted_result)
    except Exception as e:
        return ApiResponse.error(f"解析失败: {str(e)}")


@router.post("/letter/parse-raw")
async def parse_authorization_letter_raw(file: UploadFile = File(...)):
    """
    解析授权委托书 PDF 文件 - 返回原始信息
    
    接受 PDF 文件上传，返回原始内容，包括：
    - 原始文本（每页文本）
    - 页数
    - 文件大小
    - 文件名
    
    不进行结构化解析，直接返回 PDF 内容。
    """
    import os
    from PyPDF2 import PdfReader
    
    # 验证文件类型
    suffix = file.filename.split(".")[-1].lower()
    if suffix != "pdf":
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")
    
    # 读取文件内容
    file_content = await file.read()
    file_size = len(file_content)
    
    # 保存临时文件用于读取
    with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name
    
    try:
        # 读取 PDF 文本内容
        reader = PdfReader(tmp_path)
        
        raw_data = {
            "filename": file.filename,
            "file_size": file_size,
            "pages_count": len(reader.pages),
            "pages": [],
            "raw_text": ""
        }
        
        # 提取每页文本
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            raw_data["pages"].append({
                "page_number": i + 1,
                "text": text if text else "",
                "char_count": len(text) if text else 0
            })
            raw_data["raw_text"] += text + "\n" if text else ""
        
        return ApiResponse.success(raw_data)
        
    except Exception as e:
        return ApiResponse.error(f"读取 PDF 失败: {str(e)}")
    finally:
        # 清理临时文件
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass
