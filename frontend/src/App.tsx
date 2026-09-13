import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, Headphones, PhoneCall, RefreshCw, ShieldCheck } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, Call, CallJob, Customer, Summary } from "./lib/api";

type LoadState = {
  summary: Summary | null;
  customers: Customer[];
  jobs: CallJob[];
  calls: Call[];
};

const emptyState: LoadState = {
  summary: null,
  customers: [],
  jobs: [],
  calls: []
};

export function App() {
  const [data, setData] = useState<LoadState>(emptyState);
  const [selectedCustomerId, setSelectedCustomerId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const selectedCustomer = useMemo(
    () => data.customers.find((customer) => customer.id === selectedCustomerId) ?? data.customers[0],
    [data.customers, selectedCustomerId]
  );

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [summary, customers, jobs, calls] = await Promise.all([api.summary(), api.customers(), api.jobs(), api.calls()]);
      setData({ summary, customers, jobs, calls });
      setSelectedCustomerId((current) => current ?? customers[0]?.id ?? null);
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "No se pudo cargar la API");
    } finally {
      setLoading(false);
    }
  }

  async function schedule(customer: Customer) {
    const obligation = customer.obligations[0];
    if (!obligation) return;
    await api.schedule(customer.id, obligation.id);
    await load();
  }

  useEffect(() => {
    void load();
  }, []);

  const chartData = [
    { name: "Pendientes", value: data.summary?.pending_jobs ?? 0 },
    { name: "Intentadas", value: data.summary?.attempted_calls ?? 0 },
    { name: "Exitosas", value: data.summary?.successful_calls ?? 0 },
    { name: "Bloqueadas", value: data.summary?.blocked_calls ?? 0 }
  ];

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <ShieldCheck size={24} />
          <div>
            <strong>Banca Inteligente</strong>
            <span>Cobranza preventiva</span>
          </div>
        </div>
        <nav>
          <a className="active">Operación</a>
          <a>Clientes</a>
          <a>Llamadas</a>
          <a>Retell</a>
        </nav>
        <div className="safety">
          <AlertTriangle size={18} />
          <p>El worker solo llama a teléfonos permitidos por allowlist.</p>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <span className="eyebrow">MVP 12 horas</span>
            <h1>Centro de llamadas preventivas</h1>
          </div>
          <button className="iconButton" onClick={() => void load()} title="Actualizar">
            <RefreshCw size={18} />
          </button>
        </header>

        {error && <div className="error">{error}</div>}

        <section className="metrics">
          <Metric icon={<Headphones />} label="Clientes" value={data.summary?.customers ?? 0} />
          <Metric icon={<Clock3 />} label="Pendientes" value={data.summary?.pending_jobs ?? 0} />
          <Metric icon={<PhoneCall />} label="Intentadas" value={data.summary?.attempted_calls ?? 0} />
          <Metric icon={<CheckCircle2 />} label="Exitosas" value={data.summary?.successful_calls ?? 0} />
        </section>

        <section className="grid">
          <div className="panel span2">
            <div className="panelHeader">
              <div>
                <h2>Embudo operativo</h2>
                <p>Se actualiza desde la base local y webhooks Retell.</p>
              </div>
            </div>
            <div className="chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" />
                  <YAxis allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="value" fill="#256f68" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="panel">
            <div className="panelHeader">
              <h2>Cliente seleccionado</h2>
            </div>
            {selectedCustomer ? (
              <div className="customerFocus">
                <strong>{selectedCustomer.preferred_name}</strong>
                <span>{selectedCustomer.segment} · termina {selectedCustomer.phone_last4 ?? "----"}</span>
                <dl>
                  <div>
                    <dt>Producto</dt>
                    <dd>{selectedCustomer.obligations[0]?.product_type ?? "Sin obligación"}</dd>
                  </div>
                  <div>
                    <dt>Vence</dt>
                    <dd>{selectedCustomer.obligations[0]?.next_due_date ?? "N/A"}</dd>
                  </div>
                  <div>
                    <dt>Monto</dt>
                    <dd>
                      {selectedCustomer.obligations[0]?.currency} {selectedCustomer.obligations[0]?.amount_due}
                    </dd>
                  </div>
                </dl>
                <button onClick={() => void schedule(selectedCustomer)} disabled={loading || selectedCustomer.do_not_call}>
                  <PhoneCall size={17} />
                  Programar llamada
                </button>
              </div>
            ) : (
              <p className="muted">Ejecuta el seed para cargar clientes.</p>
            )}
          </div>
        </section>

        <section className="tables">
          <div className="panel">
            <div className="panelHeader">
              <h2>Clientes</h2>
            </div>
            <div className="list">
              {data.customers.map((customer) => (
                <button
                  className={customer.id === selectedCustomer?.id ? "row selected" : "row"}
                  key={customer.id}
                  onClick={() => setSelectedCustomerId(customer.id)}
                >
                  <span>
                    <strong>{customer.preferred_name}</strong>
                    <small>{customer.external_ref}</small>
                  </span>
                  <em>{customer.do_not_call ? "No llamar" : customer.segment}</em>
                </button>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panelHeader">
              <h2>Cola</h2>
            </div>
            <div className="list">
              {data.jobs.map((job) => (
                <div className="row" key={job.id}>
                  <span>
                    <strong>{job.customer_name}</strong>
                    <small>{new Date(job.scheduled_at).toLocaleString()}</small>
                  </span>
                  <em>{job.status}</em>
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panelHeader">
              <h2>Llamadas</h2>
            </div>
            <div className="list">
              {data.calls.map((call) => (
                <div className="callRow" key={call.id}>
                  <div>
                    <strong>{call.customer_name}</strong>
                    <small>{call.outcome}</small>
                  </div>
                  <p>{call.summary ?? call.transcript ?? "Sin resumen todavía."}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
      </section>
    </main>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <article className="metric">
      <div>{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

