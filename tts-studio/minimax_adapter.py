"""MiniMax Speech HTTP controls, including mixing and streamed responses."""
import json

SOUND_EFFECTS = {"spacious_echo", "auditorium_echo", "lofi_telephone", "robotic"}


def boolean(params, key, error, default=False):
    value = params.get(key, default)
    if not isinstance(value, bool):
        raise error(f"{key} 必须是布尔值。")
    return value


def build(model, voice, text, params, controls, info, number, string, error):
    setting = {"voice_id": voice}
    for key, native, default, low, high, integer in [
        ("speed", "speed", 1, .5, 2, False),
        ("volume", "vol", 1, 0, 10, False),
        ("pitch", "pitch", 0, -12, 12, True),
    ]:
        if key in controls:
            setting[native] = number(params, key, default, low, high, integer)
    if setting.get("vol") == 0:
        raise error("MiniMax 音量必须大于 0，且不超过 10。")
    emotion = string(params, "emotion", 40)
    if emotion and "emotion" in controls:
        if emotion not in {item["id"] for item in info["emotions"]}:
            raise error("当前 MiniMax 模型不支持所选情绪。")
        setting["emotion"] = emotion
    fmt = params.get("format", "mp3")
    rate = number(params, "sample_rate", 32000, 8000, 44100, True)
    audio = {"format": fmt, "sample_rate": rate, "channel": number(params, "channel", 1, 1, 2, True)}
    if fmt == "mp3" and "bitrate" in controls:
        bitrate = number(params, "bitrate", 128000, 32000, 256000, True)
        if bitrate not in (32000, 64000, 128000, 256000):
            raise error("请选择有效的 MP3 比特率。")
        audio["bitrate"] = bitrate
    payload = {"model": model, "text": text, "stream": False, "output_format": "hex", "voice_setting": setting, "audio_setting": audio}
    if "language_boost" in controls:
        payload["language_boost"] = string(params, "language_boost", 60) or "auto"
    if "latex_read" in controls:
        setting["latex_read"] = boolean(params, "latex_read", error)
        if setting["latex_read"]:
            payload["language_boost"] = "Chinese"
    if "pronunciation" in controls and params.get("pronunciation"):
        tones = params["pronunciation"]
        if not isinstance(tones, list) or any(not isinstance(item, str) or not item.strip() for item in tones):
            raise error("读音字典必须是非空字符串组成的数组。")
        payload["pronunciation_dict"] = {"tone": tones}
    if "normalization" in controls:
        normalization = string(params, "normalization_mode", 20)
        if normalization:
            if normalization not in ("basic", "quality"):
                raise error("文本规范化模式必须是 basic 或 quality。")
            payload["text_normalization_mode"] = normalization
    if "voice_modify" in controls:
        modify = {native: number(params, key, 0, -100, 100, True) for key, native in [("voice_pitch", "pitch"), ("intensity", "intensity"), ("timbre", "timbre")]}
        effect = string(params, "sound_effects", 40)
        if effect:
            if effect not in SOUND_EFFECTS:
                raise error("无效的 MiniMax 音效。")
            modify["sound_effects"] = effect
        if any(modify.values()):
            payload["voice_modify"] = modify
    if "vendor_stream" in controls:
        payload["stream"] = boolean(params, "vendor_stream", error)
    if "subtitle" in controls and boolean(params, "subtitle", error):
        kind = string(params, "subtitle_type", 20) or "sentence"
        if kind not in ("sentence", "word", "word_streaming"):
            raise error("无效的字幕粒度。")
        payload.update(subtitle_enable=True, subtitle_type=kind)
        if kind == "word_streaming":
            payload["stream"] = True
    if "force_cbr" in controls and boolean(params, "force_cbr", error):
        audio["force_cbr"] = True
    if "aigc" in controls and boolean(params, "aigc", error):
        payload["aigc_watermark"] = True
    if "mix" in controls and boolean(params, "mix_enabled", error):
        items = params.get("timbre_weights", [])
        if not isinstance(items, list) or len(items) > 4:
            raise error("音色混合最多支持 4 个音色。")
        weights = []
        for item in items:
            if not isinstance(item, dict):
                raise error("音色混合各项必须是对象。")
            voice_id = string(item, "voice_id", 200)
            if voice_id:
                weights.append({"voice_id": voice_id, "weight": number(item, "weight", 25, 1, 100, True)})
        if not weights:
            raise error("启用音色混合时，请至少选择一个混合音色。")
        payload["timbre_weights"] = weights
        setting["voice_id"] = ""
    return payload


def validate(payload, info, languages, number, error):
    """Validate the final merged payload, including advanced overrides."""
    setting, audio = payload["voice_setting"], payload["audio_setting"]
    for key, default, low, high, integer in [("speed", 1, .5, 2, False), ("vol", 1, 0, 10, False), ("pitch", 0, -12, 12, True)]:
        if key in setting:
            value = number(setting, key, default, low, high, integer)
            if key == "vol" and value == 0:
                raise error("MiniMax 音量必须大于 0。")
    if setting.get("emotion") and setting["emotion"] not in {item["id"] for item in info.get("emotions", [])}:
        raise error("所选 MiniMax 模型不支持该情绪。")
    if "latex_read" in setting and boolean(setting, "latex_read", error):
        payload["language_boost"] = "Chinese"
    if languages and payload.get("language_boost", "auto") not in {item[0] for item in languages}:
        raise error("MiniMax language_boost 不在官方支持列表中。")
    if payload["model"].startswith(("speech-01-", "speech-02-")) and payload.get("language_boost") in ("Persian", "Filipino", "Tamil"):
        raise error("Speech 01 / 02 不支持 Persian / Filipino / Tamil，请切换 2.6 / 2.8。")
    stream = boolean(payload, "stream", error)
    fmt = audio.get("format", "mp3")
    number(audio, "channel", 1, 1, 2, True)
    if fmt in ("pcmu_raw", "pcmu_wav"):
        if audio.get("sample_rate") != 8000:
            raise error("MiniMax μ-law 编码须选择 8000 Hz。")
    if payload.get("voice_modify"):
        modify = payload["voice_modify"]
        if not isinstance(modify, dict):
            raise error("voice_modify 必须是对象。")
        for key in ("pitch", "intensity", "timbre"):
            if key in modify:
                number(modify, key, 0, -100, 100, True)
        if modify.get("sound_effects") and modify["sound_effects"] not in SOUND_EFFECTS:
            raise error("无效的音效。")
        if fmt not in (("mp3",) if stream else ("mp3", "wav", "flac")):
            raise error("音色变换的非流式输出仅支持 MP3 / WAV / FLAC，流式仅支持 MP3。")
    if audio.get("force_cbr") and (not stream or fmt != "mp3"):
        raise error("固定比特率仅适用于流式 MP3。")
    if payload.get("aigc_watermark") and stream:
        raise error("MiniMax AIGC 水印仅支持非流式输出。")
    mode = payload.get("text_normalization_mode")
    if mode not in (None, "basic", "quality"):
        raise error("文本规范化模式无效。")
    if mode == "quality" and (stream or not payload["model"].startswith(("speech-2.8-", "speech-2.6-"))):
        raise error("高质量文本规范化仅支持 Speech 2.8 / 2.6 的非流式请求，请切换基础模式。")
    if payload.get("subtitle_type") == "word_streaming" and not stream:
        raise error("word_streaming 字幕需要厂商流式输出。")
    if stream:
        # Ask for incremental audio only; this prevents final aggregate duplication.
        payload["stream_options"] = {"exclude_aggregated_audio": True}
    if fmt != "mp3":
        audio.pop("bitrate", None)
    elif audio.get("bitrate", 128000) not in (32000, 64000, 128000, 256000):
        raise error("无效的 MP3 比特率。")
    weights = payload.get("timbre_weights")
    if weights is not None:
        if not isinstance(weights, list) or not 1 <= len(weights) <= 4:
            raise error("音色混合应包含 1 至 4 个音色。")
        for item in weights:
            if not isinstance(item, dict) or not isinstance(item.get("voice_id"), str) or not item["voice_id"]:
                raise error("混合音色 ID 不能为空。")
            number(item, "weight", 25, 1, 100, True)
        setting["voice_id"] = ""


def parse_sse(raw, error):
    chunks, metadata, final = [], {"subtitles": []}, False
    subtitles = {}
    for frame in raw.decode("utf-8").replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(line[5:].lstrip() for line in frame.splitlines() if line.startswith("data:"))
        if not data or data.strip() == "[DONE]":
            continue
        try:
            record = json.loads(data)
        except ValueError:
            raise error("MiniMax 流式响应含有无效 JSON。", 502) from None
        if not isinstance(record, dict):
            raise error("MiniMax 流式响应格式无效。", 502)
        base = record.get("base_resp") or {}
        if not isinstance(base, dict) or base.get("status_code", 0) != 0:
            raise error("MiniMax：" + str(base.get("status_msg", "流式合成失败") if isinstance(base, dict) else "响应格式错误"), 502)
        value = record.get("data") or {}
        if not isinstance(value, dict):
            raise error("MiniMax 流式 data 格式无效。", 502)
        if value.get("audio") and (value.get("status") != 2 or not chunks):
            try:
                chunks.append(bytes.fromhex(value["audio"]))
            except (ValueError, TypeError):
                raise error("MiniMax 流式音频编码无效。", 502) from None
        if value.get("subtitle"):
            subtitle = value["subtitle"]
            if isinstance(subtitle, dict):
                subtitles[subtitle.get("text_begin", len(subtitles))] = subtitle
        if isinstance(value.get("subtitles"), list):
            for subtitle in value["subtitles"]:
                if isinstance(subtitle, dict):
                    subtitles[subtitle.get("text_begin", len(subtitles))] = subtitle
        for key in ("extra_info", "trace_id"):
            if key in record:
                metadata[key] = record[key]
        if value.get("status") == 2:
            final = True
    if not final or not chunks:
        raise error("MiniMax 流式音频未完整结束，请重新生成。", 502)
    metadata["subtitles"] = list(subtitles.values())
    return b"".join(chunks), metadata
