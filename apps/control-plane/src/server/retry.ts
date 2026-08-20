/**
 * Jittered exponential backoff retry helper.
 *
 * Retries on:
 *   - Throttle errors (ThrottlingException, TooManyRequestsException)
 *   - 5xx server errors
 *
 * Never retries:
 *   - ValidationException
 *   - AccessDeniedException
 *   - Any other 4xx error (except throttle)
 */

export interface RetryOptions {
  /** Base delay in ms (default: 100) */
  baseDelayMs?: number;
  /** Max delay in ms (default: 3000) */
  maxDelayMs?: number;
  /** Max retry attempts (default: 3) */
  maxRetries?: number;
}

const DEFAULT_OPTIONS: Required<RetryOptions> = {
  baseDelayMs: 100,
  maxDelayMs: 3000,
  maxRetries: 3,
};

const RETRYABLE_ERROR_CODES = new Set([
  "ThrottlingException",
  "TooManyRequestsException",
  "Throttling",
  "RequestThrottled",
  "ProvisionedThroughputExceededException",
]);

const NON_RETRYABLE_ERROR_CODES = new Set([
  "ValidationException",
  "AccessDeniedException",
  "ResourceNotFoundException",
  "ConditionalCheckFailedException",
  "InvalidParameterException",
  "MalformedQueryException",
]);

function isRetryable(error: unknown): boolean {
  if (typeof error !== "object" || error === null) return false;

  // Check named code
  const code = (error as { name?: string }).name ?? (error as { code?: string }).code ?? "";

  if (NON_RETRYABLE_ERROR_CODES.has(code)) return false;
  if (RETRYABLE_ERROR_CODES.has(code)) return true;

  // Check HTTP status code
  const statusCode =
    (error as { $metadata?: { httpStatusCode?: number } }).$metadata?.httpStatusCode ??
    (error as { statusCode?: number }).statusCode;

  if (typeof statusCode === "number") {
    // 429 = Too Many Requests (throttle)
    if (statusCode === 429) return true;
    // 5xx = server error
    if (statusCode >= 500 && statusCode < 600) return true;
    // Other 4xx = client error, not retryable
    if (statusCode >= 400 && statusCode < 500) return false;
  }

  return false;
}

function jitteredDelay(attempt: number, baseDelayMs: number, maxDelayMs: number): number {
  const exponentialDelay = baseDelayMs * Math.pow(2, attempt);
  const capped = Math.min(exponentialDelay, maxDelayMs);
  // Full jitter: random between 0 and capped
  return Math.random() * capped;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Execute a function with jittered exponential backoff retry.
 * Throws the last error after all retries are exhausted.
 */
export async function withRetry<T>(fn: () => Promise<T>, options?: RetryOptions): Promise<T> {
  const opts = { ...DEFAULT_OPTIONS, ...options };
  let lastError: unknown;

  for (let attempt = 0; attempt <= opts.maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error: unknown) {
      lastError = error;

      if (!isRetryable(error)) {
        throw error;
      }

      if (attempt < opts.maxRetries) {
        const delay = jitteredDelay(attempt, opts.baseDelayMs, opts.maxDelayMs);
        await sleep(delay);
      }
    }
  }

  throw lastError;
}

// Export for testing
export { isRetryable as _isRetryable, jitteredDelay as _jitteredDelay };
