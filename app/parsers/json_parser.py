import json
from app.parsers.base_parser import BaseParser
from app.utils.logger import setup_logger
from app.models import ParsedResult


class JsonParser(BaseParser):
    def __init__(self):
        self.logger = setup_logger(__name__)

    def parse(self, file_path: str) -> ParsedResult:
        """Phân tích file JSON và trích xuất nội dung dạng Markdown."""
        self.logger.info(f"📊 Bắt đầu parsing JSON: {file_path}")

        res = None
        md = ''
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                data = json.load(file)

                # Chuyển JSON sang định dạng Markdown đẹp mắt
                def json_to_md(obj, indent=0):
                    md_lines = []
                    indent_str = '  ' * indent
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            md_lines.append(f"{indent_str}- **{k}**:")
                            md_lines.append(json_to_md(v, indent + 1))
                    elif isinstance(obj, list):
                        for i, item in enumerate(obj):
                            md_lines.append(f"{indent_str}- [{i + 1}]")
                            md_lines.append(json_to_md(item, indent + 1))
                    else:
                        md_lines.append(f"{indent_str}- {obj}")
                    return "\n".join(md_lines)

                md = json_to_md(data)
                res = ParsedResult(is_success=True, content=md)
                self.logger.info(f"🧾 Đã parse thành công JSON ({len(md)} ký tự Markdown).")

        except json.JSONDecodeError as e:
            msg = f"Lỗi cú pháp JSON: {str(e)}"
            self.logger.error(f"❌ {msg}")
            res = ParsedResult(is_success=False, content='', failed_reason=msg)
        except Exception as e:
            msg = f"Lỗi khi đọc file JSON: {str(e)}"
            self.logger.error(f"❌ {msg}")
            res = ParsedResult(is_success=False, content='', failed_reason=msg)

        self.logger.info(f"✅ Hoàn tất parsing JSON: {file_path}")
        return res
