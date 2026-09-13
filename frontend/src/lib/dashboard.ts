import type { Call, CallJob, Customer, Summary, ToolExecution, WebhookEvent } from "./api";

export type LoadState = {
  summary: Summary | null;
  customers: Customer[];
  jobs: CallJob[];
  calls: Call[];
  toolExecutions: ToolExecution[];
  webhookEvents: WebhookEvent[];
};

export const emptyState: LoadState = {
  summary: null,
  customers: [],
  jobs: [],
  calls: [],
  toolExecutions: [],
  webhookEvents: []
};

// Mismo orden que las promesas que recibe mergeLoadResults: la posicion es lo
// unico que aparea cada resultado con su seccion del panel.
export const LOAD_LABELS = [
  "el resumen",
  "los clientes",
  "la cola",
  "las llamadas",
  "las funciones del agente",
  "los webhooks"
];

export function valueOf<T>(result: PromiseSettledResult<unknown> | undefined, fallback: T): T {
  return result?.status === "fulfilled" ? (result.value as T) : fallback;
}

/** Estado nuevo, conservando lo que ya estaba en las secciones que fallaron.
 *
 * Vaciar una tabla porque su endpoint devolvio 404 miente mas que dejar el
 * dato anterior: el operador no distingue "no hay clientes" de "no cargo".
 */
export function mergeLoadResults(results: PromiseSettledResult<unknown>[], current: LoadState): LoadState {
  return {
    summary: valueOf(results[0], current.summary),
    customers: valueOf(results[1], current.customers),
    jobs: valueOf(results[2], current.jobs),
    calls: valueOf(results[3], current.calls),
    toolExecutions: valueOf(results[4], current.toolExecutions),
    webhookEvents: valueOf(results[5], current.webhookEvents)
  };
}

export function failedSections(results: PromiseSettledResult<unknown>[]): string[] {
  return LOAD_LABELS.filter((_, index) => results[index]?.status === "rejected");
}
