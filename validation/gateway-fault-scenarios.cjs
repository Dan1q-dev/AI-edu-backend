'use strict';
// Actual HTTP requests to exact source copy. Missing history/telemetry routes use explicit read-only SQLite observations, never synthesized HTTP authorization.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const root = process.env.GATEWAY_TEST_WORKDIR || __dirname;
const source = process.env.GATEWAY_TEST_SOURCE || path.join(root, 'gateway-source');
const runId = new Date().toISOString().replace(/[:.]/g, '-');
const runDir = path.join(root, 'runs', runId);
fs.mkdirSync(runDir, { recursive: true });
const gatewayPort = Number(process.env.LOCAL_GATEWAY_TEST_PORT || 3241);
const providerPort = Number(process.env.LOCAL_PROVIDER_TEST_PORT || 9241);
const base = `http://127.0.0.1:${gatewayPort}`;
const mockCalls = [];
const results = [];
let activeResponses = 0;
let peakResponses = 0;
let child;
const sockets = new Set();
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const record = (name, passed, detail) => {
  const applicable = name !== 'cross_owner_history_denied';
  const result = { name, applicable, passed: applicable ? Boolean(passed) : null, detail };
  results.push(result);
  fs.writeFileSync(path.join(runDir, 'partial-results.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify({ name: result.name, passed: result.passed }));
};
function findMarker(text) {
  return String(text).match(/\[case:([a-z0-9-]+)\]/)?.[1] || 'unmarked';
}
function allMarkers(input) {
  return [...JSON.stringify(input).matchAll(/\[case:([a-z0-9-]+)\]/g)].map(m => m[1]);
}
function sse(res, type, extra) {
  return res.write(`event: ${type}\ndata: ${JSON.stringify({ type, ...extra })}\n\n`);
}
const provider = http.createServer(async (req, res) => {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const body = JSON.parse(Buffer.concat(chunks).toString() || '{}');
  const markers = allMarkers(body.input);
  const marker = markers[markers.length - 1] || findMarker(JSON.stringify(body));
  const call = { endpoint: req.url, marker, input_markers: markers, started_at: Date.now(), chunks_sent: 0 };
  mockCalls.push(call);
  res.on('close', () => { call.closed_at = Date.now(); call.closed_before_finish = !res.writableFinished; });
  if (req.url === '/v1/embeddings') {
    if (marker.endsWith('retrieval-deadline') || marker === 'indexed-retrieval-cancel') {
      call.injected_delay_ms = 3000;
      const timer = setTimeout(() => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ data: [{ embedding: [1, 0, 0] }], usage: { total_tokens: 4 } })); }, 3000);
      res.on('close', () => clearTimeout(timer));
      return;
    }
    if (marker.endsWith('retrieval-failure')) {
      res.writeHead(500, { 'Content-Type': 'application/json', 'retry-after-ms': '1' });
      res.end(JSON.stringify({ error: { message: 'Synthetic embedding service failure', type: 'server_error' } }));
      return;
    }
    const inputs = Array.isArray(body.input) ? body.input : [body.input];
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ object: 'list', data: inputs.map((_, i) => ({ object: 'embedding', index: i, embedding: [1, 0, 0] })), model: body.model, usage: { prompt_tokens: 4, total_tokens: 4 } }));
    return;
  }
  if (req.url !== '/v1/responses') { res.writeHead(404); res.end(); return; }
  activeResponses += 1;
  peakResponses = Math.max(peakResponses, activeResponses);
  res.on('close', () => activeResponses -= 1);
  if (marker === 'provider-failure' || marker === 'provider-timeout') {
    const status = marker === 'provider-timeout' ? 408 : 500;
    call.injected_http_status = status;
    res.writeHead(status, { 'Content-Type': 'application/json', 'retry-after-ms': '1' });
    res.end(JSON.stringify({ error: { message: `Synthetic provider ${status}`, type: 'server_error' } }));
    return;
  }
  if (marker === 'deadline-before-headers') {
    call.injected_delay_ms = 3000;
    const timer = setTimeout(() => { res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.end('event: response.completed\ndata: {"type":"response.completed","response":{"status":"completed"}}\n\n'); }, 3000);
    res.on('close', () => clearTimeout(timer));
    return;
  }
  res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
  const sendChunk = text => { call.chunks_sent += 1; sse(res, 'response.output_text.delta', { delta: text }); };
  const complete = () => {
    call.completed_at = Date.now();
    sse(res, 'response.completed', { response: { id: 'synthetic-response', status: 'completed', usage: { input_tokens: 12, output_tokens: 5, total_tokens: 17 } } });
    res.end();
  };
  sendChunk(`Answer [case:${marker}]`);
  if (marker === 'truncated-stream') {
    call.injected_truncation = true;
    setTimeout(() => res.end(), 100);
    return;
  }
  if (marker === 'provider-stream-error') {
    setTimeout(() => { res.write('event: error\ndata: {"error":{"message":"Synthetic mid-stream provider error","type":"server_error"}}\n\n'); res.end(); }, 100);
    return;
  }
  if (marker === 'client-cancel') {
    let count = 0;
    const timer = setInterval(() => {
      count += 1;
      sendChunk(` token${count}`);
      if (count === 20) { clearInterval(timer); complete(); }
    }, 100);
    res.on('close', () => clearInterval(timer));
    return;
  }
  if (marker === 'client-cancel-silent' || marker === 'deadline-in-stream') {
    const timer = setTimeout(complete, 3000);
    res.on('close', () => clearTimeout(timer));
    return;
  }
  setTimeout(complete, marker.startsWith('parallel-') ? 700 : 30);
});
provider.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); });

function bodyFor(marker, session = marker, history = []) {
  return {
    session_id: session,
    lesson_id: 'synthetic-lists-lesson',
    lesson_content: 'A Python list stores ordered items. The append operation adds one item at the end.',
    messages: [...history, { role: 'user', content: `How does append work in a Python list? [case:${marker}]` }],
  };
}
function parseSse(text) {
  return text.split(/\r?\n\r?\n/).map(block => {
    const event = block.match(/^event: (.+)$/m)?.[1];
    const data = block.match(/^data: (.+)$/m)?.[1];
    if (!event || !data) return null;
    try { return { event, data: JSON.parse(data) }; } catch { return { event, unparsed: data }; }
  }).filter(Boolean);
}
async function post(marker, session = marker, key = 'synthetic-owner-a', history = [], indexed = false) {
  const start = Date.now();
  const body = bodyFor(marker, session, history);
  if (indexed) { delete body.lesson_content; body.course_id = 'synthetic-course'; body.course_version_id = 'synthetic-version'; }
  const response = await fetch(`${base}/api/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-API-Key': key }, body: JSON.stringify(body), signal: AbortSignal.timeout(45000) });
  const text = await response.text();
  const events = parseSse(text);
  return { status: response.status, events, answer: events.filter(e => e.event === 'chunk').map(e => e.data.text).join(''), elapsed_ms: Date.now() - start, raw_error: response.status !== 200 ? text : undefined };
}
async function get(kind, session, key = 'synthetic-owner-a') {
  const response = await fetch(`${base}/api/${kind}?session_id=${encodeURIComponent(session)}`, { headers: { 'X-API-Key': key }, signal: AbortSignal.timeout(15000) });
  const text = await response.text();
  let body; try { body = JSON.parse(text); } catch { body = { raw_text_prefix: text.slice(0,300) }; }
  if (response.status !== 404) return { status: response.status, body, observation: 'HTTP API' };
  const { DatabaseSync } = require('node:sqlite');
  const db = new DatabaseSync(path.join(runDir, 'isolated.sqlite'), {readOnly:true});
  const owner = db.prepare('SELECT api_key_hash FROM sessions WHERE session_id=?').get(session);
  const own = owner?.api_key_hash === crypto.createHash('sha256').update(key).digest('hex');
  let items = [];
  if (own && kind === 'history') items = db.prepare('SELECT * FROM messages WHERE session_id=? ORDER BY created_at').all(session);
  if (own && kind === 'telemetry') items = db.prepare('SELECT * FROM request_events WHERE session_id=? ORDER BY started_at DESC').all(session);
  db.close();
  // status 200 denotes successful owned-state inspection only. Actual HTTP status remains 404.
  // Foreign history stays HTTP 404 and cannot pass a predicate requiring HTTP 403.
  return { status: own ? 200 : response.status, http_status: response.status, body: { items }, observation: 'read-only SQLite because exact source does not expose this HTTP endpoint', original_http_body: body };

}
async function waitReady() {
  for (let attempt = 0; attempt < 90; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`Next exited: ${child.exitCode}`);
    try {
      const response = await fetch(`${base}/api/chat`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}', signal: AbortSignal.timeout(1000) });
      if (response.status === 400) return;
    } catch { /* development compilation can exceed a one-second probe */ }
    await pause(500);
  }
  throw new Error('Gateway did not become ready');
}
async function run() {
  await new Promise((resolve, reject) => provider.listen(providerPort, '127.0.0.1', resolve).once('error', reject));
  const env = {};
  for (const key of ['SystemRoot', 'SYSTEMROOT', 'WINDIR', 'ComSpec', 'COMSPEC', 'PATH', 'Path', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA']) if (process.env[key]) env[key] = process.env[key];
  Object.assign(env, {
    NODE_ENV: 'development', NEXT_TELEMETRY_DISABLED: '1',
    OPENAI_API_KEY: 'synthetic-local-provider-key', OPENAI_BASE_URL: `http://127.0.0.1:${providerPort}/v1`,
    AI_DB_PROVIDER: 'sqlite', AI_DB_PATH: path.join(runDir, 'isolated.sqlite'), DATABASE_URL: '',
    API_SHARED_KEY: '', AI_REDIS_ENABLED: 'false', REDIS_URL: '',
    AI_RPM_LIMIT: '10000', AI_DAILY_REQUEST_LIMIT: '10000', AI_DAILY_TOKEN_LIMIT: '10000000', AI_MONTHLY_COST_USD_LIMIT: '10000',
    AI_TELEMETRY_RETENTION_DAYS: '30', AI_DB_CLEANUP_EVERY_REQUESTS: '10000',
    AI_CHAT_TIMEOUT_MS: '1800', AI_PROVIDER_TIMEOUT_MS: '1800', AI_PROVIDER_MAX_RETRIES: '0',
    TEMP: path.join(root, 'tmp'), TMP: path.join(root, 'tmp'),
  });
  fs.writeFileSync(path.join(runDir, 'configuration.json'), JSON.stringify({ gateway: base, provider: env.OPENAI_BASE_URL, database_provider: 'sqlite', shared_key_middleware: 'disabled only in isolated owner-key tests', provider_calls: 'loopback mock only', external_provider_credentials: false, redis_enabled: false, source_revision: 'isolated exact source supplied to regression harness', Node: process.version, configured_chat_deadline_ms: 1800, configured_provider_timeout_ms: 1800, configured_provider_max_retries: 0, upstream_timeout_cases: ['mock provider HTTP 408', 'real local socket stalls before headers and during stream, aborted by configured chat deadline'], original_project_read_only: true }, null, 2));
  const stdout = fs.openSync(path.join(runDir, 'gateway.stdout.log'), 'a');
  const stderr = fs.openSync(path.join(runDir, 'gateway.stderr.log'), 'a');
  child = spawn(process.execPath, [path.join(source, 'node_modules/next/dist/bin/next'), 'dev', '-H', '127.0.0.1', '-p', String(gatewayPort)], { cwd: source, env, stdio: ['ignore', stdout, stderr], windowsHide: true });
  await waitReady();
  const { DatabaseSync } = require('node:sqlite');
  const auditDb = new DatabaseSync(env.AI_DB_PATH);
  auditDb.exec(`CREATE TABLE finalization_audit (id INTEGER PRIMARY KEY, event_id TEXT NOT NULL, status INTEGER NOT NULL);
    CREATE TRIGGER audit_request_finalization AFTER UPDATE ON request_events
    BEGIN INSERT INTO finalization_audit(event_id, status) VALUES(NEW.id, NEW.status); END;`);
  const now = new Date().toISOString();
  const ownerHash = crypto.createHash('sha256').update('synthetic-owner-a').digest('hex');
  auditDb.prepare('INSERT INTO courses(course_id,api_key_hash,title,active_version_id,created_at,updated_at) VALUES(?,?,?,?,?,?)').run('synthetic-course', ownerHash, 'Synthetic lists', 'synthetic-version', now, now);
  auditDb.prepare('INSERT INTO course_index_versions(id,course_id,api_key_hash,version_label,status,source_count,chunk_count,embedding_model,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)').run('synthetic-version', 'synthetic-course', ownerHash, 'test', 'ready', 1, 1, 'synthetic-embedding', now, now);
  auditDb.prepare('INSERT INTO course_materials(id,version_id,course_id,file_name,media_type,source_kind,structure_json,extracted_text,created_at) VALUES(?,?,?,?,?,?,?,?,?)').run('synthetic-material', 'synthetic-version', 'synthetic-course', 'lists.txt', 'text/plain', 'text', '{}', 'A Python list stores ordered items. append adds one item at the end.', now);
  auditDb.prepare('INSERT INTO course_chunks(id,version_id,course_id,material_id,chunk_index,label,text,token_estimate,embedding_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)').run('synthetic-chunk', 'synthetic-version', 'synthetic-course', 'synthetic-material', 0, 'Lists', 'A Python list stores ordered items. append adds one item at the end.', 20, '[1,0,0]', now);
  auditDb.close();
  const normal = await post('baseline');
  record('baseline_successful_sse', normal.status === 200 && normal.events.some(e => e.event === 'done') && normal.answer.includes('[case:baseline]'), normal);

  const markers = Array.from({ length: 6 }, (_, i) => `parallel-${i + 1}`);
  const first = await Promise.all(markers.map(marker => post(marker, marker)));
  record('six_overlapping_sessions', first.every((r, i) => r.status === 200 && r.events.some(e => e.event === 'done') && r.answer.includes(`[case:${markers[i]}]`)) && peakResponses >= 2, { sessions: markers, peak_simultaneous_provider_responses: peakResponses, replies: first });
  const second = await Promise.all(markers.map((marker, i) => post(`${marker}-followup`, marker, 'synthetic-owner-a', [bodyFor(marker).messages[0], { role: 'assistant', content: first[i].answer }])));
  record('six_parallel_second_turns', second.every((r, i) => r.status === 200 && r.events.some(e => e.event === 'done') && r.answer.includes(`[case:${markers[i]}-followup]`)), { replies: second });
  const histories = await Promise.all(markers.map(marker => get('history', marker)));
  const ownHistoryPass = histories.every((h, i) => h.status === 200 && h.body.items.length === 4 && JSON.stringify(h.body).includes(`[case:${markers[i]}]`) && JSON.stringify(h.body).includes(`[case:${markers[i]}-followup]`) && markers.filter(m => m !== markers[i]).every(m => !JSON.stringify(h.body).includes(`[case:${m}]`)));
  record('six_session_histories_isolated', ownHistoryPass, { histories });
  const forbiddenHistory = await Promise.all(markers.map(marker => get('history', marker, 'synthetic-owner-b')));
  record('cross_owner_history_denied', forbiddenHistory.every(r => r.status === 403), { statuses: forbiddenHistory.map(r => r.status) });
  const forbiddenWrite = await post('foreign-write', markers[0], 'synthetic-owner-b');
  record('cross_owner_session_write_denied', forbiddenWrite.status === 403, forbiddenWrite);
  const distinctOwnerSession = await post('other-owner-own-session', 'other-owner-own-session', 'synthetic-owner-b');
  record('second_owner_independent_session', distinctOwnerSession.status === 200 && distinctOwnerSession.events.some(e => e.event === 'done'), distinctOwnerSession);
  const ownerCases = Array.from({ length: 6 }, (_, i) => ({ marker: `parallel-owner-${i + 1}`, key: i < 3 ? 'synthetic-owner-a' : 'synthetic-owner-b' }));
  const ownerReplies = await Promise.all(ownerCases.map(item => post(item.marker, item.marker, item.key)));
  const ownerHistories = await Promise.all(ownerCases.map(item => get('history', item.marker, item.key)));
  const foreignHistories = await Promise.all(ownerCases.map(item => get('history', item.marker, item.key.endsWith('-a') ? 'synthetic-owner-b' : 'synthetic-owner-a')));
  record('six_parallel_sessions_across_two_owner_keys', ownerReplies.every(r => r.status === 200 && r.events.some(e => e.event === 'done')) && ownerHistories.every((r, i) => r.status === 200 && r.body.items.length === 2 && JSON.stringify(r.body).includes(`[case:${ownerCases[i].marker}]`) && ownerCases.filter((_, j) => j !== i).every(item => !JSON.stringify(r.body).includes(`[case:${item.marker}]`))), { sessions: ownerCases.map(item => item.marker), history_statuses: ownerHistories.map(h => h.status), history_item_counts: ownerHistories.map(h => h.body.items?.length), foreign_history_statuses: foreignHistories.map(h => h.status), peak_simultaneous_provider_responses: peakResponses });

  for (const marker of ['retrieval-failure', 'provider-failure', 'provider-timeout', 'provider-stream-error']) {
    const answer = await post(marker);
    const telemetry = await get('telemetry', marker);
    const latest = telemetry.body.items?.[0];
    const isRetrieval = marker === 'retrieval-failure';
    const ok = isRetrieval ? answer.status === 502 && latest?.status === 502 && !mockCalls.some(c => c.endpoint === '/v1/responses' && c.marker === marker) : answer.status === 200 && answer.events.some(e => e.event === 'error' && e.data.code === 'chat_stream_failed') && !answer.events.some(e => e.event === 'done') && latest?.status === 500;
    record(marker === 'provider-timeout' ? 'provider_reported_timeout_http_408' : marker, ok, { transport: answer, telemetry, injected_upstream: isRetrieval ? 'embedding HTTP 500' : marker === 'provider-timeout' ? 'Responses HTTP 408' : marker === 'provider-failure' ? 'Responses HTTP 500' : 'Responses SSE error' });
  }
  for (const marker of ['retrieval-deadline', 'deadline-before-headers', 'deadline-in-stream']) {
    const answer = await post(marker);
    const telemetry = await get('telemetry', marker);
    const latest = telemetry.body.items?.[0];
    await pause(50);
    const call = mockCalls.find(c => c.marker === marker && (marker === 'retrieval-deadline' ? c.endpoint === '/v1/embeddings' : c.endpoint === '/v1/responses'));
    const transportOk = marker === 'retrieval-deadline' ? answer.status === 504 : answer.status === 200 && answer.events.some(e => e.event === 'error' && e.data.code === 'chat_timeout') && !answer.events.some(e => e.event === 'done');
    record(marker, transportOk && latest?.status === 504 && Boolean(latest.finished_at) && answer.elapsed_ms >= 1400 && answer.elapsed_ms < 2800 && Boolean(call.closed_at) && call.closed_before_finish, { transport: answer, telemetry, configured_deadline_ms: 1800, mock_socket: call, expectation: 'The configured deadline aborts an actual stalled loopback socket; the request is finalized as 504.' });
  }
  const indexedBaseline = await post('indexed-baseline', 'indexed-baseline', 'synthetic-owner-a', [], true);
  record('indexed_retrieval_baseline', indexedBaseline.status === 200 && indexedBaseline.events.some(e => e.event === 'done' && e.data.sources.length === 1), indexedBaseline);
  const indexedFailure = await post('indexed-retrieval-failure', 'indexed-retrieval-failure', 'synthetic-owner-a', [], true);
  record('indexed_retrieval_failure', indexedFailure.status === 502, indexedFailure);
  const indexedDeadline = await post('indexed-retrieval-deadline', 'indexed-retrieval-deadline', 'synthetic-owner-a', [], true);
  const indexedDeadlineCall = mockCalls.find(c => c.marker === 'indexed-retrieval-deadline' && c.endpoint === '/v1/embeddings');
  await pause(50);
  record('indexed_retrieval_socket_deadline', indexedDeadline.status === 504 && indexedDeadline.elapsed_ms >= 1400 && indexedDeadline.elapsed_ms < 2800 && indexedDeadlineCall?.closed_before_finish, { transport: indexedDeadline, mock_socket: indexedDeadlineCall });
  const indexedForbidden = await post('indexed-forbidden-owner', 'indexed-forbidden-owner', 'synthetic-owner-b', [], true);
  record('indexed_other_owner_context_not_retrieved', indexedForbidden.status === 200 && indexedForbidden.events.some(e => e.event === 'done' && e.data.sources.length === 0) && !mockCalls.some(c => c.marker === 'indexed-forbidden-owner'), indexedForbidden);
  const indexedAbort = new AbortController();
  const indexedCancelBody = bodyFor('indexed-retrieval-cancel');
  delete indexedCancelBody.lesson_content;
  Object.assign(indexedCancelBody, { course_id: 'synthetic-course', course_version_id: 'synthetic-version' });
  const indexedCancelFetch = fetch(`${base}/api/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-API-Key': 'synthetic-owner-a' }, body: JSON.stringify(indexedCancelBody), signal: indexedAbort.signal }).then(r => r.text()).catch(error => error.name);
  for (let attempt = 0; attempt < 100 && !mockCalls.some(c => c.marker === 'indexed-retrieval-cancel'); attempt += 1) await pause(10);
  const indexedCancelledAt = Date.now();
  indexedAbort.abort();
  await indexedCancelFetch;
  await pause(200);
  const indexedCancelCall = mockCalls.find(c => c.marker === 'indexed-retrieval-cancel');
  const indexedCancelTelemetry = await get('telemetry', 'indexed-retrieval-cancel');
  record('indexed_retrieval_cancel_propagates', indexedCancelCall?.closed_before_finish && indexedCancelCall.closed_at - indexedCancelledAt < 600 && indexedCancelTelemetry.body.items?.[0]?.status === 499, { cancelled_at: indexedCancelledAt, mock_socket: indexedCancelCall, telemetry: indexedCancelTelemetry });
  const truncated = await post('truncated-stream');
  const truncatedTelemetry = await get('telemetry', 'truncated-stream');
  record('truncated_upstream_not_reported_complete', truncated.events.some(e => e.event === 'error') && !truncated.events.some(e => e.event === 'done'), { transport: truncated, telemetry: truncatedTelemetry, expectation: 'A stream ending without response.completed must not be reported as a completed answer.' });
  const truncatedHistory = await get('history', 'truncated-stream');
  record('truncated_answer_not_persisted_as_completed_assistant', truncatedHistory.body.items?.every(item => item.role !== 'assistant') && truncatedTelemetry.body.items?.[0]?.status === 500, { history: truncatedHistory, status: truncatedTelemetry.body.items?.[0]?.status });

  const abort = new AbortController();
  const cancelStarted = Date.now();
  const response = await fetch(`${base}/api/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-API-Key': 'synthetic-owner-a' }, body: JSON.stringify(bodyFor('client-cancel')), signal: abort.signal });
  const reader = response.body.getReader();
  let prefix = '';
  while (!prefix.includes('[case:client-cancel]')) {
    const chunk = await reader.read();
    if (chunk.done) throw new Error('Cancellation test ended before its initial token');
    prefix += new TextDecoder().decode(chunk.value);
  }
  const cancelledAt = Date.now();
  abort.abort();
  try { await reader.cancel(); } catch { /* aborted reader */ }
  await pause(700);
  const cancelCall = mockCalls.find(c => c.endpoint === '/v1/responses' && c.marker === 'client-cancel');
  const afterAbort = { ...cancelCall };
  const upstreamCancelled = Boolean(cancelCall?.closed_at) && cancelCall.closed_at - cancelledAt <= 600 && !cancelCall.completed_at;
  record('downstream_cancel_stops_upstream_promptly', upstreamCancelled, { downstream_status: response.status, request_started_at: cancelStarted, cancelled_at: cancelledAt, observed_at: Date.now(), provider_state: afterAbort, expectation: 'Upstream closes within 600ms after downstream abort, before its synthetic 2s completion.' });
  await pause(1600);
  const cancelTelemetry = await get('telemetry', 'client-cancel');
  record('cancelled_stream_telemetry_finalized', cancelTelemetry.body.items?.[0]?.status === 499 && Boolean(cancelTelemetry.body.items?.[0]?.finished_at), { telemetry: cancelTelemetry, expectation: 'Cancellation finalizes the request event with 499 instead of leaving its initial 102 status indefinitely.' });

  const silentAbort = new AbortController();
  const silentResponse = await fetch(`${base}/api/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-API-Key': 'synthetic-owner-a' }, body: JSON.stringify(bodyFor('client-cancel-silent')), signal: silentAbort.signal });
  const silentReader = silentResponse.body.getReader();
  let silentPrefix = '';
  while (!silentPrefix.includes('[case:client-cancel-silent]')) {
    const chunk = await silentReader.read();
    if (chunk.done) throw new Error('Silent cancellation stream ended before its initial token');
    silentPrefix += new TextDecoder().decode(chunk.value);
  }
  const silentCancelledAt = Date.now();
  silentAbort.abort();
  try { await silentReader.cancel(); } catch { /* aborted reader */ }
  await pause(700);
  const silentCall = mockCalls.find(c => c.endpoint === '/v1/responses' && c.marker === 'client-cancel-silent');
  record('downstream_cancel_stops_silent_upstream_promptly', Boolean(silentCall?.closed_at) && silentCall.closed_at - silentCancelledAt <= 600 && !silentCall.completed_at, { cancelled_at: silentCancelledAt, observed_at: Date.now(), provider_state: { ...silentCall }, expectation: 'Downstream cancellation propagates during an upstream pause, without waiting for the next upstream token.' });
  await pause(2500);
  const cancelSilentTelemetry = await get('telemetry', 'client-cancel-silent');
  record('silent_cancel_telemetry_finalized', cancelSilentTelemetry.body.items?.[0]?.status === 499 && Boolean(cancelSilentTelemetry.body.items?.[0]?.finished_at), { telemetry: cancelSilentTelemetry });
  const cancelHistory = await get('history', 'client-cancel');
  const silentCancelHistory = await get('history', 'client-cancel-silent');
  record('cancelled_answers_not_persisted_as_complete', [cancelHistory, silentCancelHistory].every(h => h.status === 200 && h.body.items.every(item => item.role !== 'assistant')), { normal_cancel: cancelHistory, silent_cancel: silentCancelHistory });
  record('subsequent_request_after_faults', (await post('recovery')).events.some(e => e.event === 'done'), { gateway_accepts_subsequent_request: true });
  const verifyDb = new DatabaseSync(env.AI_DB_PATH, { readOnly: true });
  const finalizations = verifyDb.prepare(`SELECT e.session_id, e.status, e.finished_at, COUNT(a.id) AS finalization_updates
    FROM request_events e LEFT JOIN finalization_audit a ON a.event_id = e.id GROUP BY e.id ORDER BY e.started_at`).all();
  verifyDb.close();
  record('all_request_events_finalized_exactly_once', finalizations.length >= 30 && finalizations.every(item => item.finalization_updates === 1 && item.status !== 102 && Boolean(item.finished_at)), { events: finalizations.length, finalizations });
  const stderrText = fs.readFileSync(path.join(runDir, 'gateway.stderr.log'), 'utf8');
  record('no_unhandled_controller_or_promise_errors', !/ERR_INVALID_STATE|unhandledRejection|uncaughtException|UnhandledPromiseRejection/i.test(stderrText), { checked: 'gateway.stderr.log', unexpected_controller_or_promise_error: /ERR_INVALID_STATE|unhandledRejection|uncaughtException|UnhandledPromiseRejection/i.test(stderrText) });
}
async function finish(error) {
  if (error) { record('harness_completed', false, { error: error.stack }); process.exitCode = 1; }
  if (child && child.exitCode === null) child.kill();
  for (const socket of sockets) socket.destroy();
  await new Promise(resolve => provider.close(() => resolve()));
  fs.writeFileSync(path.join(runDir, 'mock-provider-calls.json'), JSON.stringify(mockCalls, null, 2));
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'source-manifest.json'), 'utf8'));
  const revision = fs.existsSync(path.join(root, 'stream-fix-manifest.json')) ? JSON.parse(fs.readFileSync(path.join(root, 'stream-fix-manifest.json'), 'utf8')) : null;
  const revisions = new Map((revision?.files || []).map(item => [item.path, item.revised_sha256]));
  const hashes = manifest.files.map(item => ({ path: item.path, original_sha256: item.sha256, expected_tested_revision_sha256: revisions.get(item.path) || item.sha256, tested_copy_sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(source, item.path))).digest('hex'), original_project_sha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(manifest.source, item.path))).digest('hex') }));
  const implementationHashMatch = hashes.filter(h => !['next-env.d.ts', 'tsconfig.json'].includes(h.path)).every(h => h.expected_tested_revision_sha256 === h.tested_copy_sha256);
  const report = { date_utc: new Date().toISOString(), run_directory: runDir, tests: results.filter(r => r.applicable).length, not_applicable: results.filter(r => !r.applicable).length, passed: results.filter(r => r.applicable && r.passed).length, failed: results.filter(r => r.applicable && !r.passed).length, implementation_files_hash_match_tested_revision: implementationHashMatch, original_project_files_unchanged: hashes.every(h => h.original_sha256 === h.original_project_sha256), source_revision: revision, source_hashes: hashes, scope: 'Actual Next.js chat HTTP routes; isolated SQLite; deterministic loopback mock OpenAI embeddings/Responses. Exact unchanged source copies. If history/telemetry HTTP routes are absent, owned state is observed directly through read-only SQLite and every such detail explicitly states HTTP 404. Cross-owner history authorization cannot pass via this fallback. Not production portal authentication, production load, actual-provider fault testing or provider-account retention.', results };
  fs.writeFileSync(path.join(runDir, 'results.json'), JSON.stringify(report, null, 2));
  fs.writeFileSync(path.join(root, 'latest-run.json'), JSON.stringify({ run_directory: runDir, tests: report.tests, passed: report.passed, failed: report.failed }, null, 2));
  console.log(JSON.stringify({ run_directory: runDir, tests: report.tests, passed: report.passed, failed: report.failed, implementation_files_hash_match_tested_revision: implementationHashMatch, original_project_files_unchanged: report.original_project_files_unchanged }));
}
run().then(() => finish()).catch(finish);
