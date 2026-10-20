// Real Edge browser checks with intercepted synthesis/settings writes. No paid calls.
// Usage: node tests/browser-smoke.mjs http://127.0.0.1:8770
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, writeFile, rm} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const base = process.argv[2] || 'http://127.0.0.1:8770';
assert.match(base, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/);
const edgePath = process.env.EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const artifacts = path.join(root, '.playwright');
const [settings, catalog] = await Promise.all(['/api/settings', '/api/catalog'].map(async endpoint => {
  const response = await fetch(base + endpoint);
  assert.ok(response.ok, `${endpoint}: HTTP ${response.status}`);
  return response.json();
}));
for (const value of Object.values(settings.providers)) {
  value.configured = true;
  for (const key of Object.keys(value.fields)) value.fields[key] = true;
}
const vendor = id => {
  const item = catalog.providers.find(p => p.id === id);
  assert.ok(item, `${id} catalog exists`);
  return item;
};
const voicesFor = (id, model) => vendor(id).voices.filter(v => (!v.models || v.models.includes(model)) && (!v.regions || v.regions.includes(settings.providers[id].region)));
await mkdir(artifacts, {recursive: true});
const profile = await mkdtemp(path.join(artifacts, 'edge-'));
const edge = spawn(edgePath, ['--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-gpu', '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1', `--user-data-dir=${profile}`, 'about:blank'], {stdio: ['ignore', 'ignore', 'pipe']});
let socket;
const errors = [];
const requests = [];
const settingsWrites = [];
let failMini = false;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
try {
  const endpoint = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Edge did not expose DevTools within 15 seconds')), 15000);
    let stderr = '';
    edge.on('error', error => { clearTimeout(timer); reject(error); });
    edge.on('exit', code => { clearTimeout(timer); reject(new Error(`Edge exited early: ${code}`)); });
    edge.stderr.on('data', data => {
      stderr += data.toString();
      const match = stderr.match(/DevTools listening on (ws:\/\/127\.0\.0\.1:\d+\/[^\s]+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
  });
  const port = new URL(endpoint).port;
  const targets = await fetch(`http://127.0.0.1:${port}/json/list`).then(r => r.json());
  const target = targets.find(item => item.type === 'page');
  assert.ok(target, 'Browser page target exists');
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, {once: true}); socket.addEventListener('error', reject, {once: true}); });
  let seq = 0;
  const pending = new Map();
  function cdp(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++seq;
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 12000);
      pending.set(id, {resolve: result => { clearTimeout(timer); resolve(result); }, reject: error => { clearTimeout(timer); reject(error); }});
      socket.send(JSON.stringify({id, method, params}));
    });
  }
  const wav = Buffer.alloc(44 + 4800);
  wav.write('RIFF', 0); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(24000, 24); wav.writeUInt32LE(48000, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34);
  wav.write('data', 36); wav.writeUInt32LE(4800, 40);
  let audioIndex = 0;
  async function intercept(event) {
    const {request, requestId} = event;
    const url = new URL(request.url);
    let response;
    let status = 200;
    let contentType = 'application/json';
    if (url.pathname === '/api/settings') {
      if (request.method !== 'GET') settingsWrites.push(JSON.parse(request.postData));
      response = Buffer.from(JSON.stringify(settings));
    } else if (url.pathname === '/api/synthesize') {
      const job = JSON.parse(request.postData);
      requests.push(job);
      if (failMini && job.provider === 'minimax') { status = 502; response = Buffer.from(JSON.stringify({error: '模拟厂商额度不足'})); }
      else {
        const id = `smoke-${++audioIndex}`;
        response = Buffer.from(JSON.stringify({...job, id, format: 'wav', originalFormat: 'wav', sampleRate: 24000, bytes: wav.length, elapsed: .25, createdAt: Date.now() / 1000, audioUrl: `/api/audio/${id}`, downloadUrl: `/api/audio/${id}?download=1`, payload: {model: job.model, input: {voice: job.voice}}}));
      }
    } else if (url.pathname.startsWith('/api/audio/smoke-')) { response = wav; contentType = 'audio/wav'; }
    // Preview is the real local payload builder. Block every other unhandled write,
    // including catalog refresh, so a new UI request cannot accidentally call a vendor.
    if (!response && request.method !== 'GET' && url.pathname !== '/api/preview') {
      await cdp('Fetch.failRequest', {requestId, errorReason: 'BlockedByClient'});
      throw new Error(`Unexpected backend write blocked: ${request.method} ${url.pathname}`);
    }
    if (response) await cdp('Fetch.fulfillRequest', {requestId, responseCode: status, responseHeaders: [{name: 'Content-Type', value: contentType}], body: response.toString('base64')});
    else await cdp('Fetch.continueRequest', {requestId});
  }
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const waiter = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) waiter?.reject(new Error(message.error.message));
      else waiter?.resolve(message.result);
    } else if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text + ': ' + (message.params.exceptionDetails.exception?.description || ''));
    else if (message.method === 'Fetch.requestPaused') intercept(message.params).catch(error => errors.push(error.message));
  });
  async function evaluate(expression) {
    const result = await cdp('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true, userGesture: true});
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  }
  async function until(expression) {
    for (let i = 0; i < 100; i++) { if (await evaluate(expression)) return; await pause(50); }
    throw new Error(`Browser condition timed out: ${expression}`);
  }
  async function click(selector) { await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`); }
  async function input(selector, value, event = 'input') {
    await evaluate(`{const n = document.querySelector(${JSON.stringify(selector)}); n.value = ${JSON.stringify(value)}; n.dispatchEvent(new Event(${JSON.stringify(event)}, {bubbles:true}));}`);
  }
  async function chooseProvider(id) {
    const index = catalog.providers.findIndex(p => p.id === id);
    assert.ok(index >= 0);
    await click(`.provider-tab:nth-child(${index + 1})`);
  }
  async function checkVoiceCount(id, model, query = '') {
    const all = voicesFor(id, model);
    const matches = all.filter(v => `${v.name} ${v.id} ${v.language} ${v.description || ''} ${v.category || ''}`.toLowerCase().includes(query.toLowerCase().trim()));
    assert.equal(await evaluate('document.querySelector("#voice-count").textContent'), `${matches.length} / ${all.length}`);
    assert.equal(await evaluate('document.querySelectorAll(".voice-card").length'), Math.min(100, matches.length));
    return matches;
  }
  async function chooseVoice(id, model, voice) {
    if (!await evaluate('document.querySelector("#voice-dialog").open')) await click('#voice-picker-open');
    assert.equal(await evaluate('document.querySelector("#voice-dialog").open'), true);
    await input('#voice-search', voice.id);
    await checkVoiceCount(id, model, voice.id);
    await evaluate(`{
      const card = [...document.querySelectorAll('.voice-card')].find(n => n.querySelector('code').textContent === ${JSON.stringify(voice.id)});
      if (!card) throw new Error('Catalog voice missing from rendered search');
      card.click();
    }`);
    assert.equal(await evaluate('document.querySelector(".voice-card.selected code").textContent'), voice.id);
    assert.equal(await evaluate('document.querySelector("#voice-dialog").open'), false, 'Picking a voice closes the library');
    assert.equal(await evaluate('document.querySelector("#current-voice-name").textContent'), voice.name);
  }
  async function hasControl(key, expected = true) {
    assert.equal(await evaluate(`Boolean(document.querySelector(${JSON.stringify(`#param-${key}`)}))`), expected, `${key} control ${expected ? 'available' : 'absent'}`);
  }
  async function openControlGroup(selector) {
    await evaluate(`{
      const control = document.querySelector(${JSON.stringify(selector)});
      if (!control) throw new Error('Missing grouped control');
      const group = control.closest('details');
      if (group && !group.open) group.querySelector('summary').click();
      if (!control.getClientRects().length) throw new Error('Grouped control is not visible');
    }`);
  }
  async function previewPayload() {
    await evaluate('document.querySelector("details.advanced").open = true; document.querySelector("#request-preview").hidden = true');
    await click('#preview-button');
    await until('!document.querySelector("#request-preview").hidden');
    return JSON.parse(await evaluate('document.querySelector("#request-preview").textContent'));
  }
  await cdp('Page.enable');
  await cdp('Runtime.enable');
  await cdp('Fetch.enable', {patterns: [{urlPattern: `${base}/api/*`}]});
  await cdp('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false});
  await cdp('Page.navigate', {url: base});
  await until(`document.querySelectorAll('.provider-tab').length === ${catalog.providers.length}`);
  assert.equal(await evaluate('document.querySelector("#model").value'), vendor('doubao').models[0].id);
  await checkVoiceCount('doubao', vendor('doubao').models[0].id);
  const doubaoModel = vendor('doubao').models.find(m => m.verified && voicesFor('doubao', m.id).some(v => v.verified))
    || vendor('doubao').models.find(m => voicesFor('doubao', m.id).some(v => v.verified));
  assert.ok(doubaoModel, 'An official Doubao model/voice pair exists');
  await input('#model', doubaoModel.id, 'change');
  const doubaoVoice = voicesFor('doubao', doubaoModel.id).find(v => v.verified);
  await chooseVoice('doubao', doubaoModel.id, doubaoVoice);
  for (const key of ['silence_duration', 'explicit_language', 'explicit_dialect', 'disable_markdown_filter', 'disable_emoji_filter', 'enable_latex_tn', 'latex_parser', 'max_length_to_filter_parenthesis', 'unsupported_char_ratio_thresh', 'aigc_watermark', 'aigc_metadata_enabled', 'cache_mode', 'pronunciation']) await hasControl(key);
  await openControlGroup('#param-silence_duration');
  await input('#param-silence_duration', '750', 'change');
  await input('#param-cache_mode', 'off', 'change');
  await input('#param-explicit_language', 'zh-cn', 'change');
  await input('#param-explicit_dialect', 'sichuan', 'change');
  await openControlGroup('#param-pronunciation');
  await input('#param-pronunciation', '重庆/(chong2)(qing4)');
  await openControlGroup('#param-disable_markdown_filter');
  await click('#param-disable_markdown_filter');
  await click('#param-enable_latex_tn');
  await input('#param-latex_parser', 'v2', 'change');
  await openControlGroup('#param-aigc_watermark');
  await click('#param-aigc_watermark');
  await click('#param-aigc_metadata_enabled');
  await input('#param-content_producer', 'local-smoke');
  const doubaoPreview = await previewPayload();
  const additions = JSON.parse(doubaoPreview.req_params.additions);
  assert.equal(additions.silence_duration, 750);
  assert.equal(additions.explicit_dialect, 'sichuan');
  assert.equal(additions.latex_parser, 'v2');
  assert.equal(additions.aigc_metadata.content_producer, 'local-smoke');
  assert.deepEqual(additions.pronunciation_dict.tone, ['重庆/(chong2)(qing4)']);
  assert.equal(additions.cache_config.use_cache, false);
  await input('#model', 'seed-tts-1.0', 'change');
  const emotionalVoice = voicesFor('doubao', 'seed-tts-1.0').find(v => v.emotions?.some(e => (e.id || e) === 'sad'));
  assert.ok(emotionalVoice, 'Official 1.0 voice with documented sadness exists');
  await chooseVoice('doubao', 'seed-tts-1.0', emotionalVoice);
  await hasControl('instructions', false);
  await hasControl('tone_fidelity', false);
  await input('#param-emotion', 'sad', 'change');
  const emotionalPreview = await previewPayload();
  assert.equal(emotionalPreview.req_params.audio_params.emotion, 'sad');
  assert.deepEqual(await evaluate('[...document.querySelector("#param-emotion").options].map(o => o.value)'), ['', ...emotionalVoice.emotions.map(e => e.id || e)]);
  await openControlGroup('#param-mix_enabled');
  assert.equal(await evaluate('document.querySelectorAll(".mix-row").length'), 3);
  await input('#model', doubaoModel.id, 'change');
  await chooseVoice('doubao', doubaoModel.id, doubaoVoice);
  await hasControl('emotion', false);
  const emotion = await evaluate('document.querySelector("#param-emotion") ? [...document.querySelector("#param-emotion").options].find(o => o.value)?.value : null');
  if (emotion) await input('#param-emotion', emotion, 'change');
  await click('#queue-add');

  await chooseProvider('minimax');
  assert.equal(await evaluate('document.querySelector("#insert-pause").hidden'), false);
  await input('#text', '停顿插入检查。');
  await evaluate('document.querySelector("#text").setSelectionRange(2, 2)');
  await click('#insert-pause');
  assert.equal(await evaluate('document.querySelector("#text").value'), '停顿<#0.5#>插入检查。');
  const miniModel = await evaluate('document.querySelector("#model").value');
  await checkVoiceCount('minimax', miniModel);
  await hasControl('pitch');
  await input('#param-speed', '1.5');
  await openControlGroup('#param-voice_pitch');
  for (const key of ['voice_pitch', 'intensity', 'timbre', 'sound_effects']) await hasControl(key);
  await input('#param-voice_pitch', '10');
  await openControlGroup('#param-mix_enabled');
  assert.equal(await evaluate('document.querySelectorAll(".mix-row").length'), 4);
  assert.ok(await evaluate('Boolean(document.querySelector("#mix-voice-0").getAttribute("aria-label"))'));
  const mixedVoices = vendor('minimax').voices.slice(0, 2);
  assert.ok(mixedVoices.length, 'MiniMax system voices are available for mixing');
  for (let i = 0; i < mixedVoices.length; i++) {
    await input(`#mix-voice-${i}`, mixedVoices[i].id, 'change');
    await evaluate(`{
      const weight = document.querySelectorAll('.mix-row')[${i}].querySelector('input');
      if (!weight.getAttribute('aria-label') || !weight.getClientRects().length) throw new Error('Mix weight must be visible and labelled');
      weight.value = ${100 / mixedVoices.length};
      weight.dispatchEvent(new Event('change', {bubbles:true}));
    }`);
  }
  await click('#param-mix_enabled');
  await click('#queue-add');

  await chooseProvider('qwen');
  const audioModel = 'qwen-audio-3.1-tts-flash';
  assert.equal(await evaluate('document.querySelector("#model").value'), audioModel);
  await checkVoiceCount('qwen', audioModel);
  for (const key of ['speed', 'volume', 'pitch', 'instructions', 'format', 'sample_rate', 'language_hints', 'ssml', 'timestamps', 'seed', 'hot_fix', 'aigc']) await hasControl(key);
  await click('.instruction-presets button:first-child');
  const instruction = await evaluate('document.querySelector("#param-instructions").value');
  assert.match(instruction, /开心/);
  const audioVoice = voicesFor('qwen', audioModel).find(v => ['instructions', 'ssml', 'timestamps'].every(key => v.capabilities?.[key] !== false));
  assert.ok(audioVoice, 'Region-allowed Qwen-Audio voice with full controls exists');
  await chooseVoice('qwen', audioModel, audioVoice);
  const tag = vendor('qwen').textTags[0].id;
  await input('#text', '标签插入检查。');
  await evaluate('document.querySelector("#text").setSelectionRange(0, 0)');
  await input('#text-tag', tag, 'change');
  assert.equal(await evaluate('document.querySelector("#text").value'), `${tag}标签插入检查。`);
  assert.equal(await evaluate('document.querySelector("#text-tag").value'), '');
  await click('#queue-add');
  assert.equal(await evaluate('document.querySelectorAll(".queue-item").length'), 3);
  let preview = await previewPayload();
  assert.equal(preview.model, audioModel);
  assert.equal(preview.input.voice, audioVoice.id);
  assert.equal(preview.input.instruction, instruction, 'Backend uses singular Qwen-Audio instruction');
  assert.equal(Object.hasOwn(preview.input, 'instructions'), false);
  assert.ok(['rate', 'volume', 'pitch', 'format', 'sample_rate'].every(key => Object.hasOwn(preview.input, key)));

  const flash30 = 'qwen-audio-3.0-tts-flash';
  const mary = voicesFor('qwen', flash30).find(v => v.id.toLowerCase().includes('loongmary'));
  if (mary && vendor('qwen').models.some(m => m.id === flash30)) {
    await input('#model', flash30, 'change');
    await chooseVoice('qwen', flash30, mary);
    for (const key of ['instructions', 'ssml', 'timestamps']) await hasControl(key, false);
    preview = await previewPayload();
    for (const key of ['instruction', 'instructions', 'enable_ssml', 'word_timestamp_enabled']) assert.equal(Object.hasOwn(preview.input, key), false);
    await input('#model', audioModel, 'change');
    await chooseVoice('qwen', audioModel, audioVoice);
    for (const key of ['instructions', 'ssml', 'timestamps']) await hasControl(key);
    assert.equal(await evaluate('document.querySelector("#param-instructions").value'), instruction);
  }
  await input('#model', 'qwen3-tts-flash', 'change');
  await checkVoiceCount('qwen', 'qwen3-tts-flash');
  assert.deepEqual(await evaluate('[...document.querySelectorAll("#controls [id^=param-]")].map(n => n.id)'), ['param-language']);
  assert.equal(await evaluate('Boolean(document.querySelector("#text-tag"))'), false);
  await input('#param-language', 'Chinese', 'change');
  await input('#text', '测'.repeat(601));
  assert.match(await evaluate('document.querySelector("#char-count").textContent'), /601\s*\/\s*600/);
  assert.ok(await evaluate('document.querySelector("#char-count").classList.contains("over-limit")'));
  await evaluate('document.querySelector("details.advanced").open = true');
  await click('#preview-button');
  await until('document.querySelector("#toast").textContent.includes("600")');
  assert.equal(await evaluate('document.querySelector("#request-preview").hidden'), true);
  await input('#text', '测'.repeat(600));
  assert.equal(await evaluate('document.querySelector("#char-count").classList.contains("over-limit")'), false);
  preview = await previewPayload();
  assert.deepEqual(Object.keys(preview.input).sort(), ['language_type', 'text', 'voice']);
  assert.equal(preview.input.language_type, 'Chinese');
  assert.equal(preview.input.text.length, 600);
  await input('#model', audioModel, 'change');
  await chooseVoice('qwen', audioModel, audioVoice);
  await input('#text', '这是当前 Qwen-Audio 的试听文本。');
  preview = await previewPayload();
  assert.equal(preview.input.instruction, instruction);
  assert.equal(requests.length, 0, 'All previews use the real backend without synthesis');

  await click('#synthesize');
  await until('document.querySelectorAll(".result-card").length === 1 && !document.querySelector("#synthesize").disabled');
  await evaluate('document.querySelector("audio").play()');
  await until('document.querySelector("audio").readyState >= 2');
  assert.equal(await evaluate('document.querySelector(".audio-error").hidden'), true);
  await input('#text', '这是三家共用的对比文本。');
  await click('.nav-item[data-view="compare"]');
  assert.equal(await evaluate('document.querySelector("#compare-view").hidden'), false);
  assert.equal(await evaluate('document.querySelector("#studio-view").hidden'), true);
  failMini = true;
  await click('#compare-run');
  await until('Boolean(document.querySelector(".batch-error")) && !document.querySelector("#synthesize").disabled');
  assert.equal(await evaluate('document.querySelectorAll(".result-card").length'), 3);
  assert.equal(await evaluate('document.querySelector("#history-view").hidden'), false, 'Comparison opens generation history');
  const firstAudio = await evaluate('document.querySelector("#studio-player").getAttribute("src")');
  await click('.result-card .result-play');
  await until('document.querySelector("#studio-player").readyState >= 2');
  assert.equal(await evaluate('document.querySelectorAll("audio").length'), 1, 'Results share one persistent player');
  const activeAudio = await evaluate('document.querySelector("#studio-player").getAttribute("src")');
  assert.notEqual(activeAudio, firstAudio, 'History selection switches the persistent audio');
  await click('#player-prev');
  assert.notEqual(await evaluate('document.querySelector("#studio-player").getAttribute("src")'), activeAudio, 'Previous record changes audio');
  await click('#player-next');
  assert.equal(await evaluate('document.querySelector("#studio-player").getAttribute("src")'), activeAudio, 'Next record restores audio');
  assert.ok(await evaluate('!document.querySelector("#player-download").hidden'));
  await click('.nav-item[data-view="studio"]');
  assert.equal(await evaluate('document.querySelector("#studio-player").getAttribute("src")'), activeAudio, 'Navigation preserves playback');
  await click('.nav-item[data-view="history"]');
  assert.match(await evaluate('document.querySelector(".batch-error").textContent'), /2 组成功，1 组失败/);
  assert.equal(requests.length, 4);
  assert.ok(requests.slice(1).every(job => job.text === '这是三家共用的对比文本。'));
  const doubaoJob = requests.slice(1).find(job => job.provider === 'doubao');
  assert.equal(doubaoJob.model, doubaoModel.id);
  assert.equal(doubaoJob.voice, doubaoVoice.id);
  assert.equal(doubaoJob.params.emotion, emotion || '');
  const miniJob = requests.find(job => job.provider === 'minimax');
  assert.equal(miniJob.params.speed, 1.5);
  assert.equal(miniJob.params.voice_pitch, 10);
  assert.equal(miniJob.params.mix_enabled, true);
  assert.deepEqual(miniJob.params.timbre_weights.filter(v => v.voice_id), mixedVoices.map(v => ({voice_id: v.id, weight: 100 / mixedVoices.length})));
  const qwenJob = requests.slice(1).find(job => job.provider === 'qwen');
  assert.equal(qwenJob.model, audioModel);
  assert.equal(qwenJob.voice, audioVoice.id);
  assert.equal(qwenJob.params.instructions, instruction, 'Queue snapshot survives model/voice switches');
  await click('#settings-open');
  assert.equal(await evaluate('document.querySelector("#settings-dialog").open'), true);
  await input('#credential-qwen-api_key', 'fake-browser-test-key');
  await evaluate('document.querySelector("#credential-qwen-api_key").form.requestSubmit()');
  await until('document.querySelector("#settings-message").textContent.includes("已保存")');
  assert.equal(settingsWrites.length, 1, 'Settings save was intercepted');
  assert.equal(settingsWrites[0].provider, 'qwen');
  assert.equal(settingsWrites[0].fields.api_key, 'fake-browser-test-key');
  assert.equal(await evaluate('document.querySelector("#credential-qwen-api_key").value'), '');
  assert.equal(await evaluate('Object.values(localStorage).some(value => value.includes("fake-browser-test-key"))'), false);
  await click('#settings-close');
  await click('.nav-item[data-view="studio"]');
  await input('#param-speed', '1.4');
  await click('#reset-controls');
  assert.equal(await evaluate('document.querySelector("#param-speed").value'), '1');
  assert.equal(await evaluate('document.querySelector("#param-instructions").value'), '');
  assert.equal(await evaluate('document.querySelectorAll(".queue-item").length'), 3, 'Reset preserves comparison snapshots');
  await click('#clear-text');
  assert.equal(await evaluate('document.querySelector("#text").value'), '');
  await evaluate('document.querySelector("#text").dispatchEvent(new KeyboardEvent("keydown", {key:"Enter", ctrlKey:true, bubbles:true}))');
  assert.match(await evaluate('document.querySelector("#toast").textContent'), /请先输入/);
  assert.equal(requests.length, 4, 'Empty keyboard submission does not call synthesis');
  await input('#text', '这是三家共用的对比文本。');
  await evaluate('document.documentElement.dataset.theme = "light"; document.querySelector(".inspector-scroll").scrollTop = 0; window.scrollTo(0, 0)');
  assert.ok(await evaluate('document.querySelector("#text").getBoundingClientRect().width > document.querySelector(".inspector").getBoundingClientRect().width'), 'Desktop prioritizes the editor');
  assert.ok(await evaluate('document.querySelector("#synthesize").getBoundingClientRect().bottom <= document.querySelector(".player-bar").getBoundingClientRect().top'), 'Generation remains above the persistent player');
  assert.ok(await evaluate('document.documentElement.scrollHeight <= innerHeight + 1'), 'Desktop workspace fits one viewport');
  await evaluate('document.querySelector("#toast").hidden = true');
  const desktop = await cdp('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
  await writeFile(path.join(artifacts, 'desktop.png'), Buffer.from(desktop.data, 'base64'));
  await click('#theme-toggle');
  assert.equal(await evaluate('document.documentElement.dataset.theme'), 'dark');
  const dark = await cdp('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
  await writeFile(path.join(artifacts, 'desktop-dark.png'), Buffer.from(dark.data, 'base64'));
  await click('#theme-toggle');
  await cdp('Emulation.setDeviceMetricsOverride', {width: 400, height: 880, deviceScaleFactor: 1, mobile: true});
  assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Phone layout has no horizontal overflow');
  await click('#voice-picker-open');
  assert.equal(await evaluate('document.querySelector("#voice-dialog").open'), true);
  assert.ok(await evaluate('document.querySelector("#voice-dialog").getBoundingClientRect().width <= innerWidth - 32'), 'Phone voice library fits within viewport gutters');
  await click('#voice-dialog-close');
  await evaluate('window.scrollTo(0, 0)');
  const mobile = await cdp('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
  await writeFile(path.join(artifacts, 'mobile.png'), Buffer.from(mobile.data, 'base64'));
  assert.deepEqual(errors, [], 'No browser JavaScript errors');
  console.log('PASS: live catalogs, provider/model/voice selection, per-voice capabilities, Qwen-Audio instruction preview/tags, Qwen3 language/600-character limit, MiniMax mix/voice modification, queue snapshots, shared-text comparison, partial failures, audio playback, intercepted settings save, theme, 400px layout.');
  console.log(`Screenshots: ${path.join(artifacts, 'desktop.png')} and mobile.png`);
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  edge.kill();
  // Edge can hold profile files briefly on Windows. Artifacts are gitignored.
  try { await rm(profile, {recursive: true, force: true, maxRetries: 5, retryDelay: 200}); } catch {}
}
