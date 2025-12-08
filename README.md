Mini File Parser — Đặc tả API & Kiến trúc
1. Mục tiêu & Phạm vi
Cung cấp REST API nhận file tải lên (PDF native/scan, DOC/DOCX, PPTX, XLSX, TXT, JSON, Markdown) và trả về nội dung đã chuẩn hóa dạng Markdown cùng metadata file.
Đảm bảo luồng xử lý ổn định với rate limiting, timeout, giới hạn kích thước và số trang (PDF).
Hỗ trợ mở rộng parser theo mô hình Factory Pattern và hạ tầng log, cấu hình linh hoạt qua biến môi trường.
2. Tác nhân & Use Case chính
Tác nhân	Nhu cầu chính	Ghi chú
Client nội bộ (Portal, Workflow)	Upload file để chuẩn hóa nội dung	Gọi POST /sdlc/convert-document
Hệ thống giám sát	Kiểm tra sức khỏe dịch vụ	Gọi GET /
DevOps/SRE	Theo dõi log, scale hệ thống	Sử dụng logging JSON, metrics bổ sung
3. Kiến trúc tổng thể
Nền tảng FastAPI nhiều tầng: - API Layer: app/api/endpoints.py xử lý HTTP, rate limit, timeout middleware. - Service Layer: app/services gồm file_service (lưu file tạm), parser_factory (chọn parser theo đuôi file). - Domain Layer: app/parsers triển khai từng parser kế thừa BaseParser. - Infrastructure Layer: cấu hình (app/config.py), logging (app/utils), middleware, thư viện OCR.

graph LR
    Client -->|HTTP| APIGateway[FastAPI Router]
    APIGateway --> Middleware[Timeout & SlowAPI]
    Middleware --> FileSvc[FileService]
    Middleware --> ParserFactory
    ParserFactory --> PDFParser
    ParserFactory --> DocParser
    ParserFactory --> PPTParser
    ParserFactory --> XLSXParser
    ParserFactory --> TxtParser
    ParserFactory --> JsonParser
    ParserFactory --> MdParser
    FileSvc --> TempStorage
    Parsers --> MarkdownUtils
    APIGateway --> ResponseModel[FileResponse]
4. Luồng xử lý chi tiết
4.1 Flowchart (Upload → Markdown)
flowchart TD
    A[Nhận request POST /sdlc/convert-document] --> B[Limiter check theo IP]
    B -->|Pass| C[Đọc nội dung UploadFile]
    C --> D{Kích thước > MAX\_FILE\_SIZE?}
    D -->|Có| E[HTTP 413]
    D -->|Không| F[Lưu file tạm aiofiles]
    F --> G[Xác định file_ext]
    G --> H{ParserFactory có parser?}
    H -->|Không| I[HTTP 400 Unsupported type]
    H -->|Có| J[parser]
    J --> K{Timeout > API\_TIMEOUT?}
    K -->|Có| L[HTTP 504]
    K -->|Không| M{parsed\_result.is_success?}
    M -->|Không| N[HTTP 400 failed_reason]
    M -->|Có| O[Trả FileResponse]
    O --> P[Cleanup file tạm]
4.2 Sequence nội bộ
sequenceDiagram
    participant Client
    participant FastAPI as FastAPI Router
    participant Limiter
    participant FileSvc as FileService
    participant Factory as ParserFactory
    participant Parser as Concrete Parser

    Client->>FastAPI: POST /sdlc/convert-document
    FastAPI->>Limiter: enforce rate limit
    FastAPI->>FileSvc: save_upload_to_temp()
    FastAPI->>Factory: get_parser(ext)
    Factory-->>FastAPI: parser instance
    FastAPI->>Parser: parse(file_path) via ThreadPoolExecutor
    Parser-->>FastAPI: ParsedResult(content/fail)
    FastAPI-->>Client: FileResponse JSON
5. Thành phần chính
5.1 Middleware & QoS
TimeoutMiddleware: bao request trong asyncio.wait_for (mặc định 5s override settings) để tránh kẹt event loop.
SlowAPIMiddleware + slowapi Limiter: chống flood, cấu hình settings.rate_limit (mặc định 50/minute).
Exception handler RateLimitExceeded: trả JSON 429 thống nhất.
5.2 Service Layer
save_upload_to_temp: dùng aiofiles, lưu /tmp/uploads/<uuid>.<ext> và trả (file_id, path).
ParserFactory.get_parser(ext): mapping ext → parser, raise ValueError nếu không hỗ trợ.
5.3 Parser Layer (trích xuất nổi bật)
Parser	Chức năng chính	Thư viện	Ghi chú
PDFParser	Phân loại native vs scan, OCR khi cần	fitz, pdfplumber, pdf2image, pytesseract, OpenCV	Kiểm tra >50 trang, convert Markdown
DocParser	Giữ định dạng heading, bảng, TOC	python-docx, lxml	Tự convert .doc → .docx, xử lý merge cell
PPTParser	Trích xuất text theo slide	python-pptx	Ghi log từng shape
XLSXParser	Xuất từng sheet thành bảng MD	pandas, numpy	Lọc cột/hàng rỗng, tối ưu markdown table
TxtParser	Đọc UTF-8/Latin-1 fallback	built-in	
JsonParser	Render JSON thành bullet Markdown	json	Đệ quy object/list
MdParser	Passthrough nội dung gốc	built-in	
6. Đặc tả API
6.1 Endpoint Health Check
Thuộc tính	Giá trị
Method & Path	GET /
Chức năng	Kiểm tra trạng thái dịch vụ
Rate limit	Theo settings.rate_limit
Response 200	{ "status": "ok" }
6.2 Endpoint Convert Document
Thuộc tính	Giá trị
Method & Path	POST /sdlc/convert-document
Yêu cầu	Multipart form-data file: UploadFile
Kích thước tối đa	settings.max_file_size (mặc định 10 MB)
Timeout xử lý	settings.timeout (endpoint) hoặc middleware (5s)
Bảo vệ	SlowAPI rate limit, TimeoutMiddleware, cleanup file tạm
Response Body (200 OK)
{
  "id": "uuid",
  "file_name": "report.pdf",
  "file_size": 1048576,
  "file_type": "application/pdf",
  "extracted_content": "# Markdown..."
}
Mã lỗi chính
HTTP	Khi nào	Chi tiết
400	Parser fail / định dạng không hỗ trợ	detail chứa failed_reason
413	Vượt giới hạn kích thước	Nêu rõ max MB
429	Vượt rate limit	Handler custom
500	Lỗi hệ thống	Log JSON chứa stack
504	Timeout xử lý	Cả middleware và endpoint
7. Mô hình dữ liệu
FileResponse (app/models.py): schema trả về.
ParsedResult: giao tiếp nội bộ giữa parser và API, gồm is_success, content, failed_reason.
classDiagram
    class FileResponse {
        +string id
        +string file_name
        +int file_size
        +string file_type
        +string extracted_content
    }
    class ParsedResult {
        +bool is_success
        +string? content
        +string? failed_reason
    }
    class BaseParser {
        +parse(file_path) ParsedResult
    }
    BaseParser <|-- PDFParser
    BaseParser <|-- DocParser
    BaseParser <|-- PPTParser
    BaseParser <|-- XLSXParser
    BaseParser <|-- TxtParser
    BaseParser <|-- JsonParser
    BaseParser <|-- MdParser
8. Phi chức năng & Bảo mật
Logging chuẩn JSON (app/utils.get_logger): ghi file xoay vòng (100MB x5) và console, phục vụ ELK.
Cấu hình động (app/config.py – BaseSettings): đọc .env hoặc biến môi trường (APP_NAME, RATE_LIMIT, OCR_LANG, LOG_LEVEL, TIMEOUT, MAX_FILE_SIZE, MAX_PAGE_LIMIT,...).
Hiệu năng:
Upload đọc toàn bộ file.read() (blocking) ⇒ phù hợp file nhỏ, có thể cải thiện chunked upload.
CPU-bound (OCR, doc parsing) chạy trong ThreadPoolExecutor để không block event loop.
Tài nguyên:
Thư mục /tmp/uploads cần write permission.
OCR phụ thuộc tesseract, poppler (cài trong Dockerfile).
Bảo mật:
Không lưu file vĩnh viễn, xóa ngay sau xử lý (finally block).
Rate limit tránh brute force.
Chưa bật auth → layer bảo vệ nên đặt phía trước (API Gateway, mTLS hoặc JWT).
9. Khoản mục vận hành
Hạng mục	Nội dung
Deploy	Dockerfile + docker-compose mount thư mục ./uploads → /tmp/uploads
Healthcheck	/
Observability	Log JSON, cần bổ sung metrics (FastAPI Instrumentation)
Scaling	Stateless, scale ngang theo Pods/Containers; chú ý giới hạn ThreadPool
Backup	Không lưu trữ dữ liệu lâu dài, không cần backup file tạm
10. Kiểm thử & QA
tests/test_upload.py: smoke test health & upload validation.
Đề xuất bổ sung:
Unit test cho từng parser với sample fixtures.
Integration test cho luồng OCR/timeout.
Load test rate limit.
11. Kế hoạch mở rộng
Thêm các parser mới (CSV, HTML) bằng cách kế thừa BaseParser và đăng ký trong ParserFactory.
Caching kết quả parse (Redis) để tránh OCR lại.
Bổ sung auth/JWT, key-based throttling, S3 output.
Streaming upload để giảm memory footprint.
Tài liệu này mô tả toàn diện kiến trúc, luồng thực thi và đặc tả API của mini-file-parser để các đội ngũ phát triển, QA và vận hành có thể triển khai và mở rộng thống nhất.