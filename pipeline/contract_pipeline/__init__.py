"""Contract lost-value pipeline: PDF -> OCR -> findings -> report.

Every model call goes to a single OpenAI-compatible endpoint (Ollama on a
laptop, vLLM on a GPU server) so the same code runs anywhere the data lives.
"""

__version__ = "0.1.0"
