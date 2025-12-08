import random
import re
import gc
import fitz
import numpy as np
import cv2
from spellchecker import SpellChecker

def check_scanned_pdf(
    pdf_source,
    min_text_len=30,
    img_cover_ratio=0.4,
    sample_ratio=0.1,
    large_image_threshold=0.3,
):
    """
    Kiểm tra xem PDF có phải là bản scan hay không.
    Chỉ sampling ngẫu nhiên một tỷ lệ trang (sample_ratio)
    """

    VALID_CHARS = re.compile(r"[a-zA-ZÀ-ỹ0-9\s.,;:!?()'\-]+")

    try:
        spell_en = SpellChecker(language="en")
    except Exception:
        spell_en = None

    # ----------------------------- Helpers -----------------------------
    def get_text_quality_score(text):
        text = text.strip()
        if not text:
            return 0, 0
        valid_chars = len("".join(VALID_CHARS.findall(text)))
        weird_ratio = 1 - valid_chars / max(len(text), 1)
        words = re.findall(r"\b\w+\b", text)
        if not words:
            return weird_ratio, 0
        avg_word_len = sum(len(w) for w in words) / len(words)
        return weird_ratio, avg_word_len

    def get_language_quality(text):
        words = re.findall(r"\b\w+\b", text.lower())
        if not words or spell_en is None:
            return 0, 0
        misspelled = [w for w in words if w not in spell_en]
        error_ratio = len(misspelled) / len(words)

        accented_chars = set(
            "ăâêôơưđáàạảãắằặẳẵầấậẩẫéèẹẻẽếềệểễóòọỏõốồộổỗớờợởỡúùụủũứừựửữíìịỉĩýỳỵỷỹ"
        )
        accent_ratio = sum(c in accented_chars for c in text.lower()) / max(len(text), 1)
        return error_ratio, accent_ratio

    def analyze_page_texture(page, dpi=50):
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        contrast = float(gray.std())
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        white_ratio = float(np.mean(gray > 240))

        del pix, img, gray
        gc.collect()
        return contrast, lap_var, white_ratio

    # ----------------------------- Main Logic -----------------------------
    doc = None
    texture_vals = []
    weird_ratios = []
    avg_word_lengths = []
    spell_error_ratios = []
    accent_ratios = []
    total_text_len = 0

    try:
        if isinstance(pdf_source, str):
            doc = fitz.open(pdf_source)
        elif hasattr(pdf_source, "read"):
            data = pdf_source.read()
            doc = fitz.open(stream=data, filetype="pdf")
        else:
            doc = fitz.open(stream=pdf_source, filetype="pdf")

        total_pages = len(doc)
        pages_with_large_image = 0

        # ----------- Sample 10% trang ngẫu nhiên -----------
        n_sample = max(1, int(total_pages * sample_ratio))
        sampled_indices = sorted(random.sample(range(total_pages), n_sample))

        for i in range(total_pages):
            page = doc[i]
            try:
                text = page.get_text("text") or ""
                total_text_len += len(text)

                if text:
                    weird, wlen = get_text_quality_score(text)
                    weird_ratios.append(weird)
                    avg_word_lengths.append(wlen)

                    err, accent = get_language_quality(text)
                    spell_error_ratios.append(err)
                    accent_ratios.append(accent)

                #  Check large images
                page_area = page.rect.width * page.rect.height
                for img in page.get_images(full=True):
                    xref = img[0]
                    try:
                        bbox = page.get_image_bbox(xref)
                        img_area = bbox.width * bbox.height
                    except:
                        img_area = img[2] * img[3]
                    if img_area / page_area > img_cover_ratio:
                        pages_with_large_image += 1
                        break

                # Chỉ phân tích texture của các trang được sample
                if i in sampled_indices:
                    texture_vals.append(analyze_page_texture(page))

                del page, text
                gc.collect()

            except Exception:
                continue

        # ---------------------- Summary Metrics ----------------------
        has_text = total_text_len > min_text_len
        large_img_ratio = pages_with_large_image / max(total_pages, 1)

        contrast = float(np.mean([x[0] for x in texture_vals])) if texture_vals else 0
        lap_var = float(np.mean([x[1] for x in texture_vals])) if texture_vals else 0
        white_ratio = float(np.mean([x[2] for x in texture_vals])) if texture_vals else 0

        avg_weird = float(np.mean(weird_ratios)) if weird_ratios else 0
        spell_err = float(np.mean(spell_error_ratios)) if spell_error_ratios else 0
        accent_ratio = float(np.mean(accent_ratios)) if accent_ratios else 0
        text_density = total_text_len / max(total_pages, 1)

        # ---------------------- Classification Rules ----------------------
        if large_img_ratio >= large_image_threshold:
            return True

        if has_text and pages_with_large_image == 0:
            return False
        elif not has_text and pages_with_large_image > 0:
            return True

        elif has_text and pages_with_large_image:
            if text_density > 100:
                if avg_weird > 0.03 or spell_err > 0.15 or accent_ratio < 0.03:
                    return True
                return False
            else:
                if (lap_var > 400 or contrast > 25) and white_ratio < 0.96:
                    return True
                return False

        return True

    except fitz.FileDataError:
        return True

    finally:
        if doc:
            try:
                doc.close()
            except:
                pass

        del doc, texture_vals, weird_ratios, avg_word_lengths
        del spell_error_ratios, accent_ratios
        gc.collect()
