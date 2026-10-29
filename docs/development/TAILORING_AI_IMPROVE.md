# Tailoring Studio AI Improve

AI Improve is an optional, review-only assistant for one selected résumé bullet. It is deliberately separate from deterministic résumé tailoring and never applies or approves a change automatically.

## Runtime behavior

Requests return a job ID immediately. The Tailoring Studio polls the job status and shows elapsed time while the local Ollama request runs. The configured timeout is a wall clock deadline for the whole operation, including the single permitted safety retry; it is not reset for a retry. The default per-request limit is 30 seconds and 256 output tokens; configure OLLAMA_TAILORING_TIMEOUT_SECONDS and OLLAMA_TAILORING_MAX_OUTPUT_TOKENS to lower limits when desired. The effective values are capped by the base Ollama configuration.

The initial request uses one attempt. A second request is made only when the first response is returned but fails factual or quality validation, so timeouts and unavailable model errors are not retried. Unsafe or unusable retries are reported as rejected, while an unchanged validated response is reported separately as unchanged. The original bullet remains intact in all cases.

Cancellation sets a cancellation event and closes an active streaming HTTP response at the next response boundary. Only one inference job is admitted at a time; a concurrent request receives a busy response rather than competing for the GPU. Completed job records are retained for a bounded period and then expire from memory. Ollama cannot interrupt tokens that have already been delivered by the provider, so cancellation is best effort and the UI reports the actual terminal state.

Tailoring requests send keep_alive: 0, asking Ollama to unload the model after completion. This reduces idle GPU memory use and avoids holding the model while the user reviews a suggestion. The tradeoff is that the next AI Improve request pays the model startup/load latency again. This cleanup applies only to Tailoring Studio requests and does not change other Ollama workflows.

Factual validation remains mandatory: numbers, technologies, employers, projects and supported facts must be preserved, and a suggestion that cannot pass validation is rejected. Apply and Approve remain separate user actions.