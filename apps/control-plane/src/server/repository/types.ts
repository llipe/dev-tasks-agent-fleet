/**
 * ReadOutcome<T> — a discriminated union representing the result of
 * any read operation against external systems (DynamoDB, CloudWatch, etc.)
 *
 * Every variant carries a correlationId for tracing/debugging.
 */

import { randomUUID } from "node:crypto";

export type ReadOutcome<T> =
  | { status: "ok"; data: T; correlationId: string }
  | { status: "empty"; correlationId: string }
  | { status: "timeout"; correlationId: string }
  | { status: "error"; error: string; correlationId: string };

/** Helper to build a correlation id */
export function makeCorrelationId(): string {
  return randomUUID();
}

/** Convenience constructors */
export function okOutcome<T>(data: T, correlationId?: string): ReadOutcome<T> {
  return { status: "ok", data, correlationId: correlationId ?? makeCorrelationId() };
}

export function emptyOutcome<T>(correlationId?: string): ReadOutcome<T> {
  return { status: "empty", correlationId: correlationId ?? makeCorrelationId() };
}

export function timeoutOutcome<T>(correlationId?: string): ReadOutcome<T> {
  return { status: "timeout", correlationId: correlationId ?? makeCorrelationId() };
}

export function errorOutcome<T>(error: string, correlationId?: string): ReadOutcome<T> {
  return { status: "error", error, correlationId: correlationId ?? makeCorrelationId() };
}
