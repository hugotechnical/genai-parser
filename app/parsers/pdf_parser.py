from concurrent.futures import ThreadPoolExecutor, as_completed
import gc
import os
import uuid
import shutil
from pathlib import Path
from typing import Dict
import fitz
from pdf2image import convert_from_path
from PIL import Image
import pytesseract

from app.parsers.base_parser import BaseParser
from app.utils.markdown_utils import to_markdown
from app.config import settings
from app.utils import get_logger
from app.models import ParsedResult
from app.utils.pdf_utils import check_scanned_pdf

TESSERACT_CONFIG_CMD = settings.tesseract_config_cmd
TESSERACT_CONFIG_DPI = settings.tesseract_config_dpi
TESSERACT_CONFIG_THREAD_IMAGE_CONVERT = settings.tesseract_config_thread_image_convert
TESSERACT_CONFIG_MAX_WORKER = settings.tesseract_config_max_worker
TESSERACT_CONFIG_BATCH_SIZE= settings.tesseract_config_batch_size

class PDFParser(BaseParser):
    def __init__(self):
        self.logger = get_logger(__name__)
        pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

    def _extract_text_native(self, file_path: str) -> str:
        """Trích xuất text từ PDF có text layer bằng PyMuPDF (fitz)."""
        try:
            doc = fitz.open(file_path)
            texts = [page.get_text("text") for page in doc]
            self.logger.info(f"🧾 File có {len(doc)} trang (native).")
            return "\n".join(texts)
        except Exception as e:
            self.logger.error(f"❌ Lỗi khi trích xuất PDF native: {e}")
            return ""

    def _ocr_single_image_worker(self, image: Image.Image, index: int) -> tuple:
        """OCR một trang ảnh, trả về (index, text)."""
        try:
            text = pytesseract.image_to_string(
                image,
                lang=settings.ocr_lang,
                config=TESSERACT_CONFIG_CMD
            )
            return index, text.strip()
        except Exception as e:
            self.logger.warning(f"⚠️ Lỗi OCR worker trang {index}: {e}")
            return index, ""
        

    def _extract_text_ocr(self, file_path: str) -> str:
        text_results: Dict[int, str] = {}
        os.environ["OMP_THREAD_LIMIT"] = "1"

        batch_size = TESSERACT_CONFIG_BATCH_SIZE
        tmp_dir = Path(f"/tmp/pdf_scan_tmp/pdf_scan_{uuid.uuid4().hex}")
        tmp_dir.mkdir(parents=True, exist_ok=True)

        ocr_started = False   # <--- FLAG QUAN TRỌNG

        try:
            from pdf2image.pdf2image import pdfinfo_from_path
            pdf_info = pdfinfo_from_path(file_path)
            total_pages = pdf_info["Pages"]
            self.logger.info(f"🖼 PDF có {total_pages} trang. OCR với DPI={TESSERACT_CONFIG_DPI}...")

            # BẮT ĐẦU OCR
            ocr_started = True

            for batch_start in range(0, total_pages, batch_size):
                batch_end = min(batch_start + batch_size, total_pages)

                images = convert_from_path(
                    pdf_path=file_path,
                    dpi=TESSERACT_CONFIG_DPI,
                    fmt="jpeg",
                    first_page=batch_start + 1,
                    last_page=batch_end,
                    thread_count=TESSERACT_CONFIG_THREAD_IMAGE_CONVERT
                )

                batch_images = []
                for i, img in enumerate(images, start=batch_start + 1):
                    img_path = tmp_dir / f"page_{i:04d}.jpeg"
                    img.save(img_path, format="JPEG")
                    batch_images.append((i, img))

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
                            self.logger.info(f"📝 OCR xong trang {page_idx}/{total_pages}")
                        except Exception:
                            text_results[idx] = ""

                for _, img in batch_images:
                    img.close()
                del images
                gc.collect()

            ordered = [text_results.get(i, "") for i in range(1, total_pages + 1)]

            # Chỉ xóa tmp_dir sau khi OCR HOÀN THÀNH 100%
            shutil.rmtree(tmp_dir, ignore_errors=True)

            return "\n\n--- Page Break ---\n\n".join(ordered)

        except Exception as e:
            self.logger.error(f"❌ Lỗi khi OCR PDF: {e}")

            # Chỉ xóa tmp_dir NẾU OCR ĐÃ BẮT ĐẦU
            if ocr_started and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)

            return ""

    def _check_page_limit(self, file_path: str, max_pages: int = 50) -> bool:
        """Kiểm tra xem file PDF có vượt quá giới hạn số trang không."""
        try:
            doc = fitz.open(file_path)
            page_count = len(doc)
            self.logger.info(f"📊 File PDF có {page_count} trang.")
            if page_count > max_pages:
                self.logger.warning(
                    f"⚠️ File PDF vượt quá giới hạn {max_pages} trang (hiện tại: {page_count} trang)."
                )
                return False
            return True
        except Exception as e:
            self.logger.error(f"❌ Lỗi khi kiểm tra số trang PDF ({file_path}): {e}")
        return False

    def parse(self, file_path: str) -> ParsedResult:
        """Hàm chính: phân loại PDF và trích xuất nội dung tương ứng."""
        file_path = str(Path(file_path))
        self.logger.info(f"🔍 Bắt đầu xử lý PDF: {Path(file_path).name}")

        try:
            # Kiểm tra file có phải PDF hợp lệ không
            try:
                with fitz.open(file_path) as doc:
                    if doc.page_count == 0:
                        self.logger.warning(f"⚠️ File PDF rỗng: {file_path}")
                        return ParsedResult(is_success=False, content="", failed_reason=f"File PDF rỗng: {file_path}")
            except Exception as e:
                self.logger.error(f"❌ File không phải PDF hợp lệ: {e}")
                return ParsedResult(is_success=False, content="", failed_reason=f"File không phải PDF hợp lệ: {e}")

            # Kiểm tra giới hạn số trang
            if not self._check_page_limit(file_path, max_pages=settings.max_page_limit):
                return ParsedResult(is_success=False, content="", failed_reason=f"File PDF vượt quá số trang quy định: {settings.max_page_limit} trang.")

            # Phân loại PDF
            is_native = check_scanned_pdf(file_path)
            self.logger.info(f"📑 PDF '{Path(file_path).name}' là {'native' if not is_native else 'scan'}.")

            # Trích xuất nội dung
            if not is_native:
                text = self._extract_text_native(file_path)
            else:
                text = self._extract_text_ocr(file_path)

            if not text.strip():
                self.logger.warning(f"⚠️ File {Path(file_path).name} không trích xuất được nội dung.")
                return ParsedResult(is_success=False, content="", failed_reason=f"File {Path(file_path).name} không trích xuất được nội dung.")

            markdown_text = to_markdown(text.strip())
            self.logger.info(f"✅ Hoàn tất xử lý PDF: {Path(file_path).name}")
            return ParsedResult(is_success=True, content=markdown_text)

        except Exception as e:
            self.logger.critical(f"🔥 Lỗi nghiêm trọng khi xử lý file {file_path}: {e}")
            return ParsedResult(is_success=False, content="", failed_reason="Lỗi nghiêm trọng khi xử lý file")
