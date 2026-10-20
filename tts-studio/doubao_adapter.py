"""Seed TTS request controls using the official HTTP additions schema."""
import json


DOUBAO_LANGUAGES = {
    "zh-cn", "en", "ja", "es-mx", "id", "pt-br", "pt", "ko", "it", "de", "fr", "th", "vi", "ru", "fil", "ms", "ar", "pl", "tr", "sv", "nl", "no", "uk", "fi", "da", "cs", "hu", "el", "ro", "hi", "es-es"
}
DOUBAO_DIALECTS = {"beijing", "dongbei", "henan", "shaanxi", "shanghai", "sichuan", "tianjin", "yue"}


def _json_object(value, key, error):
    if value in (None, "", {}):
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            raise error(f"{key} 必须是有效 JSON 对象。") from None
    if not isinstance(value, dict):
        raise error(f"{key} 必须是 JSON 对象。")
    return value


def _string_list(value, key, error, limit=5000):
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        value = [line.strip() for line in value.splitlines() if line.strip()]
    if not isinstance(value, list) or len(value) > limit or not all(isinstance(item, str) and item for item in value):
        raise error(f"{key} 必须是字符串数组。")
    return value


def build(model, voice, text, params, controls, record, number, string, error):
    controls = set(controls)
    for key in ("ssml", "timestamps", "enable_subtitle", "disable_default_bit_rate", "enable_auto_language_recognition", "enable_language_detector", "disable_markdown_filter", "disable_emoji_filter", "enable_latex_tn", "aigc_watermark", "mix_enabled"):
        if key in params and not isinstance(params[key], bool):
            raise error(f"{key} 必须是布尔值。")
    for key in ("explicit_dialect", "section_id", "pronunciation", "mute_cut_threshold", "mute_cut_remain_ms"):
        capability = "silence_trim" if key.startswith("mute_cut_") else key
        if params.get(key) and capability not in controls:
            raise error(f"当前模型或音色未声明支持 {key}。")
    audio = {"format": params.get("format", "mp3"), "sample_rate": number(params, "sample_rate", 24000, 8000, 48000, True)}
    additions = {}
    for key, native in (("speed", "speech_rate"), ("volume", "loudness_rate")):
        if key in controls:
            audio[native] = number(params, key, 0, -50, 100)
    if "pitch" in controls:
        additions["post_process"] = {"pitch": number(params, "pitch", 0, -12, 12, True)}
    emotion = string(params, "emotion", 50)
    if emotion:
        if "emotion" not in controls:
            raise error("所选豆包模型或音色未声明支持枚举情绪，请使用其表达指令。")
        allowed = {item if isinstance(item, str) else item.get("id") for item in record.get("emotions", [])}
        if not allowed or emotion not in allowed:
            raise error("所选情绪不在该音色官方支持列表中。")
        audio.update(emotion=emotion, emotion_scale=number(params, "emotion_scale", 4, 1, 5))
    instructions = string(params, "instructions", 4000)
    if instructions:
        if "instructions" not in controls:
            raise error("表达上下文仅适用于 Seed TTS 2.0。")
        additions["context_texts"] = [instructions]
    ssml = params.get("ssml", False)
    if not isinstance(ssml, bool):
        raise error("ssml 必须是布尔值。")
    if ssml and "ssml" not in controls:
        raise error("当前豆包模型不支持 SSML。")
    for key, native in (("timestamps", "enable_timestamp"), ("enable_subtitle", "enable_subtitle")):
        if key in controls and params.get(key):
            if not isinstance(params[key], bool):
                raise error(f"{key} 必须是布尔值。")
            audio[native] = True
    if "bitrate" in controls and audio["format"] in ("mp3", "ogg_opus"):
        audio["bit_rate"] = number(params, "bitrate", 64000, 16000, 160000, True)
    if "disable_default_bit_rate" in controls and params.get("disable_default_bit_rate"):
        additions["disable_default_bit_rate"] = True
    if "silence_duration" in controls:
        value = number(params, "silence_duration", 0, 0, 30000, True)
        if value:
            additions["silence_duration"] = value
    for key in ("enable_auto_language_recognition", "enable_language_detector", "disable_markdown_filter", "disable_emoji_filter", "enable_latex_tn", "aigc_watermark"):
        if key in controls and params.get(key):
            if not isinstance(params[key], bool):
                raise error(f"{key} 必须是布尔值。")
            additions[key] = True
    if "explicit_language" in controls:
        language = string(params, "explicit_language", 20)
        if language:
            if language not in DOUBAO_LANGUAGES:
                raise error("豆包明确语言不在官方枚举中。")
            additions["explicit_language"] = language
    if "explicit_dialect" in controls:
        dialect = string(params, "explicit_dialect", 20)
        if dialect:
            if dialect not in DOUBAO_DIALECTS:
                raise error("豆包明确方言不在官方枚举中。")
            additions["explicit_dialect"] = dialect
    if "context_language" in controls:
        context_language = string(params, "context_language", 20)
        if context_language:
            if context_language not in {"id", "es", "pt"}:
                raise error("豆包上下文语言不在官方枚举中。")
            additions["context_language"] = context_language
    if "latex_parser" in controls:
        parser = string(params, "latex_parser", 10)
        if parser not in ("", "v2"):
            raise error("豆包 LaTeX parser 只能为空或 v2。")
        if parser:
            additions["latex_parser"] = parser
    if "max_length_to_filter_parenthesis" in controls:
        additions["max_length_to_filter_parenthesis"] = number(params, "max_length_to_filter_parenthesis", 0, 0, 100, True)
    if "unsupported_char_ratio_thresh" in controls and params.get("unsupported_char_ratio_thresh") not in (None, ""):
        additions["unsupported_char_ratio_thresh"] = number(params, "unsupported_char_ratio_thresh", .3, 0, 1)
    if "aigc_metadata" in controls:
        metadata = _json_object(params.get("aigc_metadata"), "aigc_metadata", error)
        if metadata:
            additions["aigc_metadata"] = metadata
    if "cache_config" in controls:
        cache = _json_object(params.get("cache_config"), "cache_config", error)
        if cache:
            additions["cache_config"] = cache
    if "pronunciation" in controls:
        pronunciation = _string_list(params.get("pronunciation"), "pronunciation", error)
        if pronunciation:
            additions["pronunciation_dict"] = {"tone": pronunciation}
    if "section_id" in controls:
        section_id = string(params, "section_id", 200)
        if section_id:
            additions["section_id"] = section_id
    if "silence_trim" in controls:
        threshold = string(params, "mute_cut_threshold", 50)
        remain = string(params, "mute_cut_remain_ms", 50)
        if bool(threshold) != bool(remain):
            raise error("豆包静音裁剪需要同时填写阈值和保留时长。")
        if threshold:
            additions["mute_cut_threshold"] = threshold
            additions["mute_cut_remain_ms"] = remain
    if ssml:
        request = {"text": text, "ssml": text, "speaker": voice, "audio_params": audio}
    else:
        request = {"text": text, "speaker": voice, "audio_params": audio}
    if "mix" in controls and params.get("mix_enabled"):
        if params["mix_enabled"] is not True:
            raise error("mix_enabled 必须是布尔值。")
        weights = params.get("timbre_weights", [])
        if not isinstance(weights, list) or not all(isinstance(item, dict) for item in weights):
            raise error("混合音色必须为对象数组。")
        weights = [item for item in weights if item.get("voice_id")]
        if not 1 <= len(weights) <= 3:
            raise error("豆包 1.0 最多混合 3 个音色。")
        speakers = [{"source_speaker": string(item, "voice_id", 200), "mix_factor": number(item, "weight", 0, 0, 100) / 100} for item in weights]
        if abs(sum(item["mix_factor"] for item in speakers) - 1) > .000001:
            raise error("豆包混合权重之和必须为 100%。")
        request["mix_speaker"] = {"speakers": speakers}
    if additions:
        request["additions"] = json.dumps(additions, ensure_ascii=False)
    return {"user": {"uid": "local-tts-studio"}, "req_params": request}


def validate(payload, controls, record, number, error):
    controls = set(controls)
    request = payload["req_params"]
    audio = request["audio_params"]
    additions_raw = request.get("additions", "{}")
    if not isinstance(additions_raw, str):
        raise error("豆包 req_params.additions 必须为 JSON 字符串。")
    try:
        additions = json.loads(additions_raw)
    except ValueError:
        raise error("豆包 additions 不是有效 JSON。") from None
    if not isinstance(additions, dict):
        raise error("豆包 additions 必须编码一个 JSON 对象。")
    for key in ("speech_rate", "loudness_rate"):
        if key in audio:
            number(audio, key, 0, -50, 100)
    if audio.get("format") == "ogg_opus" and audio.get("sample_rate") != 48000:
        raise error("豆包 Ogg Opus 仅支持 48000 Hz。")
    bitrate = audio.get("bit_rate")
    if bitrate is not None:
        allowed = (16000, 32000, 64000, 160000) if additions.get("disable_default_bit_rate") else (64000, 160000)
        if isinstance(bitrate, bool) or bitrate not in allowed:
            raise error("豆包比特率须为 64000 / 160000；关闭默认比特率限制后可选 16000 / 32000。")
    if request.get("ssml"):
        if "ssml" not in controls or not isinstance(request["ssml"], str):
            raise error("当前豆包模型不支持 SSML。")
    if audio.get("emotion"):
        allowed = {item if isinstance(item, str) else item.get("id") for item in record.get("emotions", [])}
        if "emotion" not in controls or audio["emotion"] not in allowed:
            raise error("该音色未声明支持所选情绪。")
        number(audio, "emotion_scale", 4, 1, 5)
    for key, capability in (("enable_timestamp", "timestamps"), ("enable_subtitle", "enable_subtitle")):
        if key in audio:
            if not isinstance(audio[key], bool):
                raise error(f"{key} 必须是布尔值。")
            if audio[key] and capability not in controls:
                raise error(f"当前模型不支持 {key}。")
    for key, low, high in (("silence_duration", 0, 30000), ("max_length_to_filter_parenthesis", 0, 100)):
        if key in additions:
            number(additions, key, 0, low, high, True)
    if "unsupported_char_ratio_thresh" in additions:
        number(additions, "unsupported_char_ratio_thresh", .3, 0, 1)
    for key in ("enable_auto_language_recognition", "enable_language_detector", "disable_default_bit_rate", "disable_markdown_filter", "disable_emoji_filter", "enable_latex_tn", "aigc_watermark"):
        if key in additions:
            if not isinstance(additions[key], bool):
                raise error(f"{key} 必须是布尔值。")
            if additions[key] and key not in controls:
                raise error(f"当前豆包模型不支持 {key}。")
    if audio.get("format") not in ("mp3", "ogg_opus") and bitrate is not None:
        raise error("豆包 PCM / WAV 不支持 bit_rate。")
    if additions.get("latex_parser", "") not in ("", "v2"):
        raise error("latex_parser 只能为空或 v2。")
    if (additions.get("enable_latex_tn") or additions.get("latex_parser")) and not additions.get("disable_markdown_filter"):
        raise error("LaTeX 处理需要启用 Markdown 解析（disable_markdown_filter=true）。")
    if request.get("ssml") and additions.get("disable_markdown_filter"):
        raise error("SSML 要求 disable_markdown_filter=false。")
    if audio.get("enable_subtitle") and (additions.get("enable_latex_tn") or request.get("ssml")):
        raise error("豆包字幕不能与 LaTeX 文本处理或 SSML 同时启用。")
    if additions.get("context_language", "") not in ("", "id", "es", "pt"):
        raise error("context_language 只能为 id / es / pt。")
    for key in ("use_tag_parser", "tone_fidelity"):
        if additions.get(key):
            raise error(f"{key} 仅适用于声音复刻资源，当前系统音色模型不支持。")
    for key in ("section_id", "mute_cut_threshold", "mute_cut_remain_ms"):
        if key in additions:
            capability = "silence_trim" if key.startswith("mute_cut_") else key
            if capability not in controls or not isinstance(additions[key], str) or len(additions[key]) > 200:
                raise error(f"当前模型不支持 {key} 或其值不是有效字符串。")
    if bool(additions.get("mute_cut_threshold")) != bool(additions.get("mute_cut_remain_ms")):
        raise error("静音裁剪阈值与保留时长必须同时填写。")
    if request.get("model") and additions.get("context_texts"):
        raise error("豆包 model 与 context_texts 不能同时指定。")
    if additions.get("explicit_language"):
        if "explicit_language" not in controls or additions["explicit_language"] not in DOUBAO_LANGUAGES:
            raise error("豆包明确语言无效或当前模型不支持。")
    if additions.get("explicit_dialect"):
        if "explicit_dialect" not in controls or additions["explicit_dialect"] not in DOUBAO_DIALECTS:
            raise error("豆包明确方言无效或当前模型不支持。")
    if additions.get("context_texts"):
        values = additions["context_texts"]
        if "instructions" not in controls or not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str):
            raise error("context_texts 仅适用于 2.0，且应包含一个表达指令字符串。")
    if "post_process" in additions:
        if not isinstance(additions["post_process"], dict):
            raise error("post_process 必须是对象。")
        number(additions["post_process"], "pitch", 0, -12, 12, True)
    if "pronunciation_dict" in additions:
        dictionary = additions["pronunciation_dict"]
        if "pronunciation" not in controls or not isinstance(dictionary, dict) or not isinstance(dictionary.get("tone"), list) or len(dictionary["tone"]) > 5000:
            raise error("pronunciation_dict 必须是当前模型支持的字符串数组。")
        originals = set()
        for entry in dictionary["tone"]:
            if not isinstance(entry, str) or "/" not in entry:
                raise error("读音字典须为 原文/读音，每行一条。")
            original, replacement = entry.split("/", 1)
            if not original or len(original) > 9 or any(char.isspace() for char in original) or original in originals or not replacement.strip():
                raise error("读音字典原文须为 1–9 个无空白字符，不得重复，替换内容不能为空。")
            originals.add(original)
    if "cache_config" in additions:
        cache = additions["cache_config"]
        if "cache_config" not in controls or not isinstance(cache, dict):
            raise error("当前豆包模型不支持 cache_config。")
        if not isinstance(cache.get("use_cache", True), bool) or type(cache.get("text_type", 1)) is not int or cache.get("text_type", 1) != 1:
            raise error("缓存须使用 text_type=1，use_cache 必须为布尔值。")
        if cache.get("use_cache", True) and (audio.get("enable_timestamp") or audio.get("enable_subtitle")):
            raise error("豆包缓存结果不提供时间戳 / 字幕，请关闭缓存后生成。")
    if "aigc_metadata" in additions:
        metadata = additions["aigc_metadata"]
        if "aigc_metadata" not in controls or not isinstance(metadata, dict):
            raise error("当前豆包模型不支持 aigc_metadata。")
        if not isinstance(metadata.get("enable", False), bool):
            raise error("aigc_metadata.enable 必须为布尔值。")
        if metadata.get("enable") and audio.get("format") == "pcm":
            raise error("原始 PCM 不支持 AIGC 元数据，请选择 MP3 / WAV / Ogg Opus。")
        for key in ("content_producer", "produce_id", "content_propagator", "propagate_id"):
            if not isinstance(metadata.get(key, ""), str) or len(metadata.get(key, "")) > 2000:
                raise error(f"AIGC {key} 必须是字符串。")
    if record and additions.get("explicit_language") and additions["explicit_language"] not in {item[0] for item in record.get("languageOptions", [])}:
        raise error("所选语言未在当前音色官方语种范围中列明。")
    if record and additions.get("explicit_dialect") and additions["explicit_dialect"] not in {item[0] for item in record.get("dialectOptions", [])}:
        raise error("所选方言未在当前音色官方方言范围中列明。")
    if request.get("mix_speaker"):
        mix = request["mix_speaker"]
        if "mix" not in controls or not isinstance(mix, dict) or not isinstance(mix.get("speakers"), list) or not 1 <= len(mix["speakers"]) <= 3:
            raise error("豆包混音仅支持 1.0 模型，最多 3 个音色。")
        total, ids = 0, set()
        for speaker in mix["speakers"]:
            if not isinstance(speaker, dict) or not isinstance(speaker.get("source_speaker"), str) or not speaker["source_speaker"] or speaker["source_speaker"] in ids:
                raise error("混合音色必须具有唯一的 source_speaker。")
            ids.add(speaker["source_speaker"])
            total += number(speaker, "mix_factor", 0, 0, 1)
        if abs(total - 1) > .000001:
            raise error("豆包混合权重之和必须为 1。")
        request["speaker"] = "custom_mix_bigtts"
        audio.pop("loudness_rate", None)
    return additions
