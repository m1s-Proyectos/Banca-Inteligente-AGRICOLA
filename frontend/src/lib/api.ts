export type Summary = {
  customers: number;
  obligations: number;
  pending_jobs: number;
  attempted_calls: number;
  successful_calls: number;
  blocked_calls: number;
};

export type Obligation = {
  id: string;
  product_type: string;
  next_due_date: string;
  amount_due: string;
  currency: string;
  status: string;
};

export type Customer = {
  id: string;
  external_ref: string;
  preferred_name: string;
  timezone: string;
  language: string;
  segment: string;
  status: string;
  phone_last4: string | null;
  do_not_call: boolean;
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
  summary: string | null;
  transcript: string | null;
  recording_url: string | null;
  created_at: string;
};

const API_BASE = "/api/v1";

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
  schedule: (customerId: string, obligationId: string) =>
    request<CallJob>("/call-jobs", {
      method: "POST",
      body: JSON.stringify({ customer_id: customerId, obligation_id: obligationId })
    })
};

