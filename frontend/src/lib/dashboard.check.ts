// Check del modo de falla que dejo el panel en blanco tras el merge del PR #15:
// el frontend nuevo ya estaba publicado y el backend viejo todavia no tenia
// /retell/tool-executions, asi que ese 404 tumbaba tambien metricas y cartera.
//
// Correr con:  npm run check   (node --experimental-strip-types)
import assert from "node:assert/strict";
import { emptyState, failedSections, mergeLoadResults, valueOf } from "./dashboard.ts";
import type { LoadState } from "./dashboard.ts";

const ok = <T,>(value: T): PromiseSettledResult<unknown> => ({ status: "fulfilled", value });
const fail = (reason: string): PromiseSettledResult<unknown> => ({ status: "rejected", reason: new Error(reason) });

const loaded: LoadState = {
  summary: { customers: 8 } as LoadState["summary"],
  customers: [{ id: "c1" }] as LoadState["customers"],
  jobs: [{ id: "j1" }] as LoadState["jobs"],
  calls: [{ id: "l1" }] as LoadState["calls"],
  toolExecutions: [{ id: "t1" }] as LoadState["toolExecutions"],
  webhookEvents: [{ id: "w1" }] as LoadState["webhookEvents"]
};

// 1. La falla real: solo fallan los dos endpoints de auditoria de Retell.
{
  const results = [
    ok(loaded.summary),
    ok(loaded.customers),
    ok(loaded.jobs),
    ok(loaded.calls),
    fail('{"detail":"Not Found"}'),
    fail('{"detail":"Not Found"}')
  ];
  const merged = mergeLoadResults(results, emptyState);

  assert.deepEqual(merged.summary, loaded.summary, "el resumen no debe caerse por un 404 de auditoria");
  assert.equal(merged.customers.length, 1, "la cartera no debe caerse por un 404 de auditoria");
  assert.equal(merged.jobs.length, 1);
  assert.equal(merged.calls.length, 1);
  assert.deepEqual(failedSections(results), ["las funciones del agente", "los webhooks"]);
}

// 2. Una seccion que falla conserva lo que ya estaba en pantalla.
{
  const results = [ok(loaded.summary), fail("timeout"), ok(loaded.jobs), ok(loaded.calls), ok([]), ok([])];
  const merged = mergeLoadResults(results, loaded);

  assert.equal(merged.customers.length, 1, "una recarga fallida no debe vaciar la tabla anterior");
  assert.deepEqual(failedSections(results), ["los clientes"]);
}

// 3. Todo bien: sin banner de error.
{
  const results = [ok(loaded.summary), ok(loaded.customers), ok(loaded.jobs), ok(loaded.calls), ok([]), ok([])];
  assert.deepEqual(failedSections(results), []);
  assert.deepEqual(mergeLoadResults(results, emptyState).customers, loaded.customers);
}

// 4. Caida total: no explota y nombra las seis secciones.
{
  const results = Array.from({ length: 6 }, () => fail("network"));
  assert.deepEqual(mergeLoadResults(results, emptyState), emptyState);
  assert.equal(failedSections(results).length, 6);
}

// 5. valueOf tolera un indice que no existe.
assert.deepEqual(valueOf(undefined, []), []);

console.log("dashboard.check: 5 comprobaciones OK");
