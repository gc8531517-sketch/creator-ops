const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const storage = {};
let listener;
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../extension/background.js'), 'utf8'), {
  URL, Set, Date,
  chrome: { runtime: { onMessage: { addListener(fn) { listener = fn; } } },
    storage: { local: { async get(key) { return {[key]: storage[key]}; }, async set(v) { Object.assign(storage, v); } } } }
});
async function claim(jobId, url) {
  return await new Promise(resolve => listener({type: 'claim_export_job', jobId}, {url}, resolve));
}
(async () => {
  const job = 'synthetic_job_1';
  const url = `https://creator.douyin.com/creator-micro/content/manage?codex_douyin_export_job=${job}`;
  assert.equal((await claim(job, 'https://example.com')).reason, 'untrusted_sender');
  assert.equal((await claim(job, url)).ok, true);
  assert.equal((await claim(job, url)).reason, 'already_claimed');
  assert.equal((await claim('different_job', url)).reason, 'untrusted_sender');
  console.log('background sender and duplicate-claim tests passed');
})().catch(e => { console.error(e); process.exitCode = 1; });
