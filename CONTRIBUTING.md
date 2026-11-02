# Contributing to Inhouse AI

## Report an issue

Open a GitHub issue with a clear title, the steps to reproduce the problem, expected and
actual behavior, and relevant environment details. Remove secrets and personal data from
logs before posting. For suspected security vulnerabilities, follow [SECURITY.md](./SECURITY.md)
instead of opening a public issue.

## Add a benchmark result

Add a row to the example results table in [README.md](./README.md). Include the machine,
GPU and VRAM, RAM, model, quantization, and context length, plus these five measurements:

1. Prompt tokens read
2. Wait before first token
3. Prompt-reading speed (tokens/second)
4. Output-writing speed (tokens/second)
5. Number of runs averaged

Record the measurement settings and use warmed-up, fresh runs. Do not include credentials,
private prompts, or personal documents in a benchmark contribution.
