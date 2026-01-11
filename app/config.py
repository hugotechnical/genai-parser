from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    app_name: str = "File Parsing API"
    version: str = "1.0.0"
    debug: bool = True
    upload_dir: str = "/tmp/uploads"
    rate_limit: str = "50/minute"
    ocr_lang: str = "vie+eng+osd"
    log_level: str = "DEBUG"
    timeout: int = 300
    max_file_size: int = 10 * 1024 * 1024
    max_page_limit: int = 150
    tesseract_config_cmd: str = r'--oem 3 --psm 3'
    tesseract_config_dpi: int = 2000
    max_concurrent_parser_light: int = 10
    max_concurrent_parser_heavy: int = 10
    tesseract_config_thread_image_convert: int = 4
    tesseract_config_max_worker: int = 4
    tesseract_config_batch_size: int = 20
    page_break_str: str = "\n\n--- Page Break ---\n\n"
    max_inspect_pages: int = 10
    heavy_extensions: set[str] | str = {"pdf"}

    @field_validator("heavy_extensions", mode="before")
    def split_set(cls, v):
        if isinstance(v, str):
            return {x.strip().lower() for x in v.split(",") if x.strip()}
        if isinstance(v, (list, set)):
            return set(v)
        return {"pdf"}

    class Config:
        env_file = ".env"


settings = Settings()
