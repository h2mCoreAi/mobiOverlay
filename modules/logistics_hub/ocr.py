"""OCR pipeline for Logistics Hub — runs in a background thread.

This module isolates the heavy OCR work (easyocr/PyTorch inference) from
the Qt UI thread. All functions here are pure/stateless and can safely
run in any thread.

Extracted as part of M2 (background OCR) optimization — see
docs/OPTIMIZATION.md and docs/DECISIONS.md.
"""

# EasyOCR character allowlist: letters, digits, and every punctuation mark
# observed in real captured contract text. Restricts the OCR classifier's
# output space without risk of rejecting valid characters.
OCR_ALLOWLIST = (
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    " .,:;'\"-/()[]*_%&!?"
)

# Upscale factor for OCR preprocessing — small in-game text needs 2x
# upscale before detection for reliable recognition.
OCR_UPSCALE_FACTOR = 2


def order_ocr_boxes(results: list, image_width: int) -> list[str]:
    """Reorder EasyOCR's `detail=1` results into genuine left-to-right,
    top-to-bottom reading order for two-column contract panels.

    The in-game contract panel is consistently two columns (mission
    narrative text next to a separate PICK UP/DROP OFF list). This splits
    at the largest horizontal gap (if wide enough) and reads each column
    top-to-bottom before moving to the next.

    Args:
        results: EasyOCR detail=1 output, list of (bbox, text, confidence)
        image_width: Width of the image (in upscaled pixels)

    Returns:
        List of text strings in reading order
    """
    boxes = []
    for bbox, text, _confidence in results:
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        boxes.append({"text": text, "x_min": min(xs), "y_center": sum(ys) / len(ys)})

    if len(boxes) < 2:
        return [b["text"] for b in boxes]

    ordered = sorted(boxes, key=lambda b: b["x_min"])
    gaps = [(ordered[i + 1]["x_min"] - ordered[i]["x_min"], i) for i in range(len(ordered) - 1)]
    biggest_gap, split_idx = max(gaps)

    # A real column boundary is a large fraction of the capture's own
    # width, not a fixed pixel count.
    if biggest_gap < max(50, image_width * 0.15):
        columns = [ordered]
    else:
        columns = [ordered[: split_idx + 1], ordered[split_idx + 1 :]]

    lines: list[str] = []
    for column in columns:
        lines.extend(b["text"] for b in sorted(column, key=lambda b: b["y_center"]))
    return lines


def preprocess_image(pil_rgb, ImageOps, Image):
    """Preprocess a PIL RGB image for OCR: grayscale, upscale, autocontrast.

    Args:
        pil_rgb: PIL Image in RGB mode
        ImageOps: PIL.ImageOps module
        Image: PIL.Image module

    Returns:
        Preprocessed grayscale PIL Image (upscaled)
    """
    gray = ImageOps.grayscale(pil_rgb)
    gray = gray.resize(
        (gray.width * OCR_UPSCALE_FACTOR, gray.height * OCR_UPSCALE_FACTOR),
        Image.LANCZOS,
    )
    gray = ImageOps.autocontrast(gray)
    return gray


def run_ocr(reader, gray_image, np) -> str:
    """Run EasyOCR on a preprocessed grayscale image.

    Args:
        reader: Initialized easyocr.Reader instance
        gray_image: Preprocessed PIL Image (grayscale, upscaled)
        np: numpy module

    Returns:
        Raw OCR text with lines joined by newlines
    """
    results = reader.readtext(np.array(gray_image), detail=1, allowlist=OCR_ALLOWLIST)
    lines = order_ocr_boxes(results, gray_image.width)
    return "\n".join(lines)
