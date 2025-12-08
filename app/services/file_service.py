import os
import uuid
from typing import Tuple

import aiofiles

from app.config import settings


async def save_upload_to_temp(filename: str, content: bytes) -> Tuple[str, str]:
    """Save an uploaded file content to temporary upload directory.

    Returns a tuple of (file_id, saved_path).
    """
    file_ext = filename.split(".")[-1].lower() if "." in filename else ""
    file_id = str(uuid.uuid4())
    os.makedirs(settings.upload_dir, exist_ok=True)
    temp_path = os.path.join(settings.upload_dir, f"{file_id}.{file_ext}" if file_ext else file_id)
    async with aiofiles.open(temp_path, "wb") as f:
        await f.write(content)
    return file_id, temp_path


