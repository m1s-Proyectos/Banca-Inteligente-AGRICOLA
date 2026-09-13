import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Cake,
  CalendarDays,
  CheckCircle2,
  Clock3,
  FileText,
  Headphones,
  ListChecks,
  Mic,
  PhoneOff,
  PhoneCall,
  RefreshCw,
  ShieldCheck,
  Target,
  TrendingUp,
  UsersRound,
  Webhook,
  Wrench
} from "lucide-react";
import { RetellWebClient } from "retell-client-js-sdk";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, Call, CallJob, Customer, Obligation, Summary, ToolExecution, WebhookEvent } from "./lib/api";

type LoadState = {
  summary: Summary | null;
  customers: Customer[];
  jobs: CallJob[];
  calls: Call[];
  toolExecutions: ToolExecution[];
  webhookEvents: WebhookEvent[];
};

const emptyState: LoadState = {
  summary: null,
  customers: [],
  jobs: [],
  calls: [],
  toolExecutions: [],
  webhookEvents: []
};

type WebCallStatus = "idle" | "connecting" | "live" | "ended";

type TabId = "operacion" | "clientes" | "llamadas" | "retell";

const TABS: { id: TabId; label: string; title: string; subtitle: string }[] = [
  {
    id: "operacion",
    label: "Operación",
    title: "Centro de llamadas preventivas",
    subtitle: "Plataforma inteligente para gestión preventiva de cobranza y seguimiento de conversaciones."
  },
  {
    id: "clientes",
    label: "Clientes",
    title: "Cartera de clientes",
    subtitle: "Datos de contacto, consentimiento, vencimientos y comportamiento de pago de cada cliente."
  },
  {
    id: "llamadas",
    label: "Llamadas",
    title: "Cola y llamadas",
    subtitle: "Trabajos pendientes del worker y el detalle de cada conversación registrada."
  },
  {
    id: "retell",
    label: "Retell",
    title: "Auditoría del agente",
    subtitle: "Funciones que invocó Sofía durante las llamadas y webhooks recibidos de Retell."
  }
];

export function App() {
  const [data, setData] = useState<LoadState>(emptyState);
  const [tab, setTab] = useState<TabId>("operacion");
  const [selectedCustomerId, setSelectedCustomerId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [webCallStatus, setWebCallStatus] = useState<WebCallStatus>("idle");
  const retellWebClient = useMemo(() => new RetellWebClient(), []);

  const selectedCustomer = useMemo(
    () => data.customers.find((customer) => customer.id === selectedCustomerId) ?? data.customers[0],
    [data.customers, selectedCustomerId]
  );

  const activeTab = TABS.find((item) => item.id === tab) ?? TABS[0];

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [summary, customers, jobs, calls, toolExecutions, webhookEvents] = await Promise.all([
        api.summary(),
        api.customers(),
        api.jobs(),
        api.calls(),
        api.toolExecutions(),
        api.webhookEvents()
      ]);
      setData({ summary, customers, jobs, calls, toolExecutions, webhookEvents });
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
    setError(null);
    try {
      await api.schedule(customer.id, obligation.id);
      await load();
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "No se pudo programar la llamada");
    }
  }

  async function startWebCall(customer: Customer) {
    const obligation = customer.obligations[0];
    if (!obligation) return;
    setError(null);
    setWebCallStatus("connecting");
    try {
      const call = await api.webCall(customer.id, obligation.id);
      // transport y callId son de Retell, no adivinables: los dos tipos de token
      // son indistinguibles y el gateway direcciona la señalización por llamada.
      await retellWebClient.startCall({
        accessToken: call.access_token,
        transport: call.transport,
        callId: call.call_id,
        iceServers: call.ice_servers?.length ? call.ice_servers : undefined
      });
    } catch (currentError) {
      setWebCallStatus("idle");
      setError(currentError instanceof Error ? currentError.message : "No se pudo iniciar la llamada web");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    const started = () => setWebCallStatus("live");
    const ended = () => {
      setWebCallStatus("ended");
      window.setTimeout(() => void load(), 1200);
    };
    const failed = (reason: unknown) => {
      setWebCallStatus("idle");
      setError(typeof reason === "string" ? reason : "Retell no pudo conectar el audio");
    };
    retellWebClient.on("call_started", started);
    retellWebClient.on("call_ended", ended);
    retellWebClient.on("error", failed);
    return () => {
      retellWebClient.off("call_started", started);
      retellWebClient.off("call_ended", ended);
      retellWebClient.off("error", failed);
      retellWebClient.stopCall();
    };
  }, [retellWebClient]);

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandMark">
            <ShieldCheck size={22} />
          </div>
          <div>
            <strong>Banca Inteligente</strong>
            <span>Cobranza preventiva</span>
          </div>
        </div>
        <nav>
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={item.id === tab ? "navItem active" : "navItem"}
              aria-current={item.id === tab ? "page" : undefined}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="safety">
          <AlertTriangle size={18} />
          <p>El worker solo llama a teléfonos permitidos por allowlist.</p>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>{activeTab.title}</h1>
            <p>{activeTab.subtitle}</p>
          </div>
          <button className="iconButton" onClick={() => void load()} title="Actualizar">
            <RefreshCw size={18} />
          </button>
        </header>

        {error && <div className="error">{error}</div>}

        {tab === "operacion" && (
          <OperationTab
            data={data}
            loading={loading}
            selectedCustomer={selectedCustomer}
            onSelect={setSelectedCustomerId}
            webCallStatus={webCallStatus}
            onStartWebCall={startWebCall}
            onSchedule={schedule}
            onStopCall={() => retellWebClient.stopCall()}
            onPlayAudio={() => void retellWebClient.startAudioPlayback()}
          />
        )}

        {tab === "clientes" && (
          <CustomersTab
            customers={data.customers}
            selectedCustomer={selectedCustomer}
            onSelect={setSelectedCustomerId}
          />
        )}

        {tab === "llamadas" && <CallsTab jobs={data.jobs} calls={data.calls} />}

        {tab === "retell" && <RetellTab executions={data.toolExecutions} events={data.webhookEvents} />}
      </section>
    </main>
  );
}

function OperationTab({
  data,
  loading,
  selectedCustomer,
  onSelect,
  webCallStatus,
  onStartWebCall,
  onSchedule,
  onStopCall,
  onPlayAudio
}: {
  data: LoadState;
  loading: boolean;
  selectedCustomer: Customer | undefined;
  onSelect: (id: string) => void;
  webCallStatus: WebCallStatus;
  onStartWebCall: (customer: Customer) => void;
  onSchedule: (customer: Customer) => void;
  onStopCall: () => void;
  onPlayAudio: () => void;
}) {
  const chartData = [
    { name: "Pendientes", value: data.summary?.pending_jobs ?? 0 },
    { name: "Intentadas", value: data.summary?.attempted_calls ?? 0 },
    { name: "Exitosas", value: data.summary?.successful_calls ?? 0 },
    { name: "Bloqueadas", value: data.summary?.blocked_calls ?? 0 }
  ];

  return (
    <>
      <section className="metrics">
        <Metric icon={<Headphones />} label="Clientes" value={data.summary?.customers ?? 0} tone="primary" />
        <Metric icon={<Clock3 />} label="Pendientes" value={data.summary?.pending_jobs ?? 0} tone="warning" />
        <Metric icon={<PhoneCall />} label="Intentadas" value={data.summary?.attempted_calls ?? 0} tone="secondary" />
        <Metric icon={<CheckCircle2 />} label="Exitosas" value={data.summary?.successful_calls ?? 0} tone="success" />
        <Metric
          icon={<TrendingUp />}
          label="Pago puntual · llamados"
          value={formatRate(data.summary?.on_time_rate_treatment)}
          tone="success"
        />
        <Metric
          icon={<Target />}
          label="Pago puntual · control"
          value={formatRate(data.summary?.on_time_rate_control)}
          tone="secondary"
        />
      </section>

      <section className="grid">
        <div className="panel span2">
          <div className="panelHeader">
            <div>
              <h2>Embudo operativo</h2>
              <p>Se actualiza desde la base local y webhooks Retell.</p>
            </div>
            <span className="panelBadge">
              <BarChart3 size={14} /> Tiempo real
            </span>
          </div>
          <div className="chart">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid stroke="#E5E7EB" strokeDasharray="4 4" vertical={false} />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: "#5F6673", fontSize: 12 }} />
                <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{ fill: "#5F6673", fontSize: 12 }} />
                <Tooltip cursor={{ fill: "rgba(0, 51, 102, 0.06)" }} />
                <Bar dataKey="value" fill="#003366" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="panel selectedPanel">
          <div className="panelHeader">
            <h2>Cliente seleccionado</h2>
          </div>
          {selectedCustomer ? (
            <div className="customerFocus">
              <div>
                <strong>{selectedCustomer.preferred_name}</strong>
                <span>
                  {selectedCustomer.segment} · termina {selectedCustomer.phone_last4 ?? "----"}
                </span>
              </div>
              <dl>
                <div>
                  <dt>Producto</dt>
                  <dd>{selectedCustomer.obligations[0]?.product_type ?? "Sin obligación"}</dd>
                </div>
                <div>
                  <dt>Vence</dt>
                  <dd>
                    {selectedCustomer.obligations[0]
                      ? `${selectedCustomer.obligations[0].next_due_date} · ${dueLabel(
                          selectedCustomer.obligations[0].days_to_due
                        )}`
                      : "N/A"}
                  </dd>
                </div>
                <div>
                  <dt>Monto</dt>
                  <dd>
                    {selectedCustomer.obligations[0]?.currency} {selectedCustomer.obligations[0]?.amount_due}
                  </dd>
                </div>
                <div>
                  <dt>Ventana permitida</dt>
                  <dd>{selectedCustomer.preferred_call_window ?? "Sin contacto"}</dd>
                </div>
                <div>
                  <dt>Consentimiento</dt>
                  <dd>{consentLabel(selectedCustomer.consent_status)}</dd>
                </div>
              </dl>
              {selectedCustomer.consent_status !== "OPTED_IN" && !selectedCustomer.do_not_call && (
                <p className="inlineWarning">
                  <AlertTriangle size={14} /> Sin consentimiento confirmado. Verificá antes de llamar.
                </p>
              )}
              <div className="callActions">
                {webCallStatus === "live" ? (
                  <button className="endCall" onClick={onStopCall}>
                    <PhoneOff size={17} />
                    Finalizar llamada
                  </button>
                ) : (
                  <button
                    onClick={() => onStartWebCall(selectedCustomer)}
                    disabled={loading || selectedCustomer.do_not_call || webCallStatus === "connecting"}
                  >
                    <Mic size={17} />
                    {webCallStatus === "connecting" ? "Conectando con Sofía…" : "Iniciar llamada web"}
                  </button>
                )}
                {webCallStatus === "live" && (
                  <button className="audioButton" onClick={onPlayAudio}>
                    Activar audio
                  </button>
                )}
                <button
                  className="audioButton"
                  onClick={() => onSchedule(selectedCustomer)}
                  disabled={loading || selectedCustomer.do_not_call || webCallStatus === "live"}
                >
                  <PhoneCall size={17} />
                  Programar llamada telefónica
                </button>
              </div>
              <p className="callStatus" role="status">
                {webCallStatus === "live"
                  ? "Llamada activa. Use su micrófono y altavoces."
                  : "Llamada web: WebRTC del navegador, sin SIP trunk. La llamada telefónica encola un trabajo para el worker."}
              </p>
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
            <span className="panelBadge">
              <UsersRound size={14} /> {data.customers.length}
            </span>
          </div>
          <div className="list">
            {data.customers.map((customer) => (
              <button
                className={customer.id === selectedCustomer?.id ? "row selected" : "row"}
                key={customer.id}
                onClick={() => onSelect(customer.id)}
              >
                <span>
                  <strong>{customer.preferred_name}</strong>
                  <small>
                    {customer.external_ref}
                    {customer.obligations[0] ? ` · ${dueLabel(customer.obligations[0].days_to_due)}` : ""}
                  </small>
                </span>
                <em className={customer.do_not_call ? "statusBadge danger" : "statusBadge neutral"}>
                  {customer.do_not_call ? "No llamar" : customer.segment}
                </em>
              </button>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panelHeader">
            <h2>Cola</h2>
            <span className="panelBadge">
              <Clock3 size={14} /> {data.jobs.length}
            </span>
          </div>
          <div className="list">
            {data.jobs.map((job) => (
              <div className="row" key={job.id}>
                <span>
                  <strong>{job.customer_name}</strong>
                  <small>{new Date(job.scheduled_at).toLocaleString()}</small>
                </span>
                <em className="statusBadge warning">{job.status}</em>
              </div>
            ))}
            {data.jobs.length === 0 && <p className="muted">Sin trabajos encolados.</p>}
          </div>
        </div>

        <div className="panel">
          <div className="panelHeader">
            <h2>Llamadas</h2>
            <span className="panelBadge">
              <PhoneCall size={14} /> {data.calls.length}
            </span>
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
            {data.calls.length === 0 && <p className="muted">Todavía no hay llamadas registradas.</p>}
          </div>
        </div>
      </section>
    </>
  );
}

function CustomersTab({
  customers,
  selectedCustomer,
  onSelect
}: {
  customers: Customer[];
  selectedCustomer: Customer | undefined;
  onSelect: (id: string) => void;
}) {
  if (customers.length === 0) {
    return (
      <div className="panel">
        <p className="muted">Ejecuta el seed para cargar clientes.</p>
      </div>
    );
  }

  return (
    <>
      <div className="panel">
        <div className="panelHeader">
          <div>
            <h2>Cartera</h2>
            <p>Seleccioná una fila para ver obligaciones y opciones de asistencia.</p>
          </div>
          <span className="panelBadge">
            <UsersRound size={14} /> {customers.length}
          </span>
        </div>
        <div className="tableScroll">
          <table className="dataTable">
            <thead>
              <tr>
                <th>Cliente</th>
                <th>Nacimiento</th>
                <th>Segmento</th>
                <th>Contacto</th>
                <th>Consentimiento</th>
                <th>Próximo vencimiento</th>
                <th>Monto</th>
                <th>Puntualidad</th>
                <th>Última llamada</th>
              </tr>
            </thead>
            <tbody>
              {customers.map((customer) => {
                const next = nextObligation(customer);
                return (
                  <tr
                    key={customer.id}
                    className={customer.id === selectedCustomer?.id ? "selectedRow" : undefined}
                    onClick={() => onSelect(customer.id)}
                  >
                    <td>
                      <strong>{customer.preferred_name}</strong>
                      <small>
                        {customer.external_ref} · {customer.cohort === "TREATMENT" ? "llamado" : "control"}
                      </small>
                    </td>
                    <td>
                      <strong>{customer.birth_year}</strong>
                      {/* Solo se guarda el anio: la edad es aproximada por diseno. */}
                      <small>~{approximateAge(customer.birth_year)} años</small>
                    </td>
                    <td>
                      <span className="statusBadge neutral">{customer.segment}</span>
                    </td>
                    <td>
                      <strong>•••• {customer.phone_last4 ?? "----"}</strong>
                      <small>{customer.preferred_call_window ?? "sin ventana"}</small>
                    </td>
                    <td>
                      <span className={`statusBadge ${consentTone(customer)}`}>
                        {customer.do_not_call ? "No llamar" : consentLabel(customer.consent_status)}
                      </span>
                    </td>
                    <td>
                      {next ? (
                        <>
                          <strong>{next.next_due_date}</strong>
                          <small className={next.days_to_due <= 3 ? "urgent" : undefined}>{dueLabel(next.days_to_due)}</small>
                        </>
                      ) : (
                        <small>Sin obligación</small>
                      )}
                    </td>
                    <td>
                      {next ? (
                        <strong>
                          {next.currency} {next.amount_due}
                        </strong>
                      ) : (
                        <small>—</small>
                      )}
                    </td>
                    <td>{punctuality(customer)}</td>
                    <td>
                      {customer.last_call_at ? (
                        <>
                          <strong>{customer.last_call_outcome}</strong>
                          <small>{new Date(customer.last_call_at).toLocaleDateString()}</small>
                        </>
                      ) : (
                        <small>Nunca</small>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {selectedCustomer && (
        <div className="panel">
          <div className="panelHeader">
            <div>
              <h2>{selectedCustomer.preferred_name}</h2>
              <p>
                {selectedCustomer.external_ref} · {selectedCustomer.timezone} · idioma {selectedCustomer.language}
              </p>
            </div>
            <span className="panelBadge">
              <Cake size={14} /> {selectedCustomer.birth_year}
            </span>
          </div>
          <div className="obligationGrid">
            {selectedCustomer.obligations.map((obligation) => (
              <article className="obligationCard" key={obligation.id}>
                <header>
                  <strong>{obligation.product_type}</strong>
                  <span className={obligation.days_to_due <= 3 ? "statusBadge warning" : "statusBadge neutral"}>
                    {dueLabel(obligation.days_to_due)}
                  </span>
                </header>
                <dl>
                  <div>
                    <dt>
                      <CalendarDays size={13} /> Vence
                    </dt>
                    <dd>{obligation.next_due_date}</dd>
                  </div>
                  <div>
                    <dt>Monto</dt>
                    <dd>
                      {obligation.currency} {obligation.amount_due}
                    </dd>
                  </div>
                  <div>
                    <dt>Estado</dt>
                    <dd>{obligation.status}</dd>
                  </div>
                  <div>
                    <dt>Pagos puntuales</dt>
                    <dd>
                      {obligation.total_payments > 0
                        ? `${obligation.on_time_payments}/${obligation.total_payments}`
                        : "sin medición"}
                    </dd>
                  </div>
                  <div>
                    <dt>Reprogramable</dt>
                    <dd>
                      {obligation.reschedule_eligible
                        ? `${obligation.earliest_new_date ?? "?"} → ${obligation.latest_new_date ?? "?"}`
                        : "No elegible"}
                    </dd>
                  </div>
                  <div>
                    <dt>Seguro de desempleo</dt>
                    <dd>{obligation.unemployment_insurance_active ? "Activo" : "No"}</dd>
                  </div>
                </dl>
              </article>
            ))}
            {selectedCustomer.obligations.length === 0 && <p className="muted">Este cliente no tiene obligaciones.</p>}
          </div>
        </div>
      )}
    </>
  );
}

function CallsTab({ jobs, calls }: { jobs: CallJob[]; calls: Call[] }) {
  return (
    <>
      <div className="panel">
        <div className="panelHeader">
          <div>
            <h2>Cola del worker</h2>
            <p>Trabajos encolados, intentos realizados y el último error del proveedor.</p>
          </div>
          <span className="panelBadge">
            <ListChecks size={14} /> {jobs.length}
          </span>
        </div>
        <div className="tableScroll">
          <table className="dataTable">
            <thead>
              <tr>
                <th>Cliente</th>
                <th>Producto</th>
                <th>Programada</th>
                <th>Estado</th>
                <th>Intentos</th>
                <th>Último error</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td>
                    <strong>{job.customer_name}</strong>
                  </td>
                  <td>{job.obligation_product}</td>
                  <td>{new Date(job.scheduled_at).toLocaleString()}</td>
                  <td>
                    <span className="statusBadge warning">{job.status}</span>
                  </td>
                  <td>{job.attempt_count}</td>
                  <td className={job.last_error ? "errorCell" : undefined}>{job.last_error ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {jobs.length === 0 && <p className="muted">Sin trabajos encolados.</p>}
        </div>
      </div>

      <div className="panel">
        <div className="panelHeader">
          <div>
            <h2>Llamadas</h2>
            <p>Resultado, sentimiento, grabación y transcripción de cada conversación.</p>
          </div>
          <span className="panelBadge">
            <PhoneCall size={14} /> {calls.length}
          </span>
        </div>
        <div className="callList">
          {calls.map((call) => (
            <article className="callDetail" key={call.id}>
              <header>
                <div>
                  <strong>{call.customer_name}</strong>
                  <small>{new Date(call.created_at).toLocaleString()}</small>
                </div>
                <div className="badgeRow">
                  <span className="statusBadge neutral">{call.status}</span>
                  <span className={call.outcome === "BLOCKED_BY_ALLOWLIST" ? "statusBadge danger" : "statusBadge warning"}>
                    {call.outcome}
                  </span>
                  {call.sentiment && <span className="statusBadge neutral">{call.sentiment}</span>}
                </div>
              </header>
              <p>{call.summary ?? "Sin resumen todavía."}</p>
              {call.recording_url && <audio controls preload="none" src={call.recording_url} />}
              {call.transcript && (
                <details>
                  <summary>
                    <FileText size={13} /> Ver transcripción
                  </summary>
                  <pre>{call.transcript}</pre>
                </details>
              )}
            </article>
          ))}
          {calls.length === 0 && <p className="muted">Todavía no hay llamadas registradas.</p>}
        </div>
      </div>
    </>
  );
}

function RetellTab({ executions, events }: { executions: ToolExecution[]; events: WebhookEvent[] }) {
  return (
    <>
      <div className="panel">
        <div className="panelHeader">
          <div>
            <h2>Funciones invocadas por el agente</h2>
            <p>Evidencia de que la información financiera se consultó después de verificar identidad.</p>
          </div>
          <span className="panelBadge">
            <Wrench size={14} /> {executions.length}
          </span>
        </div>
        <div className="tableScroll">
          <table className="dataTable">
            <thead>
              <tr>
                <th>Función</th>
                <th>Llamada</th>
                <th>Inicio</th>
                <th>Duración</th>
                <th>Estado</th>
                <th>Petición (redactada)</th>
              </tr>
            </thead>
            <tbody>
              {executions.map((execution) => (
                <tr key={execution.id}>
                  <td>
                    <strong>{execution.tool_name}</strong>
                  </td>
                  <td>
                    <small>{execution.retell_call_id ?? "—"}</small>
                  </td>
                  <td>{new Date(execution.started_at).toLocaleString()}</td>
                  <td>{execution.duration_ms} ms</td>
                  <td>
                    <span className={execution.status === "OK" ? "statusBadge neutral" : "statusBadge danger"}>
                      {execution.error_code ?? execution.status}
                    </span>
                  </td>
                  <td>
                    <code>{JSON.stringify(execution.request_redacted)}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {executions.length === 0 && <p className="muted">El agente todavía no invocó ninguna función.</p>}
        </div>
      </div>

      <div className="panel">
        <div className="panelHeader">
          <div>
            <h2>Webhooks recibidos</h2>
            <p>Eventos que Retell envió al backend, con su estado de procesamiento.</p>
          </div>
          <span className="panelBadge">
            <Webhook size={14} /> {events.length}
          </span>
        </div>
        <div className="tableScroll">
          <table className="dataTable">
            <thead>
              <tr>
                <th>Evento</th>
                <th>Llamada</th>
                <th>Recibido</th>
                <th>Procesado</th>
                <th>Estado</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id}>
                  <td>
                    <strong>{event.event_type}</strong>
                  </td>
                  <td>
                    <small>{event.retell_call_id ?? "—"}</small>
                  </td>
                  <td>{new Date(event.received_at).toLocaleString()}</td>
                  <td>{event.processed_at ? new Date(event.processed_at).toLocaleString() : "—"}</td>
                  <td>
                    <span className={event.error ? "statusBadge danger" : "statusBadge neutral"}>{event.status}</span>
                  </td>
                  <td className={event.error ? "errorCell" : undefined}>{event.error ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {events.length === 0 && (
            <p className="muted">
              <Activity size={13} /> Sin webhooks todavía. Llegan cuando Retell cierra una llamada.
            </p>
          )}
        </div>
      </div>
    </>
  );
}

function nextObligation(customer: Customer): Obligation | undefined {
  // El backend no ordena las obligaciones: la relevante es la que vence antes,
  // no la primera que devolvio la base.
  return [...customer.obligations].sort((a, b) => a.days_to_due - b.days_to_due)[0];
}

function approximateAge(birthYear: number) {
  // Solo se almacena el anio de nacimiento, asi que esto tiene +-1 anio de
  // error segun si el cliente ya cumplio anios. Se muestra con "~" a proposito.
  return new Date().getFullYear() - birthYear;
}

function dueLabel(days: number) {
  if (days === 0) return "vence hoy";
  if (days < 0) return `vencido hace ${Math.abs(days)} d`;
  return `en ${days} d`;
}

function consentLabel(status: string | null) {
  if (status === "OPTED_IN") return "Opt-in";
  if (status === "OPTED_OUT") return "Opt-out";
  return status ?? "Sin contacto";
}

function consentTone(customer: Customer) {
  if (customer.do_not_call || customer.consent_status === "OPTED_OUT") return "danger";
  return customer.consent_status === "OPTED_IN" ? "neutral" : "warning";
}

function punctuality(customer: Customer) {
  const onTime = customer.obligations.reduce((total, item) => total + item.on_time_payments, 0);
  const total = customer.obligations.reduce((sum, item) => sum + item.total_payments, 0);
  // Sin ciclos cargados es "sin medicion", no 0%.
  if (total === 0) return <small>sin medición</small>;
  const rate = Math.round((onTime / total) * 100);
  return (
    <>
      <strong className={rate < 70 ? "urgent" : undefined}>{rate}%</strong>
      <small>
        {onTime}/{total} ciclos
      </small>
    </>
  );
}

function formatRate(rate: number | null | undefined) {
  // null viene del backend cuando no hay resultados de pago cargados: "sin
  // medicion" no es lo mismo que "nadie pago".
  if (rate === null || rate === undefined) return "—";
  return `${Math.round(rate * 100)}%`;
}

function Metric({
  icon,
  label,
  value,
  tone
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  tone: string;
}) {
  return (
    <article className={`metric ${tone}`}>
      <div>{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}
