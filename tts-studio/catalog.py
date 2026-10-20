"""Official voice snapshots and model-specific capability metadata."""
import json
from pathlib import Path

VERIFIED_ON = "2026-10-19"
DATA_DIR = Path(__file__).resolve().parent / "data"


def voices_from(filename):
    path = DATA_DIR / filename
    if not path.exists():
        return []
    records = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(records, list):
        raise ValueError(f"Invalid voice catalogue: {filename}")
    return records


QWEN_AUDIO_CONTROLS = ["speed", "volume", "pitch", "instructions", "format", "sample_rate", "opus_bitrate", "language_hints", "seed", "ssml", "hot_fix", "timestamps", "aigc"]
DOUBAO_BASE_CONTROLS = ["speed", "volume", "pitch", "format", "sample_rate", "bitrate", "disable_default_bit_rate", "silence_duration", "enable_auto_language_recognition", "explicit_language", "explicit_dialect", "context_language", "disable_markdown_filter", "disable_emoji_filter", "enable_latex_tn", "latex_parser", "max_length_to_filter_parenthesis", "aigc_watermark", "aigc_metadata", "unsupported_char_ratio_thresh", "cache_config"]
DOUBAO_LANGUAGES = [[key, label] for key, label in [("zh-cn", "中文"), ("en", "英语"), ("ja", "日语"), ("es-mx", "墨西哥西班牙语"), ("id", "印尼语"), ("pt-br", "巴西葡萄牙语"), ("pt", "葡萄牙语"), ("ko", "韩语"), ("it", "意大利语"), ("de", "德语"), ("fr", "法语"), ("th", "泰语"), ("vi", "越南语"), ("ru", "俄语"), ("fil", "菲律宾语"), ("ms", "马来语"), ("ar", "阿拉伯语"), ("pl", "波兰语"), ("tr", "土耳其语"), ("sv", "瑞典语"), ("nl", "荷兰语"), ("no", "挪威语"), ("uk", "乌克兰语"), ("fi", "芬兰语"), ("da", "丹麦语"), ("cs", "捷克语"), ("hu", "匈牙利语"), ("el", "希腊语"), ("ro", "罗马尼亚语"), ("hi", "印地语"), ("es-es", "西班牙语")]]
DOUBAO_DIALECTS = [[key, label] for key, label in [("beijing", "北京"), ("dongbei", "东北"), ("henan", "河南"), ("shaanxi", "陕西"), ("shanghai", "上海"), ("sichuan", "四川"), ("tianjin", "天津"), ("yue", "粤语")]]
DOUBAO_RATES = [8000, 16000, 22050, 24000, 32000, 44100, 48000]
MINIMAX_CONTROLS = ["speed", "volume", "pitch", "emotion", "format", "sample_rate", "bitrate", "channel", "language_boost", "pronunciation", "normalization", "latex_read", "voice_modify", "subtitle", "vendor_stream", "force_cbr", "mix", "aigc"]
MINIMAX_FORMATS = ["mp3", "pcm", "flac", "wav", "pcmu_raw", "pcmu_wav", "opus"]
MINIMAX_RATES = [8000, 16000, 22050, 24000, 32000, 44100]
MINIMAX_LANGUAGES = [[value, "自动识别" if value == "auto" else "粤语" if value == "Chinese,Yue" else value] for value in ["auto", "Chinese", "Chinese,Yue", "English", "Arabic", "Russian", "Spanish", "French", "Portuguese", "German", "Turkish", "Dutch", "Ukrainian", "Vietnamese", "Indonesian", "Japanese", "Italian", "Korean", "Thai", "Polish", "Romanian", "Greek", "Czech", "Finnish", "Hindi", "Bulgarian", "Danish", "Hebrew", "Malay", "Persian", "Slovak", "Swedish", "Croatian", "Filipino", "Hungarian", "Norwegian", "Slovenian", "Catalan", "Nynorsk", "Tamil", "Afrikaans"]]
MINIMAX_EMOTIONS = [{"id": key, "name": label} for key, label in [("happy", "开心"), ("sad", "伤心"), ("angry", "愤怒"), ("fearful", "恐惧"), ("disgusted", "厌恶"), ("surprised", "惊讶"), ("calm", "平静"), ("fluent", "生动流畅"), ("whisper", "耳语")]]

CATALOG = {
    "version": VERIFIED_ON,
    "verification": "official-docs",
    "notice": "音色与参数依据官方文档整理，核对日期 2026-10-19。界面按模型、音色和地域展示能力；实际可用性还取决于账号权限。",
    "providers": [
        {
            "id": "doubao", "name": "豆包", "subtitle": "火山引擎 · 语音合成",
            "docs": "https://docs.volcengine.com/docs/6561/2528925",
            "voiceDocs": "https://docs.volcengine.com/docs/6561/1257544",
            "regions": [{"id": "cn", "name": "中国大陆"}],
            "credentialFields": [
                {"id": "app_id", "label": "App ID（旧版 Access Key 鉴权填写）", "secret": False, "optional": True},
                {"id": "api_key", "label": "新版 API Key / 旧版 Access Key", "secret": True},
                {"id": "resource_id", "label": "Resource ID（auto 跟随模型）", "secret": False, "default": "auto"},
            ],
            "models": [
                {"id": "seed-tts-2.0", "name": "Seed TTS 2.0", "controls": DOUBAO_BASE_CONTROLS + ["instructions", "enable_subtitle", "pronunciation", "section_id"], "instructionMode": "context", "formats": ["mp3", "ogg_opus", "pcm", "wav"], "sampleRates": [8000, 16000, 22050, 24000, 32000, 44100, 48000], "verified": True},
                *[{"id": mid, "name": name, "controls": DOUBAO_BASE_CONTROLS + ["emotion", "emotion_scale", "timestamps", "ssml", "silence_trim", "enable_language_detector", "mix"], "formats": ["mp3", "ogg_opus", "pcm", "wav"], "sampleRates": [8000, 16000, 22050, 24000, 32000, 44100, 48000], "verified": True}
                  for mid, name in [("seed-tts-1.0", "Seed TTS 1.0（字符计费）"), ("seed-tts-1.0-concurr", "Seed TTS 1.0（并发计费）")]],
            ],
            "voices": voices_from("doubao-voices.json"),
            "emotions": [{"id": key, "name": label} for key, label in [("happy", "开心"), ("sad", "伤心"), ("angry", "愤怒"), ("fearful", "恐惧"), ("surprised", "惊讶"), ("neutral", "中性")]],
            "notes": "1.0 的情绪由具体音色支持范围决定；2.0 使用表达指令。手动 Resource ID 会覆盖所选资源类型。",
            "formats": ["mp3", "ogg_opus", "pcm", "wav"], "sampleRates": DOUBAO_RATES,
            "languages": DOUBAO_LANGUAGES, "dialects": DOUBAO_DIALECTS,
        },
        {
            "id": "minimax", "name": "MiniMax", "subtitle": "Speech · 多语言语音",
            "docs": "https://platform.minimax.cn/docs/api-reference/speech-t2a-http",
            "voiceDocs": "https://platform.minimax.cn/docs/faq/system-voice-id",
            "regions": [{"id": "cn", "name": "中国大陆"}, {"id": "intl", "name": "国际站"}],
            "credentialFields": [{"id": "api_key", "label": "API Key", "secret": True}],
            "models": [{"id": mid, "name": mid.replace("speech-", "Speech ").replace("-hd", " HD").replace("-turbo", " Turbo"), "controls": MINIMAX_CONTROLS + (["text_tags"] if mid.startswith("speech-2.8-") else []), "formats": MINIMAX_FORMATS, "sampleRates": MINIMAX_RATES, "maxText": 9999, "verified": True,
                        "defaults": {"format": "mp3", "sample_rate": 32000},
                        "ranges": {"speed": [.5, 2, .05], "volume": [.01, 10, .01], "pitch": [-12, 12, 1]},
                        "emotions": MINIMAX_EMOTIONS if mid.startswith("speech-2.6-") else MINIMAX_EMOTIONS[:7]}
                       for mid in ["speech-2.8-hd", "speech-2.8-turbo", "speech-2.6-hd", "speech-2.6-turbo", "speech-02-hd", "speech-02-turbo", "speech-01-hd", "speech-01-turbo"]],
            "languages": MINIMAX_LANGUAGES,
            "textTags": [{"id": tag, "name": label} for tag, label in [("(laughs)", "笑声"), ("(chuckle)", "轻笑"), ("(coughs)", "咳嗽"), ("(clear-throat)", "清嗓"), ("(groans)", "呻吟"), ("(breath)", "换气"), ("(pant)", "喘气"), ("(inhale)", "吸气"), ("(exhale)", "呼气"), ("(gasps)", "倒吸气"), ("(sniffs)", "吸鼻子"), ("(sighs)", "叹气"), ("(snorts)", "喷鼻息"), ("(burps)", "打嗝"), ("(lip-smacking)", "咂嘴"), ("(humming)", "哼唱"), ("(hissing)", "嘶嘶声"), ("(emm)", "嗯"), ("(sneezes)", "喷嚏")]],
            "voices": voices_from("minimax-voices.json"),
            "emotions": [{"id": key, "name": label} for key, label in [("happy", "开心"), ("sad", "伤心"), ("angry", "愤怒"), ("fearful", "恐惧"), ("disgusted", "厌恶"), ("surprised", "惊讶"), ("calm", "平静")]],
            "notes": "可从账号接口刷新官方系统音色。音色变换与语速、音量、音调分别配置。",
            "formats": MINIMAX_FORMATS, "sampleRates": MINIMAX_RATES,
        },
        {
            "id": "qwen", "name": "Qwen", "subtitle": "阿里云百炼 · 通义语音",
            "docs": "https://help.aliyun.com/zh/model-studio/qwen-audio-tts-http-api",
            "voiceDocs": "https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list",
            "regions": [{"id": "cn", "name": "北京"}, {"id": "intl", "name": "新加坡"}],
            "credentialFields": [
                {"id": "api_key", "label": "同地域的百炼 API Key", "secret": True},
                {"id": "workspace_id", "label": "业务空间 ID（Qwen-Audio 必填）", "secret": False, "optional": True},
            ],
            "models": [
                {"id": mid, "name": name, "kind": "qwen-audio", "controls": QWEN_AUDIO_CONTROLS,
                 "formats": ["mp3", "wav", "pcm", "opus"], "sampleRates": [8000, 12000, 16000, 22050, 24000, 44100, 48000],
                 "defaults": {"speed": 1, "volume": 50, "pitch": 1, "format": "wav", "sample_rate": 24000},
                 "ranges": {"speed": [.5, 2, .05], "volume": [0, 100, 1], "pitch": [.5, 2, .05]},
                 "docs": "https://help.aliyun.com/zh/model-studio/qwen-audio-tts-http-api", "voiceDocs": "https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list", "verified": True}
                for mid, name in [("qwen-audio-3.1-tts-flash", "Qwen-Audio 3.1 TTS Flash"), ("qwen-audio-3.0-tts-flash", "Qwen-Audio 3.0 TTS Flash"), ("qwen-audio-3.0-tts-plus", "Qwen-Audio 3.0 TTS Plus")]
            ] + [
                {"id": "qwen3-tts-flash", "name": "Qwen3 TTS Flash", "kind": "qwen3", "controls": ["language"], "formats": ["wav"], "sampleRates": [24000], "maxText": 600,
                 "defaults": {"format": "wav", "sample_rate": 24000}, "docs": "https://help.aliyun.com/zh/model-studio/qwen-tts-api", "voiceDocs": "https://help.aliyun.com/zh/model-studio/qwen-tts-voice-list", "verified": True},
            ],
            "voices": voices_from("qwen-voices.json") + voices_from("qwen-base-voices.json"),
            "emotions": [],
            "textTags": [{"id": tag, "name": label} for tag, label in [
                ("[sad]", "伤心"), ("[amazed]", "惊奇"), ("[deep and loud shouting]", "低沉大喊"), ("[trembling]", "颤抖"), ("[angry]", "愤怒"), ("[excited]", "兴奋"),
                ("[sarcastic]", "讽刺"), ("[curious]", "好奇"), ("[like dracula]", "吸血鬼风格"), ("[bored]", "无聊"), ("[tired]", "疲惫"), ("[scornful]", "轻蔑"),
                ("[shouting]", "喊叫"), ("[asmr]", "ASMR"), ("[panicked]", "慌张"), ("[mischievously]", "调皮"), ("[empathetic]", "共情"), ("[whispers]", "耳语"),
                ("[reluctantly]", "不情愿"), ("[crying]", "哭泣"), ("[serious]", "严肃"), ("[very slowly]", "很慢"), ("[very fast]", "很快"),
                ("[gasp]", "倒吸气"), ("[sighing]", "叹气"), ("[clears throat]", "清嗓"), ("[giggles]", "轻笑"), ("[laughing]", "笑声"), ("[cough]", "咳嗽"), ("[snorts]", "哼声")]],
            "languages": [["", "自动"], ["zh", "中文"], ["en", "英语"], ["fr", "法语"], ["de", "德语"], ["ja", "日语"], ["ko", "韩语"], ["ru", "俄语"], ["pt", "葡萄牙语"], ["th", "泰语"], ["id", "印尼语"], ["vi", "越南语"], ["es", "西班牙语"], ["it", "意大利语"], ["ms", "马来语"], ["fil", "菲律宾语"], ["ar", "阿拉伯语"]],
            "notes": "Qwen-Audio 使用业务空间接口，支持原生语速、音调、音量和表达指令；部分音色不支持指令或 SSML。Qwen3 Flash 使用独立接口和 48 个官方音色，不提供这些数值控制。",
            "formats": ["mp3", "wav", "pcm", "opus"], "sampleRates": [8000, 12000, 16000, 22050, 24000, 44100, 48000],
        },
    ],
}


def model_info(provider, model):
    vendor = next(p for p in CATALOG["providers"] if p["id"] == provider)
    return next((item for item in vendor["models"] if item["id"] == model), {})


def effective_controls(provider, model, voice):
    info = model_info(provider, model)
    controls = set(info.get("controls", []))
    record = voice_info(provider, voice)
    caps = record.get("capabilities", {})
    for capability in ("instructions", "ssml", "timestamps"):
        if caps.get(capability) is False:
            controls.discard(capability)
    if provider == "doubao":
        if not record.get("emotions"):
            controls -= {"emotion", "emotion_scale"}
        if record and "指令遵循" not in str(record.get("catalogueEntries", [])):
            controls.discard("instructions")
        if record and not doubao_dialects(record):
            controls.discard("explicit_dialect")
        language = record.get("language", "")
        if record and ("口音" in language or not any(word in language for word in ("中文", "英语"))):
            controls -= {"timestamps", "enable_subtitle", "pronunciation", "ssml"}
    return controls


def doubao_dialects(record):
    language = record.get("language", "")
    return [key for key, label in DOUBAO_DIALECTS if "方言" in language and label in language]


def doubao_languages(record):
    if not record:
        return DOUBAO_LANGUAGES
    language = record.get("language", "")
    if record["id"].startswith("zh_") and "uranus_bigtts" in record["id"] and "30+" in language:
        return DOUBAO_LANGUAGES
    aliases = {"en": "英语", "es-mx": "西语", "es-es": "西班牙语", "id": "印尼", "pt-br": "葡萄牙", "pt": "葡萄牙"}
    return [[key, label] for key, label in DOUBAO_LANGUAGES if label in language or aliases.get(key, "不存在的语种") in language]


def voice_info(provider, voice):
    vendor = next(p for p in CATALOG["providers"] if p["id"] == provider)
    return next((item for item in vendor["voices"] if item["id"] == voice), {})


for _voice in CATALOG["providers"][0]["voices"]:
    _voice["languageOptions"] = doubao_languages(_voice)
    _voice["dialectOptions"] = [item for item in DOUBAO_DIALECTS if item[0] in doubao_dialects(_voice)]
    _voice["mixSupported"] = any(entry.get("mixSupported") is True for entry in _voice.get("catalogueEntries", []))
    if _voice.get("models"):
        _supported = effective_controls("doubao", _voice["models"][0], _voice["id"])
        _voice["capabilities"] = {key: key in _supported for key in ("instructions", "timestamps", "enable_subtitle", "pronunciation", "ssml", "explicit_dialect")}
