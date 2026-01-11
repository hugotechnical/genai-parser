import os
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Tuple

from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.services.parser_factory import ParserFactory
from app.services.file_service import save_upload_to_temp
from app.models import FileResponse
from app.config import settings
from app.utils import get_logger
from app.utils.pdf_utils import decide_should_ocr_file


router = APIRouter()
logger = get_logger(__name__)

# --- CONFIGURATION ---

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

HEAVY_EXTENSIONS = settings.heavy_extensions or {'pdf'}

# Cấu hình giới hạn Semaphore
LIMIT_HEAVY = settings.max_concurrent_parser_heavy or 2  
LIMIT_LIGHT = settings.max_concurrent_parser_light or 10 

MAX_FILE_SIZE = settings.max_file_size * 1024 * 1024
PARSE_TIMEOUT = settings.timeout or 300 

sem_heavy = asyncio.Semaphore(LIMIT_HEAVY)
sem_light = asyncio.Semaphore(LIMIT_LIGHT)

executor = ThreadPoolExecutor(max_workers=LIMIT_HEAVY + LIMIT_LIGHT + 4)


@router.get("/", summary="Health Check")
@limiter.limit(settings.rate_limit)
def health_check(request: Request):
    return {"status": "ok"}


@router.post("/sdlc/convert-document", response_model=FileResponse)
@limiter.limit(settings.rate_limit)
async def upload_file(request: Request, file: UploadFile = File(...)):
    temp_path = None
    file_id = None
    config = dict()
    start_time = time.time()
    try:
        logger.info("📤 Đã nhận file upload: filename=%s content_type=%s", file.filename, file.content_type)

        # 1. Đọc nội dung file
        content = await file.read()
        file_size = len(content)

        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"Kích thước file vượt quá giới hạn {MAX_FILE_SIZE / (1024*1024):.2f}MB"
            )

        # 2. Lưu file tạm
        file_id, temp_path = await save_upload_to_temp(file.filename, content)
        logger.debug("🗂️ File tạm lưu tại: %s", temp_path)

        # 3. Xác định loại file và chọn Semaphore phù hợp
        file_ext = file.filename.split(".")[-1].lower() if "." in file.filename else ""
        
        parser = ParserFactory.get_parser(file_ext)
        if parser is None:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_ext}")

        # Logic chọn lane (Phân luồng)
        if file_ext in HEAVY_EXTENSIONS:
            if file_ext == "pdf":
                is_scan = decide_should_ocr_file(temp_path)["should_ocr_file"]
                if is_scan:
                    target_semaphore = sem_heavy
                    lane_name = "HEAVY (OCR/PDF)"
                    config["is_pdf_scan"] = True
                else:
                    target_semaphore = sem_light
                    lane_name = "LIGHT (Text/Doc/PDF native)"
                    config["is_pdf_scan"] = False
        else:
            target_semaphore = sem_light
            lane_name = "LIGHT (Text/Doc/PDF native)"
            config["is_pdf_scan"] = False

        # 4. Fail-fast: Nếu lane đang quá tải, reject ngay để client không chờ
        if target_semaphore.locked():
            logger.warning("⚠️ %s Lane quá tải (%s request), từ chối: %s", 
                           lane_name, 
                           LIMIT_HEAVY if lane_name.startswith("HEAVY") else LIMIT_LIGHT,
                           file.filename)
            # Trả về 429 để client biết server bận, có thể retry sau
            raise HTTPException(status_code=429, detail=f"Server đang bận xử lý nhiều file {lane_name}, vui lòng thử lại sau.")

        loop = asyncio.get_running_loop()
        
        # 5. Xử lý Parse
        try:
            async with target_semaphore:
                logger.info("🚀 Bắt đầu parse (%s): %s", lane_name, file.filename)
                
                # Chạy blocking code trong ThreadPoolExecutor
                # Dùng asyncio.wait_for để set timeout cứng, tránh treo vĩnh viễn
                parsed_result = await asyncio.wait_for(
                    loop.run_in_executor(executor, lambda: parser.parse(temp_path, config)),
                    timeout=PARSE_TIMEOUT
                )
                
        except asyncio.TimeoutError:
            logger.error("⏰ Parse timeout (%ss): %s", PARSE_TIMEOUT, file.filename)
            raise HTTPException(status_code=408, detail="File xử lý quá lâu (Timeout), vui lòng kiểm tra lại file.")

        if not parsed_result.is_success:
            raise HTTPException(status_code=400, detail=parsed_result.failed_reason)

        elapsed_time = time.time() - start_time
        logger.info(f"✅ {elapsed_time}s Parsed thành công: id={file_id} ext={file_ext} lane={lane_name}")

        return FileResponse(
            id=file_id,
            file_name=file.filename,
            file_size=file_size,
            file_type=file.content_type,
            extracted_content=parsed_result.content
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("❌ Failed to process upload: filename=%s error=%s", file.filename, str(e))
        raise HTTPException(status_code=500, detail=f"Lỗi khi xử lý file: {str(e)}")
    finally:
        # 6. Cleanup
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.debug("🧹 Đã xoá file tạm: %s", temp_path)
            except Exception as cleanup_err:
                logger.warning("⚠️ Không thể xoá file tạm %s: %s", temp_path, cleanup_err)