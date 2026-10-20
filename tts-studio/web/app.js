'use strict';

const $ = id => document.getElementById(id);
const state = {catalog: null, settings: null, provider: 'doubao', models: {}, sessions: {}, queue: [], results: [], busy: false, voiceLimit: 100};
let toastTimer;
const samples = {
  narration: '黄昏的时候，最后一班电车穿过小城。她捧着一杯热茶，看着窗外缓缓亮起的灯，忽然觉得，生活还有许多值得期待的事。',
  dialogue: '真的吗？太好了！我等这个消息已经很久了。可是，你明天就要走了吗？我还以为，我们能一起看完这场烟花。',
  mixed: '欢迎使用我们的新产品。Hello, welcome to the future of voice. 今天，我们一起探索 AI 语音的更多可能。',
  numbers: '今天是2026年10月19日，订单编号为A1024，总金额是1299.50元。请在下午3点30分前，拨打400-123-4567联系我们。'
};
const defaults = {
  doubao: {speed: 0, volume: 0, pitch: 0, emotion: '', emotion_scale: 4, instructions: '', format: 'mp3', sample_rate: 24000, bitrate: 64000, disable_default_bit_rate: false, timestamps: false, enable_subtitle: false, ssml: false, explicit_language: '', explicit_dialect: '', context_language: '', enable_auto_language_recognition: false, enable_language_detector: false, disable_markdown_filter: false, disable_emoji_filter: false, silence_duration: 0, enable_latex_tn: false, latex_parser: '', max_length_to_filter_parenthesis: 0, unsupported_char_ratio_thresh: .3, pronunciation: [], section_id: '', aigc_watermark: false, aigc_metadata_enabled: false, content_producer: '', produce_id: '', content_propagator: '', propagate_id: '', cache_mode: '', mute_cut_threshold: '', mute_cut_remain_ms: '', mix_enabled: false, timbre_weights: []},
  minimax: {speed: 1, volume: 1, pitch: 0, emotion: '', format: 'mp3', sample_rate: 24000, bitrate: 128000, channel: 1, language_boost: 'auto', latex_read: false, pronunciation: [], normalization_mode: '', voice_pitch: 0, intensity: 0, timbre: 0, sound_effects: '', subtitle: false, subtitle_type: 'sentence', aigc: false, vendor_stream: false, force_cbr: false, mix_enabled: false, timbre_weights: []},
  qwen: {language: 'Auto', speed: 1, volume: 50, pitch: 1, instructions: '', format: 'wav', sample_rate: 24000, opus_bitrate: 32, language_hints: '', seed: 0, ssml: false, timestamps: false, hot_fix: '{}', aigc: false, aigc_propagator: '', aigc_propagate_id: ''}
};

function element(tag, attributes = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'checked' || key === 'disabled' || key === 'hidden') node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(typeof child === 'string' ? document.createTextNode(child) : child);
  return node;
}
function toast(message, error = false) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').classList.toggle('error', error);
  $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, error ? 10000 : 4500);
}
async function api(path, body) {
  const options = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Session-Token': state.settings.sessionToken}, body: JSON.stringify(body)};
  let response;
  try { response = await fetch(path, options); }
  catch { throw new Error('无法连接本地服务，请检查服务是否仍在运行。'); }
  let data;
  try { data = await response.json(); }
  catch { throw new Error('服务返回了无法解析的响应。'); }
  if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
  return data;
}
function provider() { return state.catalog.providers.find(item => item.id === state.provider); }
function modelId() { return state.models[state.provider] || provider().models[0].id; }
function model() { return provider().models.find(item => item.id === modelId()); }
function session() {
  const key = `${state.provider}:${modelId()}`;
  if (!state.sessions[key]) state.sessions[key] = {voice: '', params: {...structuredClone(defaults[state.provider]), ...structuredClone(model().defaults || {})}, extra: '{}', customModel: '', customVoice: ''};
  return state.sessions[key];
}
function availableVoices() {
  const region = state.settings.providers[state.provider].region;
  return provider().voices.filter(voice => (!voice.models || voice.models.includes(modelId())) && (!voice.regions || voice.regions.includes(region)));
}
function selectedVoice() { return provider().voices.find(voice => voice.id === session().voice); }
function activeControls() {
  if (session().customModel) return [];
  const capabilities = selectedVoice()?.capabilities || {};
  return model().controls.filter(key => capabilities[key] !== false && !(state.provider === 'doubao' && ['emotion', 'emotion_scale'].includes(key) && !selectedVoice()?.emotions?.length));
}
function configuredFor(job) {
  const config = state.settings.providers[job.provider];
  return config.configured && !(job.provider === 'qwen' && job.model.startsWith('qwen-audio-') && !config.fields.workspace_id);
}
function updateCount() {
  const info = state.catalog ? model() : {};
  const count = [...$('text').value].length;
  const bytes = new TextEncoder().encode($('text').value).length;
  const limit = info.maxTextBytes ? `${bytes.toLocaleString()} / ${info.maxTextBytes.toLocaleString()} UTF-8 字节` : `${count.toLocaleString()} / ${(info.maxText || 10000).toLocaleString()} 字符`;
  $('char-count').textContent = limit;
  $('char-count').classList.toggle('over-limit', info.maxTextBytes ? bytes > info.maxTextBytes : count > (info.maxText || 10000));
}
function updateSummary() {
  const s = session();
  const name = s.customVoice || selectedVoice()?.name || '尚未选择音色';
  $('selected-summary').textContent = `${provider().name} · ${s.customModel || modelId()} · ${name}`;
  const configured = configuredFor({provider: state.provider, model: s.customModel || modelId()});
  $('connection-status').textContent = configured ? '凭据已配置' : state.provider === 'qwen' && state.settings.providers.qwen.configured ? '需填写业务空间 ID' : '尚未配置凭据';
  $('connection-status').classList.toggle('connected', configured);
}
function renderProviders() {
  $('provider-tabs').replaceChildren(...state.catalog.providers.map(p => element('button', {
    class: `provider-tab ${p.id === state.provider ? 'active' : ''}`, role: 'tab', 'aria-selected': String(p.id === state.provider),
    onclick: () => { state.provider = p.id; state.voiceLimit = 100; $('voice-search').value = ''; renderSelection(); }
  }, [element('strong', {text: p.name}), element('small', {text: p.subtitle})])));
}
function renderSelection() {
  renderProviders();
  const p = provider();
  const s = session();
  $('model').replaceChildren(...p.models.map(m => element('option', {value: m.id, text: m.name})));
  $('model').value = modelId();
  $('custom-model').value = s.customModel;
  $('custom-voice').value = s.customVoice;
  $('extra-json').value = s.extra;
  $('request-preview').hidden = true;
  $('provider-notes').textContent = p.notes;
  $('voice-docs').href = model().voiceDocs || p.voiceDocs;
  $('api-docs').href = model().docs || p.docs;
  $('refresh-voices').hidden = p.id !== 'minimax';
  const voices = availableVoices();
  if (!voices.some(v => v.id === s.voice)) s.voice = voices[0]?.id || '';
  renderVoices();
  renderControls();
  updateSummary();
  updateCount();
}
function renderVoices() {
  const selected = selectedVoice();
  $('voice-description').textContent = selected ? [selected.gender, selected.description, selected.scenarios, selected.emotionSupport === 'unknown' ? '官方未提供逐音色的完整能力保证；控制项按模型提供，实际可用性由账号接口确认。' : ''].filter(Boolean).join(' · ') : '';
  const query = $('voice-search').value.toLowerCase().trim();
  const all = availableVoices();
  const voices = all.filter(v => `${v.name} ${v.id} ${v.language} ${v.description || ''} ${v.category || ''}`.toLowerCase().includes(query));
  $('voice-count').textContent = `${voices.length} / ${all.length}`;
  $('voice-list').replaceChildren(...voices.slice(0, state.voiceLimit).map(v => element('button', {
    class: `voice-card ${session().voice === v.id ? 'selected' : ''}`, role: 'radio', 'aria-checked': String(session().voice === v.id),
    title: [v.name, v.description, v.id].filter(Boolean).join(' · '),
    onclick: () => { session().voice = v.id; renderVoices(); renderControls(); updateSummary(); }
  }, [element('span', {class: 'voice-initial', text: v.name.slice(0, 1)}), element('span', {class: 'voice-info'}, [element('strong', {text: v.name}), element('small', {text: `${v.language} · ${v.source === 'MiniMax get_voice · system' ? '接口返回' : v.verified ? '官方文档' : '自定义'}`}), element('code', {text: v.id})]), element('span', {class: 'voice-check', 'aria-hidden': 'true', text: session().voice === v.id ? '●' : '○'})])));
  if (voices.length > state.voiceLimit) $('voice-list').append(element('button', {class: 'button secondary load-more', text: `显示更多（还有 ${voices.length - state.voiceLimit} 个）`, onclick: () => { state.voiceLimit += 100; renderVoices(); }}));
  if (!voices.length) $('voice-list').append(element('p', {class: 'empty', text: '没有匹配的音色。可尝试其他关键词，或指定音色 ID。'}));
}
function controlField(label, node, hint) {
  return element('div', {class: 'field'}, [element('label', {for: node.id, text: label}), node, ...(hint ? [element('p', {class: 'hint', text: hint})] : [])]);
}
function selectControl(key, label, options, hint) {
  if (!options.some(([value]) => value === session().params[key])) session().params[key] = options[0][0];
  const select = element('select', {id: `param-${key}`, onchange: () => {
    session().params[key] = typeof options[0][0] === 'number' ? Number(select.value) : select.value;
    if (key === 'format') {
      if (['pcmu_raw', 'pcmu_wav'].includes(select.value)) session().params.sample_rate = 8000;
      if (state.provider === 'doubao' && select.value === 'ogg_opus') session().params.sample_rate = 48000;
      if (state.provider === 'qwen' && select.value === 'opus' && ![8000, 12000, 16000, 24000, 48000].includes(session().params.sample_rate)) session().params.sample_rate = 24000;
      renderControls();
    }
  }});
  select.append(...options.map(([value, title]) => element('option', {value, text: title})));
  select.value = session().params[key];
  return controlField(label, select, hint);
}
function rangeControl(key, label, min, max, step, suffix = '', hint = '') {
  const id = `param-${key}`;
  const input = element('input', {type: 'range', id, min, max, step, value: session().params[key]});
  const number = element('input', {type: 'number', min, max, step, value: session().params[key], 'aria-label': `${label}数值`});
  const update = (source, target) => {
    const value = source.valueAsNumber;
    if (Number.isFinite(value) && value >= min && value <= max) { session().params[key] = value; target.value = value; }
  };
  input.addEventListener('input', () => update(input, number));
  number.addEventListener('change', () => {
    update(number, input);
    number.value = session().params[key];
  });
  return element('div', {class: 'field range-field'}, [element('div', {class: 'range-label'}, [element('label', {for: id, text: label}), element('span', {class: 'range-value'}, [number, suffix])]), input, ...(hint ? [element('p', {class: 'hint', text: hint})] : [])]);
}
function checkboxControl(key, label) {
  const input = element('input', {type: 'checkbox', id: `param-${key}`, checked: session().params[key], onchange: () => { session().params[key] = input.checked; if (key === 'disable_default_bit_rate') renderControls(); }});
  return element('label', {class: 'checkbox-row', for: input.id}, [input, label]);
}
function jsonControl(key, label, hint) {
  const input = element('textarea', {id: `param-${key}`, rows: 3, spellcheck: 'false', oninput: () => { session().params[key] = input.value; }});
  input.value = session().params[key] || '{}';
  return controlField(label, input, hint);
}
function numberControl(key, label, min, max, step = 1, hint = '') {
  const input = element('input', {id: `param-${key}`, type: 'number', min, max, step, value: session().params[key], onchange: () => {
    if (Number.isFinite(input.valueAsNumber) && input.checkValidity()) session().params[key] = input.valueAsNumber;
    else { input.value = session().params[key]; toast(`${label}须在 ${min} 至 ${max} 范围内。`, true); }
  }});
  return controlField(label, input, hint);
}
function inputControl(key, label, hint = '') {
  const input = element('input', {id: `param-${key}`, value: session().params[key] || '', oninput: () => { session().params[key] = input.value; }});
  return controlField(label, input, hint);
}
function controlGroup(title, nodes) {
  return element('details', {class: 'control-group'}, [element('summary', {text: title}), ...nodes]);
}
function renderControls() {
  const p = provider();
  const s = session();
  const info = model();
  const controls = activeControls();
  const supports = key => controls.includes(key);
  const nodes = [], output = [], additional = [];
  $('control-summary').textContent = s.customModel ? '自定义模型的扩展能力请在高级请求参数中配置。' : state.provider === 'qwen' ? (info.kind === 'qwen-audio' ? '使用官方数值控制调整语速、音量与音调。表达指令、SSML 与时间戳根据所选音色开放。' : 'Qwen3 Flash 提供官方音色与语言选择；需要情绪、语速等控制时请选择 Qwen-Audio。') : state.provider === 'doubao' ? '数值控制采用厂商原生刻度；情绪选项按具体音色的官方支持范围展示。' : '语速、音量、音调和音色变换独立配置。情绪支持范围按模型区分。';
  const fallbackRanges = state.provider === 'doubao' ? {speed: [-50, 100, 1], volume: [-50, 100, 1], pitch: [-12, 12, 1]} : {speed: [.5, 2, .05], volume: [.01, 10, .01], pitch: [-12, 12, 1]};
  for (const [key, label] of [['speed', '语速'], ['volume', '音量'], ['pitch', '音调']]) {
    if (supports(key)) {
      const range = info.ranges?.[key] || fallbackRanges[key];
      nodes.push(rangeControl(key, label, ...range, key === 'speed' && state.provider !== 'doubao' ? '×' : '', state.provider === 'doubao' ? '0 为默认值，使用厂商原生刻度。' : ''));
    }
  }
  if (supports('emotion')) {
    const voiceEmotions = selectedVoice()?.emotions;
    const all = info.emotions || p.emotions;
    const emotions = voiceEmotions?.length ? voiceEmotions.map(e => typeof e === 'string' ? all.find(item => item.id === e) || {id: e, name: e} : e) : all;
    nodes.push(selectControl('emotion', '情绪', [['', '自动 / 不指定'], ...emotions.map(e => [e.id, e.name])], state.provider === 'doubao' ? '只列出当前音色在官方表中标明的情绪。' : 'fluent / whisper 仅在官方列明支持的模型中提供。'));
  }
  if (supports('emotion_scale')) nodes.push(rangeControl('emotion_scale', '情绪强度', 1, 5, 1, '', '仅在选择具体情绪时发送。'));
  if (supports('instructions')) {
    const textarea = element('textarea', {id: 'param-instructions', rows: 3, maxlength: 4000, placeholder: '例如：以开心、明亮的语气朗读，语速稍快，句尾自然上扬。', oninput: () => { s.params.instructions = textarea.value; }});
    textarea.value = s.params.instructions;
    nodes.push(controlField('表达指令', textarea));
    const instructions = [['开心', '以开心、轻快的语气朗读，声音明亮，有自然的感染力。'], ['伤心', '以伤心、低落的语气朗读，语速稍慢，停顿自然。'], ['愤怒', '以愤怒、坚定的语气朗读，重音鲜明，保持清晰。'], ['慢速', '以缓慢、清晰的语速朗读，适当增加句间停顿。'], ['快速', '以较快的语速朗读，保持吐字清晰，节奏流畅。']];
    nodes.push(element('div', {class: 'instruction-presets'}, instructions.map(([label, text]) => element('button', {class: 'preset', text: label, onclick: () => { textarea.value = text; s.params.instructions = text; }}))));
  }
  if ((state.provider === 'qwen' && info.kind === 'qwen-audio' && supports('instructions')) || supports('text_tags')) {
    const tag = element('select', {id: 'text-tag'}, [element('option', {value: '', text: '插入情绪 / 发声标签…'}), ...p.textTags.map(item => element('option', {value: item.id, text: `${item.name} ${item.id}`}))]);
    tag.addEventListener('change', () => {
      if (!tag.value) return;
      const text = $('text');
      text.setRangeText(tag.value, text.selectionStart, text.selectionEnd, 'end');
      text.focus(); tag.value = ''; updateCount();
    });
    nodes.push(controlField('局部表达与发声', tag, '在文本光标处插入官方标签，可为不同句子指定情绪、快慢、耳语或笑声。'));
  }
  if (supports('language')) nodes.push(selectControl('language', '文本语言', ['Auto', 'Chinese', 'English', 'German', 'Italian', 'Portuguese', 'Spanish', 'Japanese', 'Korean', 'French', 'Russian'].map(value => [value, value === 'Auto' ? '自动识别' : value])));
  if (supports('language_hints')) nodes.push(selectControl('language_hints', '合成语言', p.languages));
  if (state.provider === 'doubao' && supports('explicit_language')) {
    const languages = selectedVoice()?.languageOptions?.length ? selectedVoice().languageOptions : p.languages;
    nodes.push(selectControl('explicit_language', '明确合成语言', [['', '自动识别'], ...languages]));
  }
  if (state.provider === 'doubao' && supports('explicit_dialect')) {
    const dialects = selectedVoice()?.dialectOptions?.length ? selectedVoice().dialectOptions : p.dialects;
    nodes.push(selectControl('explicit_dialect', '明确方言', [['', '不指定'], ...dialects]));
  }
  if (state.provider === 'doubao' && supports('context_language')) nodes.push(selectControl('context_language', '上下文语言', [['', '自动'], ['id', '印尼语'], ['es', '西班牙语'], ['pt', '葡萄牙语']]));
  if (supports('language_boost')) {
    const languages = (p.languages || []).filter(([value]) => !modelId().startsWith('speech-01-') && !modelId().startsWith('speech-02-') || !['Persian', 'Filipino', 'Tamil'].includes(value));
    nodes.push(selectControl('language_boost', '语言增强', languages));
  }
  if (supports('voice_modify')) additional.push(controlGroup('音色变换与音效', [rangeControl('voice_pitch', '变换 · 音高', -100, 100, 1), rangeControl('intensity', '变换 · 力度', -100, 100, 1), rangeControl('timbre', '变换 · 音色', -100, 100, 1), selectControl('sound_effects', '音效', [['', '无'], ['spacious_echo', '宽阔空间回声'], ['auditorium_echo', '礼堂回声'], ['lofi_telephone', '电话音效'], ['robotic', '机器人']]), element('p', {class: 'hint', text: '启用变换时，非流式输出使用 MP3、WAV 或 FLAC；流式输出使用 MP3。'})]));
  if (supports('mix')) {
    const mixCount = state.provider === 'doubao' ? 3 : 4;
    const mixVoices = state.provider === 'doubao' ? availableVoices().filter(v => v.mixSupported) : p.voices;
    const mixNodes = [checkboxControl('mix_enabled', `启用多音色混合（最多 ${mixCount} 个）`)];
    if (state.provider === 'doubao') mixNodes.push(element('p', {class: 'hint', text: '权重之和须为 100%，混音不支持音量控制。仅列出官方明确支持混音的 1.0 音色。'}));
    for (let index = 0; index < mixCount; index++) {
      const current = s.params.timbre_weights[index] || {voice_id: '', weight: 25};
      const select = element('select', {id: `mix-voice-${index}`, 'aria-label': `混合音色 ${index + 1}`}, [element('option', {value: '', text: `音色 ${index + 1} · 不使用`}), ...mixVoices.map(v => element('option', {value: v.id, text: v.name}))]);
      select.value = current.voice_id;
      const weight = element('input', {type: 'number', min: 1, max: 100, value: current.weight, 'aria-label': `混合音色 ${index + 1} 权重`});
      const save = () => { s.params.timbre_weights[index] = {voice_id: select.value, weight: Number(weight.value)}; };
      select.addEventListener('change', save); weight.addEventListener('change', save);
      mixNodes.push(element('div', {class: 'mix-row'}, [select, weight]));
    }
    additional.push(controlGroup('多音色混合', mixNodes));
  }
  if (supports('format')) output.push(selectControl('format', '输出格式', (info.formats || p.formats).map(value => [value, value.toUpperCase()]), '原始 PCM / μ-law 另封装成 WAV 播放，下载保留原始编码。'));
  if (supports('sample_rate')) {
    let rates = info.sampleRates || p.sampleRates;
    if (['pcmu_raw', 'pcmu_wav'].includes(s.params.format)) rates = [8000];
    if (state.provider === 'doubao' && s.params.format === 'ogg_opus') rates = [48000];
    if (state.provider === 'qwen' && s.params.format === 'opus') rates = rates.filter(rate => ![22050, 44100].includes(rate));
    output.push(selectControl('sample_rate', '采样率', rates.map(value => [value, `${value.toLocaleString()} Hz`])));
  }
  if (supports('bitrate')) {
    const rates = state.provider === 'doubao' ? (s.params.disable_default_bit_rate ? [16000, 32000, 64000, 160000] : [64000, 160000]) : [32000, 64000, 128000, 256000];
    output.push(selectControl('bitrate', state.provider === 'doubao' ? '编码比特率' : 'MP3 比特率', rates.map(value => [value, `${value / 1000} kbps`]), state.provider === 'doubao' ? '对 MP3 / Ogg Opus 发送。' : '只对 MP3 发送。'));
  }
  if (supports('disable_default_bit_rate')) output.push(checkboxControl('disable_default_bit_rate', '允许 16 / 32 kbps 比特率'));
  if (supports('opus_bitrate')) output.push(numberControl('opus_bitrate', 'Opus 比特率（kbps）', 6, 510, 1, '仅对 Opus 发送；Opus 不支持 22050 / 44100 Hz。'));
  if (supports('channel')) output.push(selectControl('channel', '声道', [[1, '单声道'], [2, '双声道']]));
  if (supports('vendor_stream')) output.push(checkboxControl('vendor_stream', '使用厂商流式响应（收齐音频后播放）'));
  if (supports('force_cbr')) output.push(checkboxControl('force_cbr', '流式 MP3 使用固定比特率'));
  if (output.length) additional.push(controlGroup('输出编码与传输', output));
  if (state.provider === 'qwen' && info.kind === 'qwen3') nodes.push(element('p', {class: 'format-note', text: 'Qwen3 Flash：WAV · 24 kHz · 单次最多 600 字符'}));
  if (supports('pronunciation')) {
    const pronunciation = element('textarea', {id: 'param-pronunciation', rows: 3, placeholder: '每行一条，按官方 tone 格式填写\n处理/(chu3)(li3)', oninput: () => { s.params.pronunciation = pronunciation.value.split('\n').map(line => line.trim()).filter(Boolean); }});
    pronunciation.value = s.params.pronunciation.join('\n');
    additional.push(controlGroup('读音与文本处理', [controlField('读音字典', pronunciation, state.provider === 'doubao' ? '每行 原文/读音；最多 5000 条，原文 1–9 字且无空格、无重复。' : '每行 原文/替换文本或官方读音标记。'), ...(supports('normalization') ? [selectControl('normalization_mode', '文本规范化', [['', '关闭 / 不指定'], ['basic', '基础规范化'], ['quality', '高质量规范化（2.8 / 2.6 非流式）']])] : []), ...(supports('latex_read') ? [checkboxControl('latex_read', 'LaTeX 公式朗读（启用时强制中文语言增强）')] : []), ...(state.provider === 'minimax' ? [element('p', {class: 'hint', text: '在文本中用 <#0.5#> 插入 0.5 秒停顿。停顿范围为 0.01–99.99 秒，不能连续使用。'})] : [])]));
  }
  const qwenAdvanced = [];
  if (supports('ssml')) qwenAdvanced.push(checkboxControl('ssml', '将文本作为 SSML 解析（使用 <speak> 包裹）'));
  if (supports('hot_fix')) qwenAdvanced.push(jsonControl('hot_fix', '读音与文本替换', '示例：{"pronunciation":[{"重庆":"chong2 qing4"}],"replace":[{"本日":"今天"}]}'));
  if (supports('seed')) qwenAdvanced.push(numberControl('seed', '随机种子', 0, 65535));
  if (supports('timestamps')) qwenAdvanced.push(checkboxControl('timestamps', state.provider === 'doubao' ? '生成 1.0 时间戳（中英、文本规范化后的词）' : '生成字词时间戳（自动使用厂商 SSE 输出）'));
  if (qwenAdvanced.length) additional.push(controlGroup('SSML、读音与复现', qwenAdvanced));
  if (supports('subtitle')) additional.push(controlGroup('字幕', [checkboxControl('subtitle', '生成字幕'), selectControl('subtitle_type', '字幕粒度', [['sentence', '句级'], ['word', '词级'], ['word_streaming', '词级流式（同时启用厂商流式）']])]));
  if (supports('aigc')) additional.push(controlGroup('音频标识', [checkboxControl('aigc', '嵌入官方 AIGC 标识'), ...(state.provider === 'qwen' ? [inputControl('aigc_propagator', '传播者标识（留空使用官方默认）'), inputControl('aigc_propagate_id', '传播内容标识（留空使用官方默认）')] : [])]));
  if (state.provider === 'doubao') {
    const textNodes = [];
    if (supports('disable_markdown_filter')) textNodes.push(checkboxControl('disable_markdown_filter', '解析并移除 Markdown 标记'), element('p', {class: 'hint', text: '对应官方 disable_markdown_filter=true；关闭时保留原文，LaTeX 处理需要开启。'}));
    if (supports('disable_emoji_filter')) textNodes.push(checkboxControl('disable_emoji_filter', 'disable_emoji_filter'), element('p', {class: 'hint', text: '当前文档称 true 为解析 / 移除 Emoji，历史 V3 文档称 true 为保留；存在官方语义冲突，请按实际返回试听。'}));
    if (supports('enable_latex_tn')) textNodes.push(checkboxControl('enable_latex_tn', '启用 LaTeX 文本处理'));
    if (supports('latex_parser')) textNodes.push(selectControl('latex_parser', 'LaTeX 解析器', [['', '默认'], ['v2', 'v2（改进公式朗读，可能增加延迟）']]));
    if (supports('max_length_to_filter_parenthesis')) textNodes.push(numberControl('max_length_to_filter_parenthesis', '过滤括号内容的最大字数', 0, 100, 1, '0 为关闭；采用官方建议范围 0–100，超出长度的括号内容正常朗读。'));
    if (supports('unsupported_char_ratio_thresh')) textNodes.push(numberControl('unsupported_char_ratio_thresh', '不支持字符的比例阈值', 0, 1, .01, '默认 0.3，超过阈值时厂商拒绝合成。'));
    if (supports('enable_auto_language_recognition')) textNodes.push(checkboxControl('enable_auto_language_recognition', '按首句自动识别语言'), element('p', {class: 'hint', text: '明确指定的语言优先；实际语言范围以当前音色为准。'}));
    if (supports('enable_language_detector')) textNodes.push(checkboxControl('enable_language_detector', '旧版语言检测（enable_language_detector）'));
    if (textNodes.length) additional.push(controlGroup('文本处理与语言识别', textNodes));
    const timing = [];
    if (supports('silence_duration')) timing.push(numberControl('silence_duration', '全文末尾静音（毫秒）', 0, 30000));
    if (supports('enable_subtitle')) timing.push(checkboxControl('enable_subtitle', '生成 2.0 字幕数据（中英）'));
    if (supports('section_id')) timing.push(inputControl('section_id', '连续请求会话 ID', '关联连续请求的上下文，留空不指定。'));
    if (supports('silence_trim')) timing.push(inputControl('mute_cut_threshold', '静音裁剪阈值', '官方字符串值，例如 400；须同时填写保留时长。'), inputControl('mute_cut_remain_ms', '裁剪后保留静音（毫秒）', '官方字符串值，例如 50；仅适用于 1.0。'));
    if (supports('cache_config')) timing.push(selectControl('cache_mode', '厂商音频缓存', [['', '不指定'], ['on', '启用'], ['off', '关闭']], '同文本缓存约 1 小时；缓存结果不带时间戳 / 字幕。'));
    if (timing.length) additional.push(controlGroup('停顿、字幕与缓存', timing));
    if (supports('aigc_watermark')) additional.push(controlGroup('音频标识', [checkboxControl('aigc_watermark', '添加可听见的 AIGC 节奏水印'), checkboxControl('aigc_metadata_enabled', '嵌入 AIGC 元数据（MP3 / WAV / Ogg Opus）'), inputControl('content_producer', '内容生产者'), inputControl('produce_id', '生产内容 ID'), inputControl('content_propagator', '内容传播者'), inputControl('propagate_id', '传播内容 ID')]));
  }
  $('controls').replaceChildren(...nodes, ...additional);
}
function getJob() {
  const s = session();
  let extra;
  try { extra = JSON.parse(s.extra); }
  catch { throw new Error('高级请求参数不是有效 JSON，请检查逗号和引号。'); }
  if (!extra || Array.isArray(extra) || typeof extra !== 'object') throw new Error('高级参数必须是 JSON 对象。');
  const params = structuredClone(s.params);
  const controls = activeControls();
  if (!controls.includes('instructions')) params.instructions = '';
  for (const key of ['ssml', 'timestamps']) if (!controls.includes(key)) params[key] = false;
  if (!controls.includes('emotion')) params.emotion = '';
  if (state.provider === 'doubao') {
    if (!controls.includes('enable_subtitle')) params.enable_subtitle = false;
    if (!controls.includes('pronunciation')) params.pronunciation = [];
    if (!controls.includes('explicit_dialect')) params.explicit_dialect = '';
    if (params.cache_mode) params.cache_config = {text_type: 1, use_cache: params.cache_mode === 'on'};
    if (params.aigc_metadata_enabled) params.aigc_metadata = {enable: true, content_producer: params.content_producer, produce_id: params.produce_id, content_propagator: params.content_propagator, propagate_id: params.propagate_id};
  }
  return {provider: state.provider, model: s.customModel || modelId(), voice: s.customVoice || s.voice, text: $('text').value.trim(), params, extra};
}
function setBusy(value, label = '正在合成…') {
  state.busy = value;
  $('synthesize').disabled = value;
  $('synthesize').textContent = value ? label : '生成并试听 ↗';
  $('compare-run').disabled = value || !state.queue.length;
  $('queue-add').disabled = value;
}
function providerName(id) { return state.catalog.providers.find(p => p.id === id)?.name || id; }
function voiceName(job) { return state.catalog.providers.find(p => p.id === job.provider)?.voices.find(v => v.id === job.voice)?.name || job.voice; }
function renderQueue() {
  $('queue-count').textContent = state.queue.length;
  $('compare-run').disabled = state.busy || !state.queue.length;
  $('queue-list').replaceChildren(...state.queue.map((job, index) => element('article', {class: 'queue-item'}, [element('span', {class: 'queue-index', text: String(index + 1).padStart(2, '0')}), element('div', {class: 'queue-info'}, [element('strong', {text: `${providerName(job.provider)} · ${voiceName(job)}`}), element('small', {text: job.model}), element('small', {text: job.params.instructions || (job.params.emotion ? `情绪：${job.params.emotion}` : '默认表达')})]), element('button', {class: 'icon-button', 'aria-label': `移除第 ${index + 1} 组对比`, text: '×', onclick: () => { state.queue.splice(index, 1); renderQueue(); }})])));
  if (!state.queue.length) $('queue-list').append(element('p', {class: 'empty', text: '将配置加入对比，再切换音色或厂商。最多保存 6 组。'}));
}
function renderResults() {
  $('result-count').textContent = state.results.length;
  $('results').replaceChildren(...state.results.map(result => {
    const payload = element('pre', {text: JSON.stringify({params: result.params, payload: result.payload, vendorMetadata: result.vendorMetadata || {}}, null, 2)});
    const details = element('details', {class: 'result-details'}, [element('summary', {text: '查看请求、用量与字幕 / 时间戳'}), payload]);
    const subtitleFile = result.vendorMetadata?.subtitleFile;
    if (typeof subtitleFile === 'string') {
      try {
        const url = new URL(subtitleFile);
        if (url.protocol === 'https:' && !url.username && !url.password) details.append(element('a', {class: 'download-link', href: url.href, target: '_blank', rel: 'noopener noreferrer', text: '打开官方字幕 JSON ↗'}));
      } catch {}
    }
    const info = `${result.model} · ${result.sampleRate / 1000} kHz · ${result.originalFormat.toUpperCase()} · ${(result.bytes / 1024).toFixed(1)} KiB`;
    const audio = element('audio', {controls: '', preload: 'none', src: result.audioUrl, 'aria-label': `${providerName(result.provider)} ${voiceName(result)}试听`});
    audio.addEventListener('error', () => { audio.parentElement.querySelector('.audio-error').hidden = false; });
    return element('article', {class: 'result-card'}, [
      element('div', {class: 'result-heading'}, [element('div', {}, [element('span', {class: 'result-provider', text: providerName(result.provider)}), element('h3', {text: voiceName(result)})]), element('div', {class: 'result-meta'}, [element('span', {text: `耗时 ${result.elapsed.toFixed(2)} s`}), element('small', {text: new Date(result.createdAt * 1000).toLocaleTimeString()})])]),
      element('p', {class: 'result-text', text: result.text}), audio,
      element('p', {class: 'audio-error hint', hidden: true, text: '音频可能已释放，或浏览器不支持该编码。请尝试下载，或重新生成 WAV / MP3。'}),
      element('div', {class: 'result-bottom'}, [element('small', {text: info}), element('a', {class: 'download-link', href: result.downloadUrl, text: '下载音频 ↓'})]), details
    ]);
  }));
  if (!state.results.length) $('results').append(element('div', {class: 'empty-result'}, [element('span', {'aria-hidden': 'true', text: '〰'}), element('p', {text: '下一段好声音，从这里开始。'}), element('small', {text: '生成后可播放、下载，并查看每次使用的参数。'})]));
}
async function generateOne() {
  try {
    const job = getJob();
    if (!job.text) throw new Error('请先输入要合成的文本。');
    if (!configuredFor(job)) { $('settings-dialog').showModal(); throw new Error('请先配置同地域的厂商凭据；Qwen-Audio 还需要业务空间 ID。'); }
    setBusy(true);
    const result = await api('/api/synthesize', job);
    state.results.unshift(result);
    state.results = state.results.slice(0, 30);
    renderResults();
    $('results').scrollIntoView({behavior: 'smooth', block: 'start'});
    toast('已生成。点击播放器试听。');
  } catch (error) { toast(error.message, true); }
  finally { setBusy(false); }
}
async function compareAll() {
  const text = $('text').value.trim();
  if (!text) return toast('请先输入用于对比的文本。', true);
  const jobs = structuredClone(state.queue);
  if (!jobs.length) return;
  const missing = [...new Set(jobs.filter(job => !configuredFor(job)).map(job => providerName(job.provider)))];
  if (missing.length) { $('settings-dialog').showModal(); return toast(`请先配置：${missing.join('、')}`, true); }
  setBusy(true, '正在生成对比…');
  const errors = [];
  let success = 0;
  try {
    for (let start = 0; start < jobs.length; start += 3) {
      const batch = jobs.slice(start, start + 3);
      const settled = await Promise.allSettled(batch.map(job => api('/api/synthesize', {...job, text})));
      settled.forEach((result, index) => {
        if (result.status === 'fulfilled') { state.results.unshift(result.value); success++; }
        else errors.push(`${providerName(batch[index].provider)} / ${voiceName(batch[index])}：${result.reason.message}`);
      });
      state.results = state.results.slice(0, 30);
      renderResults();
    }
    if (errors.length) {
      const message = element('article', {class: 'batch-error'}, [element('strong', {text: `${success} 组成功，${errors.length} 组失败`}), ...errors.map(message => element('p', {text: message}))]);
      $('results').prepend(message);
      toast(`${success} 组成功，${errors.length} 组失败，详细信息已显示在试听记录中。`, true);
    } else toast(`已生成 ${success} 组对比。`);
    $('results').scrollIntoView({behavior: 'smooth', block: 'start'});
  } finally { setBusy(false); }
}
function renderSettings() {
  $('settings-forms').replaceChildren(...state.catalog.providers.map(p => {
    const status = state.settings.providers[p.id];
    const fieldNodes = {};
    const fields = p.credentialFields.map(field => {
      const input = element('input', {id: `credential-${p.id}-${field.id}`, type: field.secret ? 'password' : 'text', autocomplete: 'off', placeholder: status.fields[field.id] ? '已配置，留空保留' : field.default || '尚未配置', maxlength: 4096});
      fieldNodes[field.id] = input;
      return controlField(field.label, input);
    });
    const region = element('select', {id: `region-${p.id}`}, p.regions.map(r => element('option', {value: r.id, text: r.name})));
    region.value = status.region;
    const save = element('button', {class: 'button secondary small', type: 'submit', text: '保存到本机'});
    const clear = element('button', {class: 'text-button', type: 'button', text: '清除凭据', onclick: async () => {
      try {
        state.settings = await api('/api/settings', {provider: p.id, region: region.value, clear: true});
        renderSettings(); renderSelection(); toast(`${p.name} 凭据已清除`);
      } catch (error) { $('settings-message').textContent = error.message; }
    }});
    const form = element('form', {class: 'connection-form', onsubmit: async event => {
      event.preventDefault(); save.disabled = true;
      const values = Object.fromEntries(Object.entries(fieldNodes).map(([key, node]) => [key, node.value]));
      if (p.id === 'doubao' && !values.resource_id && !status.fields.resource_id) values.resource_id = 'auto';
      try {
        state.settings = await api('/api/settings', {provider: p.id, region: region.value, fields: values});
        for (const input of Object.values(fieldNodes)) input.value = '';
        renderSettings(); renderSelection();
        $('settings-message').textContent = `${p.name} 连接设置已保存到本机，重启后自动加载。凭据是否有效将在实际请求时由厂商验证。`;
      } catch (error) { $('settings-message').textContent = error.message; }
      finally { save.disabled = false; }
    }}, [element('div', {class: 'connection-title'}, [element('h3', {text: p.name}), element('span', {class: `status-badge ${status.configured ? 'connected' : ''}`, text: status.configured ? '已配置' : '未配置'})]), controlField('服务地域', region), ...fields, element('div', {class: 'connection-actions'}, [save, clear])]);
    return form;
  }));
}
async function initialize() {
  try {
    [state.catalog, state.settings] = await Promise.all([api('/api/catalog'), api('/api/settings')]);
    $('catalog-notice').textContent = state.catalog.notice;
    renderSelection(); renderSettings(); renderQueue(); updateCount();
  } catch (error) { $('catalog-notice').textContent = error.message; $('synthesize').disabled = true; }
}

$('text').addEventListener('input', updateCount);
document.querySelectorAll('[data-sample]').forEach(button => button.addEventListener('click', () => { $('text').value = samples[button.dataset.sample]; updateCount(); }));
$('model').addEventListener('change', () => { state.models[state.provider] = $('model').value; $('voice-search').value = ''; renderSelection(); });
$('voice-search').addEventListener('input', renderVoices);
$('custom-model').addEventListener('input', () => { session().customModel = $('custom-model').value.trim(); renderControls(); updateSummary(); });
$('custom-voice').addEventListener('input', () => { session().customVoice = $('custom-voice').value.trim(); updateSummary(); });
$('extra-json').addEventListener('input', () => { session().extra = $('extra-json').value; $('request-preview').hidden = true; });
$('preview-button').addEventListener('click', async () => {
  try { const result = await api('/api/preview', getJob()); $('request-preview').textContent = JSON.stringify(result.payload, null, 2); $('request-preview').hidden = false; }
  catch (error) { toast(error.message, true); }
});
$('synthesize').addEventListener('click', generateOne);
$('queue-add').addEventListener('click', () => {
  try {
    if (state.queue.length >= 6) throw new Error('最多保存 6 组对比配置。');
    const job = getJob();
    if (!job.voice) throw new Error('请选择音色。');
    delete job.text;
    state.queue.push(job); renderQueue(); toast('已加入对比台，生成时统一使用当前文本。');
  } catch (error) { toast(error.message, true); }
});
$('compare-run').addEventListener('click', compareAll);
$('clear-results').addEventListener('click', () => { document.querySelectorAll('audio').forEach(audio => audio.pause()); state.results = []; renderResults(); });
$('settings-open').addEventListener('click', () => { $('settings-message').textContent = ''; $('settings-dialog').showModal(); });
$('settings-close').addEventListener('click', () => $('settings-dialog').close());
$('settings-dialog').addEventListener('close', () => { $('settings-dialog').querySelectorAll('input').forEach(input => { input.value = ''; }); });
$('refresh-voices').addEventListener('click', async () => {
  const button = $('refresh-voices'); button.disabled = true; button.textContent = '正在刷新…';
  try {
    const result = await api('/api/voices/refresh', {});
    state.catalog.providers.find(p => p.id === 'minimax').voices = result.voices;
    if (state.provider === 'minimax') renderSelection();
    toast(`已获取 ${result.count} 个官方系统音色。`);
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = '刷新系统音色'; }
});
document.addEventListener('play', event => { if (event.target.tagName === 'AUDIO') document.querySelectorAll('audio').forEach(audio => { if (audio !== event.target) audio.pause(); }); }, true);
try { const theme = localStorage.getItem('tts-studio-theme'); if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme; } catch {}
$('theme-toggle').addEventListener('click', () => {
  const current = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const theme = current === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('tts-studio-theme', theme); } catch {}
});
initialize();
