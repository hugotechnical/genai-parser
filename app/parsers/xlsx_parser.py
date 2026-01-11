import pandas as pd
import re
import numpy as np
from pathlib import Path
from app.parsers.base_parser import BaseParser
from app.utils.logger import setup_logger
from app.utils.markdown_utils import to_markdown
from app.models import ParsedResult


class XLSXParser(BaseParser):
    def __init__(self):
        self.logger = setup_logger(__name__)

    def _parse_sheet(self, xls: pd.ExcelFile, sheet_name: str) -> str:
        """Đọc và chuyển 1 sheet thành markdown với xử lý tối ưu khoảng trắng."""
        try:
            self.logger.debug(f"📄 Đang đọc sheet: {sheet_name}")
            
            # Đọc sheet với các tùy chọn để xử lý NaN
            df = xls.parse(
                sheet_name,
                keep_default_na=False,  # Không chuyển đổi các giá trị rỗng thành NaN
                na_values=['#N/A', '#N/A N/A', '#NA', '-NaN', 'NaN', 'null']  # Chỉ coi các giá trị này là NaN
            )

            if df.empty:
                self.logger.debug(f"⚪ Sheet '{sheet_name}' trống.")
                return f"## Sheet: {sheet_name}\n*(Sheet trống)*"

            # Bước 1: Xác định các cột có giá trị
            # Đếm số lượng giá trị không rỗng trong mỗi cột
            non_empty_counts = df.astype(str).replace('', np.nan).count()
            
            # Lọc các cột có ít nhất một giá trị không rỗng
            cols_to_keep = non_empty_counts[non_empty_counts > 0].index.tolist()
            
            # Nếu không còn cột nào sau khi lọc
            if not cols_to_keep:
                return f"## Sheet: {sheet_name}\n*(Sheet không có dữ liệu)*"
            
            # Chỉ giữ lại các cột có giá trị
            df = df[cols_to_keep]
            
            # Bước 2: Đổi tên các cột không có tên hoặc tên tự động
            rename_dict = {}
            for col in df.columns:
                col_str = str(col)
                if col_str.startswith('Unnamed:') or col_str.startswith('.'):
                    # Đặt tên cột trống thay vì "Unnamed: X" hoặc ".X"
                    rename_dict[col] = ""
            
            if rename_dict:
                df = df.rename(columns=rename_dict)
            
            # Bước 3: Xử lý các giá trị rỗng và NaN
            df = df.fillna("")  # Thay thế NaN bằng chuỗi rỗng
            
            # Bước 4: Loại bỏ các hàng hoàn toàn trống
            # Chuyển tất cả các giá trị thành chuỗi và kiểm tra xem hàng có rỗng không
            df = df[df.astype(str).replace('', np.nan).notnull().any(axis=1)]
            
            # Nếu không còn hàng nào sau khi lọc
            if df.empty:
                return f"## Sheet: {sheet_name}\n*(Sheet không có dữ liệu sau khi lọc hàng trống)*"
            
            # Bước 5: Tối ưu hiển thị bảng Markdown
            # Chuyển đổi sang markdown với các tùy chọn để làm sạch
            md_table = df.to_markdown(index=False)
            
            # Bước 6: Xử lý thêm kết quả Markdown để loại bỏ khoảng trắng dư thừa
            # Thay thế nhiều khoảng trắng liên tiếp bằng một khoảng trắng
            md_table = re.sub(r' {2,}', ' ', md_table)
            
            self.logger.debug(f"✅ Đọc xong sheet '{sheet_name}' ({df.shape[0]} hàng × {df.shape[1]} cột).")
            return f"## Sheet: {sheet_name}\n\n{md_table}\n"
            
        except Exception as e:
            self.logger.warning(f"⚠️ Lỗi khi đọc sheet '{sheet_name}': {e}")
            return f"## Sheet: {sheet_name}\n*(Không thể đọc nội dung do lỗi: {str(e)})*"

    def _optimize_markdown_table(self, md_table: str) -> str:
        """Tối ưu hóa bảng Markdown để giảm khoảng trắng dư thừa."""
        # Tách bảng thành các dòng
        lines = md_table.split('\n')
        if len(lines) < 3:  # Bảng Markdown cần ít nhất 3 dòng (header, separator, data)
            return md_table
        
        # Xử lý từng dòng để loại bỏ khoảng trắng dư thừa
        processed_lines = []
        for line in lines:
            # Giữ nguyên dòng phân cách (dòng có dấu |:-----|)
            if re.match(r'\|[\s:]*-+[\s:]*\|', line):
                processed_lines.append(line)
                continue
            
            # Xử lý các dòng dữ liệu
            cells = line.split('|')
            processed_cells = []
            
            for cell in cells:
                # Nếu cell chỉ chứa khoảng trắng, thay thế bằng chuỗi rỗng
                if cell.strip() == '':
                    processed_cells.append('')
                else:
                    # Loại bỏ khoảng trắng đầu/cuối và thay thế nhiều khoảng trắng liên tiếp
                    processed_cells.append(cell.strip())
            
            processed_lines.append('|'.join(processed_cells))
        
        return '\n'.join(processed_lines)

    def parse(self, file_path: str) -> ParsedResult:
        """Phân tích file Excel và chuyển toàn bộ nội dung sang Markdown."""
        file_path = Path(file_path)
        self.logger.info(f"📊 Bắt đầu parsing Excel: {file_path.name}")

        try:
            # Thêm xử lý kiểm tra file tồn tại
            if not file_path.exists():
                self.logger.error(f"❌ File không tồn tại: {file_path}")
                return ParsedResult(is_success=False, content="", error="File không tồn tại")
                
            # Thêm xử lý kiểm tra kích thước file
            file_size = file_path.stat().st_size
            if file_size == 0:
                self.logger.error(f"❌ File rỗng: {file_path}")
                return ParsedResult(is_success=False, content="", error="File rỗng")
                
            # Đọc file Excel
            xls = pd.ExcelFile(file_path)
            sheet_names = xls.sheet_names
            self.logger.info(f"📑 File '{file_path.name}' có {len(sheet_names)} sheet: {', '.join(sheet_names)}")

            md_parts = []
            for sheet in sheet_names:
                md_content = self._parse_sheet(xls, sheet)
                # Tối ưu hóa bảng Markdown
                if "*(Sheet" not in md_content:  # Chỉ tối ưu nếu không phải thông báo lỗi
                    sheet_header = md_content.split('\n\n')[0]
                    table_content = '\n\n'.join(md_content.split('\n\n')[1:])
                    optimized_table = self._optimize_markdown_table(table_content)
                    md_content = f"{sheet_header}\n\n{optimized_table}"
                md_parts.append(md_content)

            result = "\n\n--- Sheet Break ---\n\n".join(md_parts)
            markdown_text = to_markdown(result.strip())

            self.logger.info(f"✅ Hoàn tất parsing Excel: {file_path.name}")
            return ParsedResult(is_success=True, content=markdown_text)

        except Exception as e:
            self.logger.critical(f"🔥 Lỗi nghiêm trọng khi xử lý Excel '{file_path.name}': {e}")
            return ParsedResult(is_success=False, content="", error=str(e))
