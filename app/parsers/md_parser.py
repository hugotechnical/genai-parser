from app.parsers.base_parser import BaseParser
from app.utils import get_logger
from app.models import ParsedResult


class MdParser(BaseParser):
    def __init__(self):
        self.logger = get_logger(__name__)

    def parse(self, file_path: str) -> ParsedResult:
        """Phân tích file Markdown và trích xuất toàn bộ nội dung."""
        self.logger.info(f"📊 Bắt đầu parsing Markdown: {file_path}")

        res = None
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
                res = ParsedResult(is_success=True, content=content)
                self.logger.info(f"📝 Đã đọc {len(content)} ký tự từ file Markdown")
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='latin-1') as file:
                    content = file.read()
                    res = ParsedResult(is_success=True, content=content)
                    self.logger.info(f"📝 Đã đọc {len(content)} ký tự từ file Markdown (latin-1)")
            except Exception as e:
                msg = f"Lỗi khi đọc file Markdown (latin-1): {str(e)}"
                self.logger.error(f"❌ {msg}")
                res = ParsedResult(is_success=False, content='', failed_reason=msg)
        except Exception as e:
            msg = f"Lỗi khi đọc file Markdown: {str(e)}"
            self.logger.error(f"❌ {msg}")
            res = ParsedResult(is_success=False, content='', failed_reason=msg)

        self.logger.info(f"✅ Hoàn tất parsing Markdown: {file_path}")
        return res
