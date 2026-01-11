from app.parsers.base_parser import BaseParser
from app.utils.logger import setup_logger
from app.models import ParsedResult

class TxtParser(BaseParser):
    def __init__(self):
        self.logger = setup_logger(__name__)


    def parse(self, file_path: str) -> ParsedResult:
        """Phân tích file txt và trích xuất toàn bộ nội dung dạng Markdown."""
        self.logger.info(f"📊 Bắt đầu parsing TXT: {file_path}")

        res = None
        md = ''
        try:
            # Mở file txt với encoding utf-8
            with open(file_path, 'r', encoding='utf-8') as file:
                # Đọc toàn bộ nội dung file
                content = file.read()
                
                # Chuyển đổi nội dung thành định dạng markdown
                # Trong trường hợp file txt, nội dung đã ở dạng văn bản thuần túy
                # nên chỉ cần gán trực tiếp
                res = ParsedResult(is_success=True, content=content)
                self.logger.info(f"📝 Đã đọc {len(content)} ký tự từ file TXT")
        except UnicodeDecodeError:
            # Thử lại với encoding khác nếu utf-8 không hoạt động
            try:
                with open(file_path, 'r', encoding='latin-1') as file:
                    content = file.read()
                    md = content
                    self.logger.info(f"📝 Đã đọc {len(content)} ký tự từ file TXT (encoding: latin-1)")
            except Exception as e:
                self.logger.error(f"❌ Lỗi khi đọc file với encoding latin-1: {str(e)}")
                md = f"Lỗi khi đọc file: {str(e)}"
                res = ParsedResult(is_success=False, content=md, failed_reason=md)
        except Exception as e:
            self.logger.error(f"❌ Lỗi khi parsing TXT: {str(e)}")
            md = f"Lỗi khi đọc file: {str(e)}"
            res = ParsedResult(is_success=False, content=md, failed_reason=md)

        self.logger.info(f"✅ Hoàn tất parsing TXT: {file_path}")
        return res
