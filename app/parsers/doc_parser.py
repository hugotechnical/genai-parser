import shutil
import subprocess
import tempfile
import os
import uuid
from lxml import etree
import zipfile

from pathlib import Path
from docx import Document
from typing import List, Tuple
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from app.parsers.base_parser import BaseParser
from app.utils.logger import setup_logger
from app.models import ParsedResult


class DocParser(BaseParser):
    def __init__(self):
        self.logger = setup_logger(__name__)

    def _convert_doc_to_docx(self, doc_path: Path) -> Path:
        """Convert file .doc sang .docx bằng LibreOffice (CLI)."""
        temp_dir = tempfile.mkdtemp()
        output_path = Path(temp_dir) / (doc_path.stem + ".docx")
        
        # Tạo thư mục profile riêng
        profile_dir = Path(f"/tmp/lo_profile_{uuid.uuid4().hex}")
        profile_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            self.logger.info(f"🔄 Converting .doc → .docx: {doc_path.name}")
            
            # Kiểm tra file đầu vào
            if not doc_path.exists():
                raise FileNotFoundError(f"File không tồn tại: {doc_path}")
            
            if not os.access(doc_path, os.R_OK):
                raise PermissionError(f"Không có quyền đọc file: {doc_path}")
            
            # Kiểm tra quyền ghi vào thư mục tạm
            if not os.access(temp_dir, os.W_OK):
                raise PermissionError(f"Không có quyền ghi vào thư mục tạm: {temp_dir}")
            
            # Thử chuyển đổi với nhiều tùy chọn khác nhau
            conversion_methods = [
                # Phương pháp 1: Không sử dụng Java
                ["soffice", "--headless", f"-env:UserInstallation=file://{profile_dir}", 
                "--norestore", "--nofirststartwizard", "--nologo", "--convert-to", "docx", 
                "--outdir", temp_dir, str(doc_path)],
                
                # Phương pháp 2: Sử dụng bộ lọc cụ thể
                ["soffice", "--headless", f"-env:UserInstallation=file://{profile_dir}", 
                "--convert-to", "docx:MS Word 2007 XML", "--outdir", temp_dir, str(doc_path)],
                
                # Phương pháp 3: Thử với libreoffice thay vì soffice
                ["libreoffice", "--headless", f"-env:UserInstallation=file://{profile_dir}", 
                "--convert-to", "docx", "--outdir", temp_dir, str(doc_path)]
            ]
            
            success = False
            error_messages = []
            
            for i, cmd in enumerate(conversion_methods):
                try:
                    self.logger.info(f"Đang thử phương pháp chuyển đổi {i+1}/{len(conversion_methods)}")
                    
                    result = subprocess.run(
                        cmd,
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=300
                    )
                    
                    # Kiểm tra kết quả và đảm bảo file tồn tại
                    if result.returncode == 0:
                        # Kiểm tra file có tồn tại không
                        if output_path.exists():
                            success = True
                            self.logger.info(f"✅ Convert thành công: {output_path}")
                            # Đảm bảo file có thể đọc được
                            if not os.access(output_path, os.R_OK):
                                os.chmod(output_path, 0o644)  # Thêm quyền đọc
                            break
                        else:
                            # Tìm kiếm file .docx trong thư mục đầu ra
                            docx_files = list(Path(temp_dir).glob("*.docx"))
                            if docx_files:
                                output_path = docx_files[0]
                                success = True
                                self.logger.info(f"✅ Tìm thấy file chuyển đổi với tên khác: {output_path}")
                                # Đảm bảo file có thể đọc được
                                if not os.access(output_path, os.R_OK):
                                    os.chmod(output_path, 0o644)  # Thêm quyền đọc
                                break
                            else:
                                stderr = result.stderr.decode('utf-8', errors='replace')
                                error_messages.append(f"File không được tạo ra mặc dù quá trình chuyển đổi thành công: {stderr}")
                    else:
                        stderr = result.stderr.decode('utf-8', errors='replace')
                        error_messages.append(stderr)
                        self.logger.warning(f"⚠️ Phương pháp chuyển đổi thất bại: {stderr}")
                except Exception as e:
                    error_messages.append(str(e))
                    self.logger.warning(f"⚠️ Lỗi khi thử phương pháp chuyển đổi: {e}")
            
            # Dọn dẹp thư mục profile tạm
            try:
                shutil.rmtree(profile_dir, ignore_errors=True)
            except Exception as e:
                self.logger.warning(f"⚠️ Không thể xóa thư mục profile tạm: {e}")
            
            if not success:
                # Nếu không thành công với tất cả các phương pháp
                raise FileNotFoundError(f"Không tạo được file .docx sau khi convert. Lỗi: {'; '.join(error_messages)}")
            
            # Kiểm tra lại một lần nữa trước khi trả về
            if not output_path.exists():
                raise FileNotFoundError(f"File .docx không tồn tại sau khi chuyển đổi: {output_path}")
                
            return output_path
        except Exception as e:
            self.logger.error(f"❌ Lỗi khi convert .doc → .docx: {e}")
            raise



    def _process_paragraph(self, para_element, ns) -> str:
        """
        Xử lý một phần tử XML của đoạn văn (<w:p>) và trả về chuỗi văn bản hoàn chỉnh
        có giữ lại định dạng cơ bản (in đậm, in nghiêng, chữ to).
        """
        para_text_parts = []
        
        # Kiểm tra xem đoạn văn có phải là heading không
        p_style = para_element.xpath('./w:pPr/w:pStyle', namespaces=ns)
        is_heading = False
        heading_level = 0
        
        if p_style:
            style_val = p_style[0].get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '')
            if style_val.startswith('Heading'):
                is_heading = True
                try:
                    heading_level = int(style_val.replace('Heading', ''))
                except ValueError:
                    heading_level = 1
        
        nodes = para_element.xpath('.//w:r | .//w:br | .//w:tab', namespaces=ns)
        
        for node in nodes:
            tag = etree.QName(node.tag).localname
            
            if tag == 'r': 
                # Kiểm tra định dạng của run
                run_props = node.xpath('./w:rPr', namespaces=ns)
                is_bold = node.xpath('./w:rPr/w:b', namespaces=ns)
                is_italic = node.xpath('./w:rPr/w:i', namespaces=ns)
                
                # Kiểm tra kích thước font
                sz_elements = node.xpath('./w:rPr/w:sz', namespaces=ns)
                font_size = None
                if sz_elements:
                    font_size_val = sz_elements[0].get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
                    if font_size_val:
                        font_size = int(font_size_val) / 2  # Chuyển đổi từ half-points sang points
                
                text_nodes = node.xpath('.//w:t', namespaces=ns)
                run_text = ''.join(t.text for t in text_nodes if t.text is not None)

                if not run_text:
                    continue

                # Áp dụng định dạng
                formatted_text = run_text
                
                # Áp dụng in đậm nếu có
                if is_bold:
                    formatted_text = f"**{formatted_text}**"
                    
                # Áp dụng in nghiêng nếu có
                if is_italic:
                    formatted_text = f"*{formatted_text}*"
                    
                # Nếu là phần được chèn thêm
                if node.xpath('ancestor::w:ins', namespaces=ns):
                    para_text_parts.append(formatted_text)
                else:
                    para_text_parts.append(formatted_text)

            elif tag == 'br':
                para_text_parts.append('\n')
                
            elif tag == 'tab':
                para_text_parts.append('\t')
        
        result = ''.join(para_text_parts)
        
        # Nếu là heading, thêm dấu # tương ứng
        if is_heading and heading_level > 0:
            result = '#' * heading_level + ' ' + result
        
        return result


    def _process_table(self, table_element, ns) -> str:
        """
        Xử lý một phần tử XML của bảng (<w:tbl>) và chuyển đổi nó thành định dạng Markdown,
        có hỗ trợ xử lý merge cells và vmerge (merge rows).
        """
        table_markdown_lines = []
        rows = table_element.xpath('./w:tr', namespaces=ns)
        
        if not rows:
            return ""
        
        # Xác định số cột thực tế của bảng
        grid_cols = table_element.xpath('./w:tblGrid/w:gridCol', namespaces=ns)
        num_columns = len(grid_cols) if grid_cols else 0
        
        if num_columns == 0:
            # Tính tổng số cột từ tất cả các hàng, lấy hàng có nhiều cột nhất
            for row in rows:
                cells = row.xpath('./w:tc', namespaces=ns)
                row_cols = 0
                for cell in cells:
                    grid_span = cell.xpath('./w:tcPr/w:gridSpan', namespaces=ns)
                    if grid_span:
                        span_val = grid_span[0].get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
                        row_cols += int(span_val) if span_val else 1
                    else:
                        row_cols += 1
                num_columns = max(num_columns, row_cols)
        
        # Theo dõi các ô đã được merge theo chiều dọc
        vmerge_tracking = [None] * num_columns
        
        # Tạo cấu trúc dữ liệu để lưu thông tin về các ô được merge
        table_data = []
        cell_spans = []  # Lưu thông tin về span của các ô
        
        # Phân tích cấu trúc bảng và lưu thông tin về các ô được merge
        for i, row_element in enumerate(rows):
            row_data = [""] * num_columns
            row_spans = [1] * num_columns  # Mặc định mỗi ô chiếm 1 cột
            row_cells = row_element.xpath('./w:tc', namespaces=ns)
            col_index = 0
            
            for cell_element in row_cells:
                # Bỏ qua nếu đã vượt quá số cột
                if col_index >= num_columns:
                    break
                    
                # Kiểm tra xem cột hiện tại có bị ảnh hưởng bởi vmerge từ hàng trước không
                while col_index < num_columns and vmerge_tracking[col_index] is not None:
                    row_data[col_index] = vmerge_tracking[col_index]
                    col_index += 1
                    
                if col_index >= num_columns:
                    break
                
                # Xử lý gridSpan (merge columns)
                grid_span = cell_element.xpath('./w:tcPr/w:gridSpan', namespaces=ns)
                span = 1
                if grid_span:
                    span_val = grid_span[0].get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
                    span = int(span_val) if span_val else 1
                
                # Xử lý vMerge (merge rows)
                vmerge = cell_element.xpath('./w:tcPr/w:vMerge', namespaces=ns)
                is_vmerge_continue = False
                is_vmerge_start = False
                
                if vmerge:
                    vmerge_val = vmerge[0].get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '')
                    is_vmerge_continue = vmerge_val != 'restart'
                    is_vmerge_start = vmerge_val == 'restart'
                
                # Xử lý nội dung cell
                cell_paragraphs = cell_element.xpath('./w:p', namespaces=ns)
                cell_text_parts = [self._process_paragraph(p, ns) for p in cell_paragraphs]
                cell_text = '\n'.join(cell_text_parts).strip()
                
                # Nếu là vmerge continue, sử dụng nội dung từ hàng trước
                if is_vmerge_continue:
                    if col_index < len(vmerge_tracking) and vmerge_tracking[col_index] is not None:
                        cell_text = vmerge_tracking[col_index]
                
                # Lưu nội dung cell vào cấu trúc dữ liệu
                for j in range(col_index, min(col_index + span, num_columns)):
                    row_data[j] = cell_text
                    row_spans[j] = span if j == col_index else 0  # Đánh dấu các ô được merge
                
                # Cập nhật vmerge tracking
                if is_vmerge_start or (vmerge and not is_vmerge_continue):
                    for j in range(col_index, min(col_index + span, num_columns)):
                        vmerge_tracking[j] = cell_text
                elif not vmerge:
                    for j in range(col_index, min(col_index + span, num_columns)):
                        vmerge_tracking[j] = None
                
                col_index += span
            
            table_data.append(row_data)
            cell_spans.append(row_spans)
        
        # Tạo bảng Markdown từ cấu trúc dữ liệu đã phân tích
        for i, row_data in enumerate(table_data):
            # Xử lý các ô được merge theo chiều ngang
            row_text = []
            for j, cell_text in enumerate(row_data):
                span = cell_spans[i][j]
                if span > 0:  # Chỉ thêm các ô không bị merge (hoặc là ô đầu tiên của một nhóm merge)
                    # Xử lý ký tự đặc biệt trong Markdown
                    escaped_text = cell_text.replace('|', '\\|').replace('\n', '<br>')
                    row_text.append(escaped_text)
            
            # Thêm dòng vào bảng Markdown
            table_markdown_lines.append("| " + " | ".join(row_text) + " |")
            
            # Thêm dòng phân cách sau hàng đầu tiên
            if i == 0:
                separator = "| " + " | ".join(["---"] * len(row_text)) + " |"
                table_markdown_lines.append(separator)
        
        # Thêm khoảng trống trước và sau bảng để đảm bảo định dạng Markdown đúng
        return "\n" + "\n".join(table_markdown_lines) + "\n"


    def _parse_docx(self, file_path: Path) -> Tuple[List[str], int]:
        """
        Phân tích tài liệu DOCX và trả về danh sách các đoạn văn và vị trí của TOC.
        """
        try:
            markdown_content = []
            toc_position = -1
            toc_found = False
            
            with zipfile.ZipFile(file_path, 'r') as docx_zip:
                xml_content = docx_zip.read('word/document.xml')
                root = etree.fromstring(xml_content)
                ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                
                body = root.find('w:body', ns)
                if body is None:
                    return markdown_content, toc_position

                for i, element in enumerate(body.iterchildren()):
                    tag = etree.QName(element.tag).localname
                    
                    # Kiểm tra xem đây có phải là TOC không
                    if tag == 'p':
                        processed_text = self._process_paragraph(element, ns)
                        
                        # Kiểm tra xem đoạn văn này có phải là tiêu đề TOC không
                        if not toc_found and self._is_toc_heading(element, ns, processed_text):
                            toc_position = len(markdown_content)
                            toc_found = True
                            
                        markdown_content.append(processed_text)
                    elif tag == 'tbl':
                        processed_table = self._process_table(element, ns)
                        markdown_content.append(f"\n{processed_table}\n")
                    elif tag == 'sdt':
                        # Kiểm tra xem đây có phải là TOC không
                        sdt_pr = element.find('.//w:sdtPr', ns)
                        if sdt_pr is not None:
                            tag_elem = sdt_pr.find('.//w:tag', ns)
                            if tag_elem is not None and 'TOC' in tag_elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', ''):
                                toc_position = len(markdown_content)
                                toc_found = True
                                
                                # Xử lý nội dung bên trong TOC
                                content_elem = element.find('.//w:sdtContent', ns)
                                if content_elem is not None:
                                    for child in content_elem.iterchildren():
                                        child_tag = etree.QName(child.tag).localname
                                        if child_tag == 'p':
                                            processed_text = self._process_paragraph(child, ns)
                                            markdown_content.append(processed_text)
                                        elif child_tag == 'tbl':
                                            processed_table = self._process_table(child, ns)
                                            markdown_content.append(f"\n{processed_table}\n")
 
            return markdown_content, toc_position
        
        except KeyError:
            self.logger.warning(f"⚠️ Không tìm thấy 'word/document.xml' trong tệp: {file_path}")
            return [], -1
        except Exception as e:
            self.logger.error(f"⚠️ Đã xảy ra lỗi khi trích xuất tệp Word '{file_path}': {e}")
            return [], -1

    def _is_toc_heading(self, para_element, ns, text: str) -> bool:
        """Kiểm tra xem đoạn văn có phải là tiêu đề TOC không."""
        # Kiểm tra style
        style = para_element.find('.//w:pStyle', ns)
        if style is not None:
            style_val = style.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '')
            if 'TOCHeading' in style_val:
                return True
        
        # Kiểm tra nội dung
        toc_keywords = ["mục lục", "table of contents", "nội dung", "contents"]
        text_lower = text.lower().strip()
        return any(keyword in text_lower for keyword in toc_keywords)

    def extract_toc(self, file_path: Path) -> List[dict]:
        """Trích xuất mục lục (Table of Contents) từ tài liệu Word."""
        try:
            self.logger.info(f"📑 Đang trích xuất mục lục từ: {file_path.name}")
            toc_entries = []
            
            # Đảm bảo file là .docx
            docx_path = file_path
            if file_path.suffix.lower() == '.doc':
                docx_path = self._convert_doc_to_docx(file_path)
            
            # Mở file docx như một zip archive
            with ZipFile(docx_path, 'r') as docx_zip:
                # Đọc document.xml
                doc_xml = docx_zip.read('word/document.xml')
                
                # Parse XML
                root = ET.fromstring(doc_xml)
                
                # Namespace cho Word XML
                ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                
                # Tìm tất cả các trường TOC
                sdt_elements = root.findall('.//w:sdt', ns)
                
                for sdt in sdt_elements:
                    # Kiểm tra xem đây có phải là TOC không
                    sdt_pr = sdt.find('.//w:sdtPr', ns)
                    if sdt_pr is not None:
                        tag = sdt_pr.find('.//w:tag', ns)
                        if tag is not None and 'TOC' in tag.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', ''):
                            # Đây là TOC, trích xuất các mục
                            paragraphs = sdt.findall('.//w:p', ns)
                            
                            for p in paragraphs:
                                # Bỏ qua tiêu đề TOC
                                if p.find('.//w:pStyle[@w:val="TOCHeading"]', ns) is not None:
                                    continue
                                    
                                # Xác định cấp độ của mục TOC
                                style = p.find('.//w:pStyle', ns)
                                level = 1  # Mặc định là cấp độ 1
                                
                                if style is not None:
                                    style_val = style.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '')
                                    if 'TOC' in style_val:
                                        try:
                                            level_str = ''.join(filter(str.isdigit, style_val))
                                            if level_str:
                                                level = int(level_str)
                                        except ValueError:
                                            pass
                                
                                # Lấy nội dung văn bản
                                text_elements = p.findall('.//w:t', ns)
                                text = ''.join(t.text for t in text_elements if t.text)
                                
                                if text.strip():
                                    toc_entries.append({
                                        'level': level,
                                        'text': text.strip(),
                                    })
                
                # Nếu không tìm thấy TOC thông qua sdt, thử phương pháp khác
                if not toc_entries:
                    # Tìm các đoạn văn có style TOC
                    paragraphs = root.findall('.//w:p', ns)
                    
                    for p in paragraphs:
                        style = p.find('.//w:pStyle', ns)
                        if style is not None:
                            style_val = style.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '')
                            if 'TOC' in style_val:
                                # Xác định cấp độ
                                level = 1
                                try:
                                    level_str = ''.join(filter(str.isdigit, style_val))
                                    if level_str:
                                        level = int(level_str)
                                except ValueError:
                                    pass
                                    
                                # Lấy nội dung văn bản
                                text_elements = p.findall('.//w:t', ns)
                                text = ''.join(t.text for t in text_elements if t.text)
                                
                                if text.strip():
                                    toc_entries.append({
                                        'level': level,
                                        'text': text.strip(),
                                    })
            
            # Nếu vẫn không tìm thấy TOC, thử phương pháp cuối cùng: tìm các heading
            if not toc_entries:
                self.logger.info("Không tìm thấy TOC, đang trích xuất từ các heading...")
                doc = Document(docx_path)
                
                for para in doc.paragraphs:
                    if para.style and para.style.name.startswith('Heading'):
                        try:
                            level_str = ''.join(filter(str.isdigit, para.style.name))
                            level = int(level_str) if level_str else 1
                        except ValueError:
                            level = 1
                            
                        if para.text.strip():
                            toc_entries.append({
                                'level': level,
                                'text': para.text.strip(),
                            })
            
            # Nếu file là .doc, xóa file tạm sau khi xử lý xong
            if file_path.suffix.lower() == '.doc' and docx_path != file_path:
                try:
                    os.remove(docx_path)
                    os.rmdir(docx_path.parent)
                except Exception:
                    pass
            
            self.logger.info(f"✅ Đã trích xuất {len(toc_entries)} mục trong TOC")
            return toc_entries
            
        except Exception as e:
            self.logger.error(f"❌ Lỗi khi trích xuất TOC: {e}")
            return []

    def toc_to_markdown(self, toc_entries: List[dict]) -> str:
        """Chuyển đổi TOC thành định dạng Markdown."""
        if not toc_entries:
            return ""
            
        markdown_lines = ["## Mục lục\n"]
        
        for entry in toc_entries:
            indent = "  " * (entry['level'] - 1)
            markdown_lines.append(f"{indent}- {entry['text']}")
        
        return "\n".join(markdown_lines)

    def parse(self, file_path: str) -> ParsedResult:
        """Parse tài liệu Word và giữ TOC ở đúng vị trí của nó."""
        file_path = Path(file_path)
        ext = file_path.suffix.lower()
        self.logger.info(f"📄 Đang xử lý file Word: {file_path.name}")

        try:
            docx_path = file_path
            if ext == ".doc":
                docx_path = self._convert_doc_to_docx(file_path)
            elif ext != ".docx":
                self.logger.warning(f"⚠️ Định dạng không hỗ trợ: {ext}")
                return ParsedResult(is_success=False, content="", failed_reason=f"Định dạng không hỗ trợ: {ext}")
            
            # Phân tích tài liệu và xác định vị trí TOC
            markdown_paragraphs, toc_position = self._parse_docx(docx_path)
            # Trích xuất TOC
            toc_entries = self.extract_toc(docx_path)
            toc_markdown = self.toc_to_markdown(toc_entries)
            
            # Nếu tìm thấy vị trí TOC, chèn TOC vào đúng vị trí đó
            if toc_position >= 0 and toc_markdown:
                # Xóa các đoạn văn TOC gốc (thường là 1 đoạn tiêu đề)
                markdown_paragraphs[toc_position] = toc_markdown
            elif toc_markdown:  # Nếu không tìm thấy vị trí TOC nhưng có TOC
                # Thêm TOC vào đầu tài liệu
                markdown_paragraphs.insert(0, toc_markdown)
            
            # Xóa file tạm nếu là .doc
            if ext == ".doc" and docx_path != file_path:
                try:
                    os.remove(docx_path)
                    os.rmdir(docx_path.parent)
                    self.logger.debug(f"🧹 Đã xoá file tạm {docx_path}")
                except Exception as cleanup_err:
                    self.logger.warning(f"⚠️ Không xoá được file tạm: {cleanup_err}")
            
            return ParsedResult(is_success=True, content="\n\n".join(markdown_paragraphs))

        except Exception as e:
            self.logger.critical(f"🔥 Lỗi nghiêm trọng khi xử lý {file_path.name}: {e}")
            return ParsedResult(is_success=False, content="", failed_reason="Lỗi khi xử lý file")
