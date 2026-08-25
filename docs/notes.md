# Notes

- **Model choices**: Qwen3-VL-8B is a direct upgrade of Qwen2.5-VL with much
  better OCR. Worth evaluating next: `olmOCR-2-7B` (a Qwen2.5-VL fine-tune
  trained on scanned legal docs, Apache-2.0) for transcription, and tiny
  parsers (DeepSeek-OCR-2, MinerU2.5) that run on even cheaper GPUs.
- Sample contracts are synthetic and watermarked as such on every page.
- **Context length**: the analysis step sends the whole transcript plus a 4k
  response budget, so a long contract (roughly 15+ dense pages) can overflow
  a 12k window. Local Ollama manages its own window; if you ever serve with
  vLLM, size `--max-model-len` accordingly or split the document.
