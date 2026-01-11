import gc
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Tuple

import fitz  # PyMuPDF
import pymupdf4llm
import pytesseract
from PIL import Image, ImageEnhance, ImageOps, ImageFilter  # Added ImageFilter

from app.config import settings
from app.models import ParsedResult
from app.parsers.base_parser import BaseParser
from app.utils import get_logger

# =========================
# CONFIG CONSTANTS
# =========================
# --oem 3: Default engine
# --psm 3: Auto segmentation (Tốt cho bảng có Header)
# preserve_interword_spaces=1: Giữ khoảng cách cột
# tessedit_char_whitelist: KHÔNG NÊN DÙNG nếu file có cả Tiếng Việt và Số hỗn hợp
TESSERACT_CONFIG_CMD = r'--oem 3 --psm 3 -c preserve_interword_spaces=1'

TESSERACT_CONFIG_MAX_WORKER = settings.tesseract_config_max_worker
TESSERACT_CONFIG_BATCH_SIZE = settings.tesseract_config_batch_size
PAGE_BREAK_STR = settings.page_break_str


class PDFParser(BaseParser):
    def __init__(self):
        self.logger = get_logger(__name__)
        if os.path.exists("/usr/bin/tesseract"):
            pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

    # =====================================================
    # NATIVE PDF (TEXT-BASED)
    # =====================================================
    def _extract_text_native(self, file_path: str) -> str:
        try:
            self.logger.info(f"🚀 Converting native PDF: {Path(file_path).name}")
            md_pages = pymupdf4llm.to_markdown(
                file_path,
                page_chunks=True,
                write_images=False
            )
            pages_text = [page.get("text", "") for page in md_pages]
            return f"\n\n{PAGE_BREAK_STR}\n\n".join(pages_text)
        except Exception as e:
            self.logger.error(f"❌ Native extraction failed: {e}")
            return ""

    # =====================================================
    # IMAGE ENHANCEMENT (FIX LỖI 8 -> 0 & Binarization)
    # =====================================================
    # Thay thế hàm _enhance_image trong code của bạn bằng hàm này
    def _enhance_image(self, img: Image.Image) -> Image.Image:
        """
        Chiến thuật 'Thickening': 
        Thay vì tăng tương phản (làm mất chữ nhạt), ta làm chữ đậm lên.
        """
        try:
            # 1. Convert Grayscale
            img = img.convert('L')

            # 2. PADDING (Bắt buộc)
            img = ImageOps.expand(img, border=30, fill=255)

            # 3. LÀM ĐẬM CHỮ (KEY FIX)
            # MinFilter(3) trong ảnh nền trắng chữ đen sẽ lấy điểm đen nhất trong ô 3x3
            # -> Tác dụng: Làm nét chữ dày thêm 1 pixel xung quanh.
            # Giúp số 8 không bị đứt nét, số tài khoản mờ hiện rõ hơn.
            
            img = img.filter(ImageFilter.MinFilter(1))
            
            enhancer_sharp = ImageEnhance.Sharpness(img)
            img = enhancer_sharp.enhance(2.0)

            # 4. Tăng tương phản nhẹ (Rất nhẹ thôi)
            # Chỉ để nền trắng hơn chút, không được quá cao (>1.5) gây mất nét
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.2)

            return img
        except Exception as e:
            self.logger.warning(f"⚠️ Image enhancement failed: {e}")
            return img
         
    # =====================================================
    # OCR WORKER
    # =====================================================
    def _ocr_single_image_worker(self, image: Image.Image, index: int) -> Tuple[int, str]:
        try:
            # Xử lý ảnh trước khi đưa vào Tesseract
            processed_img = self._enhance_image(image)

            # Debug: Có thể lưu ảnh ra disk để kiểm tra xem ảnh sau xử lý trông thế nào
            # processed_img.save(f"debug_page_{index}.png")

            text = pytesseract.image_to_string(
                processed_img,
                lang=settings.ocr_lang, # Đảm bảo lang bao gồm 'vie' hoặc 'eng'
                config=TESSERACT_CONFIG_CMD
            )
            return index, text.strip()
        except Exception as e:
            self.logger.warning(f"⚠️ OCR error at page {index}: {e}")
            return index, ""

    # =====================================================
    # OCR PDF (SCANNED PDF)
    # =====================================================
    def _extract_text_ocr(self, file_path: str) -> str:
        text_results: Dict[int, str] = {}
        os.environ["OMP_THREAD_LIMIT"] = "1"

        # Zoom 2.0 hoặc 2.2 là tối ưu nhất.
        # 2.8 gây nhiễu hạt (noise) dẫn đến File 1 bị lỗi.
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)

        try:
            doc = fitz.open(file_path)
            total_pages = doc.page_count

            self.logger.info(
                f"🖼 OCR PDF Processing: {total_pages} pages (Zoom={zoom}, Mode=Binary Threshold)"
            )

            batch_size = TESSERACT_CONFIG_BATCH_SIZE

            for batch_start in range(0, total_pages, batch_size):
                batch_end = min(batch_start + batch_size, total_pages)
                batch_images = []

                for i in range(batch_start, batch_end):
                    page = doc.load_page(i)

                    # Lấy pixmap, KHÔNG dùng alpha (trong suốt), dùng Grayscale để nhẹ
                    pix = page.get_pixmap(matrix=mat, alpha=False, colorspace=fitz.csGRAY)
                    
                    # Convert bytes sang PIL Image
                    img = Image.frombytes("L", [pix.width, pix.height], pix.samples)

                    batch_images.append((i + 1, img))

                with ThreadPoolExecutor(max_workers=TESSERACT_CONFIG_MAX_WORKER) as executor:
                    futures = {
                        executor.submit(self._ocr_single_image_worker, img, idx): idx
                        for idx, img in batch_images
                    }

                    for future in as_completed(futures):
                        idx = futures[future]
                        try:
                            page_idx, text = future.result()
                            text_results[page_idx] = text
                        except Exception:
                            text_results[idx] = ""

                # Giải phóng bộ nhớ
                for _, img in batch_images:
                    img.close()
                del batch_images
                gc.collect()

            doc.close()

            ordered_text = [text_results.get(i, "") for i in range(1, total_pages + 1)]
            return f"\n\n{PAGE_BREAK_STR}\n\n".join(ordered_text)

        except Exception as e:
            self.logger.error(f"❌ OCR processing failed: {e}")
            return ""

    # ... (Các phần check_page_limit và parse giữ nguyên)
    def _check_page_limit(self, file_path: str, max_pages: int) -> bool:
        try:
            with fitz.open(file_path) as doc:
                return doc.page_count <= max_pages
        except Exception:
            return False

    def parse(self, file_path: str, config: dict) -> ParsedResult:
        file_path = str(Path(file_path))
        file_name = Path(file_path).name

        try:
            with fitz.open(file_path) as doc:
                if doc.page_count == 0:
                    raise ValueError("PDF has 0 pages")

            if not self._check_page_limit(file_path, settings.max_page_limit):
                return ParsedResult(
                    is_success=False,
                    content="",
                    failed_reason=f"Page limit exceeded (> {settings.max_page_limit})"
                )

            is_scan = config.get("is_pdf_scan", False)

            if is_scan:
                content = self._extract_text_ocr(file_path)
            else:
                content = self._extract_text_native(file_path)

            if not content.strip():
                return ParsedResult(
                    is_success=False,
                    content="",
                    failed_reason="No content extracted"
                )

            return ParsedResult(
                is_success=True,
                content=content.strip()
            )

        except Exception as e:
            self.logger.critical(f"🔥 Fatal error parsing {file_name}: {e}")
            return ParsedResult(
                is_success=False,
                content="",
                failed_reason=f"System error: {str(e)}"
            )