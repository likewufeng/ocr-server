# Description: 证件类型器 这个文件负责根据图片文字特征，自动告诉程序这是身份证还是营业执照。
from app.utils.layout import Layout

class DocumentDetector:
    def detect(self, layout: Layout) -> str:
        """
        返回证件类型: id_front, id_back, business_license, unknown
        """
        all_text = "".join(layout.texts())
        
        # 1. 身份证判定
        if "姓名" in all_text and "公民身份号码" in all_text:
            return "id_front"
        
        if "签发机关" in all_text and "有效期限" in all_text:
            return "id_back"
        
        # 2. 营业执照判定
        if "营业执照" in all_text or "统一社会信用代码" in all_text:
            return "business_license"
            
        # 3. 补充判定：如果只有信用代码但没印“营业执照”四个字
        if "注册资本" in all_text and "法定代表人" in all_text:
            return "business_license"
            
        return "unknown"