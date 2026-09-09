'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { begin, finalize, hook, status, collect } = require('./lifecycle');
function fixture(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dispatch-lifecycle-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return { dir, put: (suffix, value) => fs.writeFileSync(path.join(dir, `T-1.${suffix}`), typeof value === 'string' ? value : JSON.stringify(value)) };
}
test('AGY blank and malformed response fail despite exit zero and absent PID', t => {
  const {dir, put} = fixture(t);
  put('agy.exitcode', '0');
  for (const value of ['', '{}', '{"response":"  "}', '{"response":{}}', 'null', '{broken']) {
    put('agy.json', value);
    assert.equal(status(dir, 'T-1').exit_code, 21);
    assert.equal(collect(dir, 'T-1').exit_code, 21);
  }
  put('agy.json', { response: 'A useful result' });
  assert.equal(status(dir, 'T-1').exit_code, 0);
});
test('Claude semantic failures override zero exit and success-looking prose', t => {
  const {dir, put} = fixture(t);
  put('exitcode', '0');
  put('json', { type: 'result', is_error: true, result: 'Something failed' });
  assert.equal(status(dir, 'T-1').exit_code, 1);
  put('json', { type: 'result', subtype: 'error_max_budget_usd', result: 'No budget' });
  assert.equal(status(dir, 'T-1').exit_code, 20);
  put('json', { type: 'result', api_error_status: 429, result: 'Quota' });
  assert.equal(status(dir, 'T-1').exit_code, 17);
  put('json', { type: 'result', subtype: 'success', result: 'Explained HTTP 429 and maximum budget behavior' });
  assert.equal(status(dir, 'T-1').exit_code, 0);
  put('result-missing', 'missing');
  assert.equal(status(dir, 'T-1').exit_code, 21);
});
test('required Bridge summary/status validated and incomplete work not successful', t => {
  const {dir, put} = fixture(t);
  put('run.json', { engine: 'claude', bridge_required: true });
  put('exitcode', '0');
  put('json', { type: 'result', result: 'Done' });
  for (const result of [null, {}, {status:'DONE',summary:' '}, {status:'invented',summary:'Okay'}]) {
    put('bridge.json', {result});
    assert.equal(status(dir, 'T-1').exit_code, 21);
  }
  put('bridge.json', {result: {status:'PARTIAL', summary:'Some progress'}});
  assert.equal(status(dir, 'T-1').exit_code, 22);
  put('bridge.json', {result: {status:'DONE', summary:'All done'}});
  assert.equal(status(dir, 'T-1').exit_code, 0);
});
test('final status precedes hook and preserves engine result on hook failure', t => {
  const {dir, put} = fixture(t);
  put('run.json', {run_id:'run-a',engine:'claude'});
  put('json', {type:'result',result:'Implemented changes'});
  assert.equal(finalize(dir, 'T-1', 0).exit_code, 0);
  assert.equal(status(dir, 'T-1').exit_code, 10);
  hook(dir, 'T-1', 7);
  const state = status(dir, 'T-1');
  assert.equal(state.exit_code, 24);
  assert.equal(state.engine_status, 'done');
  assert.match(collect(dir, 'T-1').report, /Implemented changes/);
  const disk = JSON.parse(fs.readFileSync(path.join(dir,'T-1.final-status.json'),'utf8'));
  assert.equal(disk.exit_code, 0);
  assert.equal(disk.hook.exit_code, 7);
});
test('pending hook becomes bounded failure and stale final cannot finish a new run', t => {
  const {dir, put} = fixture(t);
  put('run.json', {run_id:'new',engine:'claude',pid:999999999,process_identity:{start:'x'}});
  put('final-status.json', {run_id:'old',exit_code:0,status:'done'});
  assert.equal(status(dir, 'T-1').exit_code, 23);
  put('final-status.json', {run_id:'new',exit_code:0,status:'done',hook:{status:'pending'},completed_at:'2000-01-01T00:00:00Z'});
  assert.equal(status(dir, 'T-1').exit_code, 24);
});
test('checkpoint recovers last assistant even when final event is a tool event', t => {
  const {dir, put} = fixture(t);
  put('json', [JSON.stringify({type:'assistant', message:{content:[{type:'text',text:'Verified A; B still pending'}]}}), JSON.stringify({type:'user',message:{content:[{type:'tool_result',content:'ok'}]}}), '{truncated'].join('\n'));
  put('exitcode', '124');
  assert.equal(finalize(dir, 'T-1', 124).exit_code, 14);
  hook(dir, 'T-1', 0);
  assert.equal(collect(dir, 'T-1').exit_code, 14);
  assert.match(collect(dir, 'T-1').report, /Verified A; B still pending/);
  assert.match(fs.readFileSync(path.join(dir,'T-1.checkpoint.json'),'utf8'), /B still pending/);
});
test('bare legacy PID is unverified and invalid task identifiers rejected', t => {
  const {dir, put} = fixture(t);
  put('pid', String(process.pid));
  assert.equal(status(dir, 'T-1').exit_code, 23);
  assert.throws(() => status(dir, '../escape'));
});
test('AGY partial protocol is surfaced as partial', t => {
  const {dir, put} = fixture(t);
  put('agy.exitcode', '0'); put('agy.json', {response:'STATUS: BLOCKED\nMissing input'});
  assert.equal(status(dir,'T-1').exit_code,22);
});
test('new run has a unique sentinel and mismatched process start cannot be running', t => {
  const {dir, put} = fixture(t);
  const run = begin(dir,'T-1','claude',999999999);
  assert.match(run.run_id,/^[a-f0-9-]{36}$/);
  put('run.json',{...run,process_identity:{kind:'proc',pid:process.pid,start:'incorrect'}});
  assert.equal(status(dir,'T-1').exit_code,23);
});
