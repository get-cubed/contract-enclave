"""PDF -> per-page markdown transcription via a vision model."""

import base64
import io

import pypdfium2 as pdfium
from openai import OpenAI

from .model import chat

OCR_PROMPT = (
    "Transcribe this contract page to clean GitHub-flavored markdown. "
    "Preserve section numbering, headings, and tables exactly as printed. "
    "Do not summarize, annotate, or omit anything. "
    "Output only the transcription, no commentary."
)

PAGE_SEPARATOR = "\n\n---\n\n"


def render_pages(pdf_path: str, dpi: int = 170):
    """Yield (page_number, png_bytes) for each page of the PDF.

    170 dpi puts a Letter page around 1450x1880 px -- crisp enough for table
    OCR without bloating the vision model's input.
    """
    doc = pdfium.PdfDocument(pdf_path)
    try:
        for i in range(len(doc)):
            bitmap = doc[i].render(scale=dpi / 72)
            buf = io.BytesIO()
            bitmap.to_pil().save(buf, format="PNG")
            yield i + 1, buf.getvalue()
    finally:
        doc.close()


def page_count(pdf_path: str) -> int:
    doc = pdfium.PdfDocument(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


def ocr_pdf(client: OpenAI, model: str, pdf_path: str, log=print,
            verbose: bool = False, audit=None) -> str:
    """Transcribe every page of a PDF, returning one markdown document.

    One model call per page, each narrated to the terminal and recorded in
    the audit list (see model.chat).
    """
    total = page_count(pdf_path)
    pages_md = []
    for page_no, png in render_pages(pdf_path):
        b64 = base64.b64encode(png).decode()
        text = chat(
            client, model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                        {"type": "text", "text": OCR_PROMPT},
                    ],
                }
            ],
            purpose=f"OCR page {page_no}/{total}",
            audit=audit, log=log, verbose=verbose,
        )
        pages_md.append(text)
    return PAGE_SEPARATOR.join(pages_md)
