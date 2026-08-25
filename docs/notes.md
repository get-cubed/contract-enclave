# Notes

- **Model choice**: the demo uses the Apache-2.0 `qwen3-vl:8b-instruct`
  Ollama tag. It is a practical baseline, not a claim that one model is best
  for every client's scan quality, language mix, or contract format. Grade
  candidate OCR/vision models against representative client documents before
  selecting a production model.
- Sample contracts are synthetic and watermarked as such on every page.
- **Context length**: discovery and each formula-normalization pass send the
  whole transcript (with 4k and 1k response budgets respectively). The model
  tag advertises a large maximum context, but the
  context actually available depends on the Ollama/vLLM serving configuration
  and GPU memory. Check the loaded configuration and split/chunk long contracts
  rather than assuming the advertised maximum is available.
