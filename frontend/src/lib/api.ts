export type Summary = {
  customers: number;
  obligations: number;
  pending_jobs: number;
  attempted_calls: number;
  successful_calls: number;
  blocked_calls: number;
  // Resultado, no actividad. null = sin medicion, distinto de 0.
  on_time_rate_treatment: number | null;
  on_time_rate_control: number | null;
};

export type Obligation = {
  id: string;
  product_type: string;
  next_due_date: string;
  // Calculado en el backend con la zona horaria del cliente: no lo recalcules
  // en el navegador, que corre en la zona del operador.
  days_to_due: number;
  amount_due: string;
  currency: string;
  status: string;
  reschedule_eligible: boolean;
  earliest_new_date: string | null;
  latest_new_date: string | null;
  unemployment_insurance_active: boolean;
  on_time_payments: number;
  total_payments: number;
};

export type Customer = {
  id: string;
  external_ref: string;
  preferred_name: string;
  // Solo el anio: la fecha completa no se guarda en claro, se compara por HMAC
  // en verify_identity. La edad derivada de aqui tiene +-1 anio de error.
  birth_year: number;
  timezone: string;
  language: string;
  segment: string;
  status: string;
  cohort: string;
  phone_last4: string | null;
  do_not_call: boolean;
  consent_status: string | null;
  preferred_call_window: string | null;
  last_call_at: string | null;
  last_call_outcome: string | null;
  obligations: Obligation[];
};

export type CallJob = {
  id: string;
  customer_name: string;
  obligation_product: string;
  scheduled_at: string;
  status: string;
  attempt_count: number;
  last_error: string | null;
};

export type Call = {
  id: string;
  customer_name: string;
  status: string;
  outcome: string;
  sentiment: string | null;
  duration_ms: number | null;
  summary: string | null;
  transcript: string | null;
  recording_url: string | null;
  created_at: string;
};

export type ToolExecution = {
  id: string;
  retell_call_id: string | null;
  tool_name: string;
  started_at: string;
  duration_ms: number;
  status: string;
  error_code: string | null;
  request_redacted: Record<string, unknown>;
  response_redacted: Record<string, unknown>;
};

export type WebhookEvent = {
  id: string;
  retell_call_id: string | null;
  event_type: string;
  received_at: string;
  processed_at: string | null;
  status: string;
  error: string | null;
};

export type WebCall = {
  call_id: string;
  access_token: string;
  transport?: "livekit" | "gateway";
  ice_servers?: RTCIceServer[];
};

const API_BASE = import.meta.env.VITE_API_URL ?? "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export const api = {
  summary: () => request<Summary>("/dashboard/summary"),
  customers: () => request<Customer[]>("/customers"),
  jobs: () => request<CallJob[]>("/call-jobs"),
  calls: () => request<Call[]>("/calls"),
  toolExecutions: () => request<ToolExecution[]>("/retell/tool-executions"),
  webhookEvents: () => request<WebhookEvent[]>("/retell/webhook-events"),
  webCall: (customerId: string, obligationId: string) =>
    request<WebCall>("/retell/web-calls", {
      method: "POST",
      body: JSON.stringify({ customer_id: customerId, obligation_id: obligationId })
    }),
  schedule: (customerId: string, obligationId: string) =>
    request<CallJob>("/call-jobs", {
      method: "POST",
      body: JSON.stringify({ customer_id: customerId, obligation_id: obligationId })
    })
};
