// Real Edge browser checks with intercepted synthesis/settings/voice-refresh writes. No paid calls.
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
    } else if (url.pathname === '/api/voices/refresh') {
      const voices = [...vendor('minimax').voices.slice(0, 2),
        {id: 'smoke-test_Woman', name: 'Test Woman', language: 'English', source: 'MiniMax get_voice · system', verified: true},
        {id: 'smoke-test-neutral', name: 'Neutral', language: '官方系统音色', source: 'MiniMax get_voice · system', verified: true}];
      response = Buffer.from(JSON.stringify({count: voices.length, voices}));
    } else if (url.pathname === '/api/synthesize') {
      const job = JSON.parse(request.postData);
      requests.push(job);
      if (failMini && job.provider === 'minimax') { status = 502; response = Buffer.from(JSON.stringify({error: '模拟厂商额度不足'})); }
      else {
        const id = `smoke-${++audioIndex}`;
        response = Buffer.from(JSON.stringify({...job, id, format: 'wav', originalFormat: 'wav', sampleRate: 24000, bytes: wav.length, elapsed: .25, createdAt: Date.now() / 1000, audioUrl: `/api/audio/${id}`, downloadUrl: `/api/audio/${id}?download=1`, payload: {model: job.model, input: {voice: job.voice}}}));
      }
    } else if (url.pathname.startsWith('/api/audio/smoke-')) { response = wav; contentType = 'audio/wav'; }
    // Preview is the real local payload builder. Synthesis, settings and refresh
    // are mocked above; block every other unhandled write to avoid vendor calls.
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
  async function checkVoiceFilters(id, model) {
    const all = voicesFor(id, model);
    const current = await evaluate('document.querySelector("#current-voice-name").textContent');
    await click('#voice-picker-open');
    for (const gender of ['男', '女']) {
      await click(`.filter-chip[data-filter="gender"][data-value="${gender}"]`);
      assert.ok(await evaluate('document.querySelectorAll(".voice-card").length > 0'));
      assert.ok(await evaluate(`[...document.querySelectorAll('.voice-card .voice-badge:first-child')].every(n => n.textContent === ${JSON.stringify(gender)})`));
      if (id !== 'minimax') {
        const expected = all.filter(v => v.gender === gender || v.gender === (gender === '男' ? 'male' : 'female'));
        assert.equal(await evaluate('document.querySelector("#voice-count").textContent'), `${expected.length} / ${all.length}`);
      }
      if (await evaluate('Boolean(document.querySelector(".load-more"))')) {
        await click('.load-more');
        assert.ok(await evaluate('document.querySelectorAll(".voice-card").length > 100'));
      }
      await input('#voice-search', 'no-such-voice-filter-test');
      assert.equal(await evaluate('document.querySelectorAll(".voice-card").length'), 0, 'Gender and search intersect');
      assert.match(await evaluate('document.querySelector("#voice-list .empty").textContent'), /清空筛选/);
      await input('#voice-search', '');
      assert.ok(await evaluate('document.querySelectorAll(".voice-card").length <= 100'), 'Search resets pagination');
    }
    await click('.filter-chip[data-filter="language"][data-value="英语"]');
    assert.ok(await evaluate('[...document.querySelectorAll(".voice-card .voice-badge:first-child")].every(n => n.textContent === "女")'));
    const ids = await evaluate('[...document.querySelectorAll(".voice-card code")].map(n => n.textContent)');
    assert.ok(ids.length > 0);
    assert.ok(ids.every(voiceId => /英语|英文|English/i.test(all.find(v => v.id === voiceId).language)), 'Language and gender intersect');
    await click('#voice-filters-clear');
    await checkVoiceCount(id, model);
    assert.equal(await evaluate('document.querySelector("#current-voice-name").textContent'), current, 'Filtering preserves the selected voice');
    assert.equal(await evaluate('document.querySelector("#voice-filters-clear").disabled'), true);
    await click('#voice-dialog-close');
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
  async function checkSettingsLayout(fitsWithoutScroll = false) {
    const layout = await evaluate(`(() => {
      const dialog = document.querySelector('#settings-dialog');
      const panel = [...document.querySelectorAll('.connection-form')].find(n => !n.hidden);
      const fields = panel.querySelector('.connection-fields');
      const footer = panel.querySelector('.connection-footer').getBoundingClientRect();
      const close = document.querySelector('#settings-close').getBoundingClientRect();
      const bounds = dialog.getBoundingClientRect();
      return {visible: [...document.querySelectorAll('.connection-form')].filter(n => !n.hidden).length,
        dialogScroll: dialog.scrollHeight - dialog.clientHeight, fieldsScroll: fields.scrollHeight - fields.clientHeight,
        overflowX: dialog.scrollWidth - dialog.clientWidth, footerTop: footer.top, footerBottom: footer.bottom,
        closeTop: close.top, closeBottom: close.bottom, dialogTop: bounds.top, dialogBottom: bounds.bottom, height: innerHeight};
    })()`);
    assert.equal(layout.visible, 1, 'Only one provider settings panel is visible');
    assert.ok(layout.dialogScroll <= 1, 'Settings dialog itself does not scroll');
    assert.ok(layout.overflowX <= 1, 'Settings fit within the dialog width');
    assert.ok(layout.footerTop >= layout.dialogTop && layout.footerBottom <= Math.min(layout.height, layout.dialogBottom) + 1, 'Save and clear remain visible');
    assert.ok(layout.closeTop >= 0 && layout.closeBottom <= layout.height, 'Close remains visible');
    if (fitsWithoutScroll) assert.ok(layout.fieldsScroll <= 1, 'All connection fields fit without scrolling');
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
  assert.deepEqual(await evaluate(`[
    voiceFacets({id: 'English_TestWoman', name: 'Test Woman', source: 'MiniMax get_voice · system'}).gender[0],
    voiceFacets({id: 'male-test', name: '女声', source: 'MiniMax get_voice · system'}).gender[0],
    voiceFacets({id: 'Arnold', name: 'Arnold', source: 'MiniMax get_voice · system'}).gender[0],
    voiceFacets({id: 'male-test', name: '男声', gender: '不能', source: 'qwen'}).gender[0],
    voiceFacets({id: 'test', language: '中文、支持30+语种识别'}).language
  ]`), ['女', '未标注', '未标注', '未标注', ['中文']], 'Conflicting or invalid metadata and personal names do not invent gender or languages');
  assert.equal(await evaluate('document.querySelector("#model").value'), vendor('doubao').models[0].id);
  await checkVoiceCount('doubao', vendor('doubao').models[0].id);
  await checkVoiceFilters('doubao', vendor('doubao').models[0].id);
  await click('#voice-picker-open');
  await input('#voice-filter-scenario', '角色扮演', 'change');
  const roleIds = await evaluate('[...document.querySelectorAll(".voice-card code")].map(n => n.textContent)');
  assert.ok(roleIds.length > 0);
  assert.ok(roleIds.every(id => voicesFor('doubao', vendor('doubao').models[0].id).find(v => v.id === id).scenario.includes('角色扮演')));
  await input('#voice-filter-tag', '豆包同款', 'change');
  const taggedIds = await evaluate('[...document.querySelectorAll(".voice-card code")].map(n => n.textContent)');
  assert.ok(taggedIds.length > 0);
  assert.ok(taggedIds.every(id => voicesFor('doubao', vendor('doubao').models[0].id).find(v => v.id === id).catalogueEntries.some(entry => entry.tags.includes('豆包同款'))));
  await click('#voice-filters-clear');
  await click('#voice-dialog-close');
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
  await checkVoiceFilters('minimax', miniModel);
  await click('#voice-picker-open');
  for (const [voiceId, gender] of [['male-qn-qingse', '男'], ['female-shaonv', '女'], ['English_Graceful_Lady', '女'], ['Grinch', '未标注']]) {
    await input('#voice-search', voiceId);
    const badges = await evaluate(`[...document.querySelectorAll('.voice-card')].filter(n => n.querySelector('code').textContent === ${JSON.stringify(voiceId)}).map(n => n.querySelector('.voice-badge').textContent)`);
    assert.deepEqual(badges, [gender], `${voiceId}: explicit official gender markers only`);
  }
  await click('#voice-filters-clear');
  await click('#voice-dialog-close');
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
  await checkVoiceFilters('qwen', audioModel);
  await click('#voice-picker-open');
  await input('#voice-filter-category', '精品英文音色', 'change');
  const categoryIds = await evaluate('[...document.querySelectorAll(".voice-card code")].map(n => n.textContent)');
  assert.ok(categoryIds.length > 0);
  assert.ok(categoryIds.every(id => voicesFor('qwen', audioModel).find(v => v.id === id).category === '精品英文音色'));
  await input('#voice-search', 'still-filtered');
  await input('#model', 'qwen-audio-3.0-tts-flash', 'change');
  assert.equal(await evaluate('document.querySelector("#voice-search").value'), '', 'Model switch resets search');
  await checkVoiceCount('qwen', 'qwen-audio-3.0-tts-flash');
  await checkVoiceFilters('qwen', 'qwen-audio-3.0-tts-flash');
  await click('#voice-picker-open');
  await click('.filter-chip[data-filter="gender"][data-value="未标注"]');
  assert.equal(await evaluate('document.querySelectorAll(".voice-card").length'), 1, 'Invalid official gender stays unspecified');
  assert.match(await evaluate('document.querySelector(".voice-card code").textContent'), /longchuanrongshuo/);
  await chooseProvider('minimax');
  await checkVoiceCount('minimax', miniModel);
  assert.equal(await evaluate('document.querySelectorAll(".filter-chip[data-filter=gender][aria-pressed=true]").length'), 1);
  assert.equal(await evaluate('document.querySelector(".filter-chip[data-filter=gender][aria-pressed=true]").dataset.value'), '', 'Provider switch resets filters');
  await chooseProvider('qwen');
  await input('#model', audioModel, 'change');
  await click('#voice-dialog-close');
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
  await cdp('Emulation.setDeviceMetricsOverride', {width: 1366, height: 768, deviceScaleFactor: 1, mobile: false});
  await click('#settings-open');
  assert.equal(await evaluate('document.querySelector("#settings-dialog").open'), true);
  assert.equal(await evaluate('document.querySelector("#settings-tab-qwen").getAttribute("aria-selected")'), 'true', 'Settings open on the current synthesis provider');
  await checkSettingsLayout(true);
  await click('#settings-tab-doubao');
  await checkSettingsLayout(true);
  await input('#credential-doubao-api_key', 'fake-unsaved-doubao');
  const connectionDesktop = await cdp('Page.captureScreenshot', {format: 'png'});
  await writeFile(path.join(artifacts, 'settings-desktop.png'), Buffer.from(connectionDesktop.data, 'base64'));
  await click('#settings-tab-minimax');
  await checkSettingsLayout(true);
  await input('#credential-minimax-api_key', 'fake-unsaved-minimax');
  await click('#settings-tab-qwen');
  await input('#credential-qwen-api_key', 'fake-browser-test-key');
  await evaluate('document.querySelector("#credential-qwen-api_key").form.requestSubmit()');
  await until('document.querySelector("#settings-message").textContent.includes("已保存")');
  assert.equal(settingsWrites.length, 1, 'Settings save was intercepted');
  assert.equal(settingsWrites[0].provider, 'qwen');
  assert.equal(settingsWrites[0].fields.api_key, 'fake-browser-test-key');
  assert.equal(await evaluate('document.querySelector("#credential-qwen-api_key").value'), '');
  assert.equal(await evaluate('document.querySelector("#credential-doubao-api_key").value'), 'fake-unsaved-doubao', 'Saving Qwen preserves the Doubao draft');
  assert.equal(await evaluate('document.querySelector("#credential-minimax-api_key").value'), 'fake-unsaved-minimax', 'Saving Qwen preserves the MiniMax draft');
  assert.equal(await evaluate('Object.values(localStorage).some(value => /fake-browser-test-key|fake-unsaved/.test(value))'), false);
  await checkSettingsLayout(true);
  await evaluate('document.querySelector("#settings-tab-qwen").dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowLeft", bubbles: true}))');
  assert.equal(await evaluate('document.activeElement.id'), 'settings-tab-minimax', 'Arrow keys move between provider tabs');
  await evaluate('document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key: "End", bubbles: true}))');
  assert.equal(await evaluate('document.activeElement.id'), 'settings-tab-qwen');
  await click('#settings-close');
  await until('[...document.querySelectorAll("#settings-dialog input")].every(n => !n.value)');
  assert.equal(await evaluate('document.querySelector("#settings-dialog").open'), false, 'Closing settings clears all unsaved credentials');
  await cdp('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false});
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
  await click('#voice-picker-open');
  await click('#voice-filters-clear');
  await click('.filter-chip[data-filter="gender"][data-value="女"]');
  const library = await cdp('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
  await writeFile(path.join(artifacts, 'voice-filters-desktop.png'), Buffer.from(library.data, 'base64'));
  await click('#voice-dialog-close');
  await cdp('Emulation.setDeviceMetricsOverride', {width: 400, height: 880, deviceScaleFactor: 1, mobile: true});
  assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Phone layout has no horizontal overflow');
  await click('#settings-open');
  await checkSettingsLayout(true);
  await click('#settings-tab-doubao');
  await checkSettingsLayout(true);
  const connectionMobile = await cdp('Page.captureScreenshot', {format: 'png'});
  await writeFile(path.join(artifacts, 'settings-mobile.png'), Buffer.from(connectionMobile.data, 'base64'));
  await cdp('Emulation.setDeviceMetricsOverride', {width: 400, height: 480, deviceScaleFactor: 1, mobile: true});
  for (const id of ['doubao', 'minimax', 'qwen']) {
    await click(`#settings-tab-${id}`);
    await checkSettingsLayout();
    await evaluate(`document.querySelector('#settings-panel-${id} .connection-fields').scrollTop = 10000`);
    await checkSettingsLayout();
  }
  await click('#settings-close');
  await cdp('Emulation.setDeviceMetricsOverride', {width: 400, height: 880, deviceScaleFactor: 1, mobile: true});
  await click('#voice-picker-open');
  assert.equal(await evaluate('document.querySelector("#voice-dialog").open'), true);
  assert.ok(await evaluate('document.querySelector("#voice-dialog").getBoundingClientRect().width <= innerWidth - 32'), 'Phone voice library fits within viewport gutters');
  assert.ok(await evaluate('document.querySelector("#voice-dialog").scrollWidth <= document.querySelector("#voice-dialog").clientWidth'), 'Phone filters have no horizontal overflow');
  await click('.filter-chip[data-filter="gender"][data-value="男"]');
  assert.ok(await evaluate('document.querySelectorAll(".voice-card").length > 0'), 'Phone gender filter returns matching voices');
  assert.ok(await evaluate('[...document.querySelectorAll(".voice-card .voice-badge:first-child")].every(n => n.textContent === "男")'));
  const phoneLibrary = await cdp('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
  await writeFile(path.join(artifacts, 'voice-filters-mobile.png'), Buffer.from(phoneLibrary.data, 'base64'));
  await click('#voice-dialog-close');
  await evaluate('window.scrollTo(0, 0)');
  const mobile = await cdp('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
  await writeFile(path.join(artifacts, 'mobile.png'), Buffer.from(mobile.data, 'base64'));
  await chooseProvider('minimax');
  await click('#voice-picker-open');
  await click('.filter-chip[data-filter="language"][data-value="葡萄牙语"]');
  await click('#refresh-voices');
  await until('document.querySelector("#voice-count").textContent === "4 / 4"');
  assert.equal(await evaluate('Boolean(document.querySelector(".filter-chip[data-value=葡萄牙语]"))'), false, 'Refreshing voices rebuilds filter options and clears stale values');
  await click('.filter-chip[data-filter="gender"][data-value="女"]');
  assert.equal(await evaluate('document.querySelector(".voice-card code").textContent'), 'smoke-test_Woman');
  await click('.filter-chip[data-filter="gender"][data-value="未标注"]');
  assert.equal(await evaluate('document.querySelector(".voice-card code").textContent'), 'smoke-test-neutral', 'New API voices without metadata remain selectable');
  await click('#voice-dialog-close');
  assert.deepEqual(errors, [], 'No browser JavaScript errors');
  console.log('PASS: official voice gender/language/category/scenario/tag filters, combined search, unspecified metadata, pagination/reset/refresh, live catalogs, provider/model/voice selection, per-voice capabilities, Qwen-Audio instruction preview/tags, Qwen3 language/600-character limit, MiniMax mix/voice modification, queue snapshots, shared-text comparison, partial failures, audio playback, intercepted settings save, provider settings tabs/draft preservation/keyboard navigation, fixed settings actions at desktop/mobile/short viewports, theme, 400px layout.');
  console.log(`Screenshots: ${path.join(artifacts, 'desktop.png')} and mobile.png`);
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  edge.kill();
  // Edge can hold profile files briefly on Windows. Artifacts are gitignored.
  try { await rm(profile, {recursive: true, force: true, maxRetries: 5, retryDelay: 200}); } catch {}
}
