# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-13 17:04:40
#LastEditTime: 2026-07-14 11:18:08
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
    
    **注意：使用 PyPDF2 提取文本，仅适用于文本 PDF**
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
    
    **注意：使用 PyPDF2 提取文本，仅适用于文本 PDF**
    """
    try:
        # 直接解析文本
        result = parser.parse_text_content(text)
        formatted_result = parser.to_dict({"data": result, "metadata": {}})
        return ApiResponse.success(formatted_result)
    except Exception as e:
        return ApiResponse.error(f"解析失败: {str(e)}")





@router.post("/letter/parse-ocr")
async def parse_authorization_letter_ocr(file: UploadFile = File(...)):
    """
    解析授权委托书 PDF 文件 - 使用 OCR 布局分析
    
    接受 PDF/图片 文件上传，使用 PaddleX OCR 与布局分析，返回完整的结构化结果：
    - 布局分析结果（每个文本块的内容、位置、类型）
    - Markdown 格式文本
    - 图片信息（印章、身份证扫描件等）
    - 原始图片链接
    
    **适用场景：**
    - 扫描图片 PDF
    - 需要布局信息的场景
    - 需要识别图片内容（印章、签名、身份证等）
    
    **注意：使用 PaddleX OCR，适用于所有 PDF，包括扫描图片 PDF**
    """
    import tempfile
    
    suffix = file.filename.split(".")[-1].lower()
    
    # 验证文件类型
    if suffix not in ["pdf", "jpg", "jpeg", "png", "webp"]:
        raise HTTPException(status_code=400, detail="仅支持 PDF/JPG/PNG 文件")
    
    # 读取文件内容
    file_content = await file.read()
    file_size = len(file_content)
    
    # 保存临时文件
    with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name
    
    try:
        # 检查 OCR 服务是否初始化
        if ocr_service.pipeline is None:
            raise RuntimeError("OCR 服务未初始化，请先调用初始化接口")
        
        # 使用 OCR 服务的布局分析 pipeline
        layout_results = ocr_service.recognize_with_layout(tmp_path)
        
        # 格式化结果
        formatted_result = {
            "filename": file.filename,
            "file_size": file_size,
            "method": "paddlex_ocr_with_layout",
            "layoutParsingResults": layout_results,
            "pages_count": len(layout_results)
        }
        
        # 添加便捷访问字段
        if layout_results and "markdown" in layout_results[0]:
            formatted_result["markdown"] = layout_results[0]["markdown"].get("text", "")
            formatted_result["images"] = layout_results[0]["markdown"].get("images", {})
        
        return ApiResponse.success(formatted_result)
        
    except Exception as e:
        return ApiResponse.error(f"OCR 分析失败: {str(e)}")
    finally:
        # 清理临时文件
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass


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
