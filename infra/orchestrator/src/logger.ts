/**
 * Structured JSON logging for the orchestrator Lambda.
 * One JSON object per line. Includes session_id per invocation.
 */

export interface LogContext {
  agent: string;
  function: string;
}

export interface LogEntry {
  timestamp: string;
  level: "info" | "warn" | "error";
  message: string;
  agent: string;
  function: string;
  session_id?: string;
  [key: string]: unknown;
}

let _context: LogContext = { agent: "", function: "orchestrator" };

export function setLogContext(ctx: LogContext): void {
  _context = ctx;
}

function emit(level: LogEntry["level"], message: string, extra?: Record<string, unknown>): void {
  const entry: LogEntry = {
    timestamp: new Date().toISOString(),
    level,
    message,
    agent: _context.agent,
    function: _context.function,
    ...extra,
  };
  // Single JSON object per line
  process.stdout.write(JSON.stringify(entry) + "\n");
}

export function info(message: string, extra?: Record<string, unknown>): void {
  emit("info", message, extra);
}

export function warn(message: string, extra?: Record<string, unknown>): void {
  emit("warn", message, extra);
}

export function error(message: string, extra?: Record<string, unknown>): void {
  emit("error", message, extra);
}

export function summary(invoked: number, skipped: number, failed: number): void {
  emit("info", "Orchestration complete", { invoked, skipped, failed });
}
