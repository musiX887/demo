"""Qwen's two official HTTP synthesis families and their distinct controls."""
import base64
import json
import re

AUDIO_PATH = "/api/v1/services/audio/tts/SpeechSynthesizer"
LEGACY_PATH = "/api/v1/services/aigc/multimodal-generation/generation"


def endpoint(model, credentials, error):
    region = credentials.get("region", "cn")
    if region not in ("cn", "intl"):
        raise error("当前 Qwen TTS 仅列出北京与新加坡地域。")
    if model.startswith("qwen-audio-"):
        workspace = credentials.get("workspace_id", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}", workspace):
            raise error("Qwen-Audio 需要同地域的业务空间 ID，请在连接设置中填写。")
        location = "cn-beijing" if region == "cn" else "ap-southeast-1"
        return f"https://{workspace}.{location}.maas.aliyuncs.com{AUDIO_PATH}"
    host = "dashscope.aliyuncs.com" if region == "cn" else "dashscope-intl.aliyuncs.com"
    return "https://" + host + LEGACY_PATH


def audio_input(text, voice, params, controls, number, string, error):
    fmt = params.get("format", "wav")
    rate = number(params, "sample_rate", 24000, 8000, 48000, True)
    if fmt == "opus" and rate not in (8000, 12000, 16000, 24000, 48000):
        raise error("Qwen Opus 不支持 22050 或 44100 Hz，请选择其他采样率。")
    data = {"text": text, "voice": voice, "format": fmt, "sample_rate": rate}
    data["rate"] = number(params, "speed", 1, .5, 2)
    data["volume"] = number(params, "volume", 50, 0, 100, True)
    data["pitch"] = number(params, "pitch", 1, .5, 2)
    data["seed"] = number(params, "seed", 0, 0, 65535, True)
    instructions = string(params, "instructions", 4000)
    if instructions:
        if "instructions" not in controls:
            raise error("该音色未声明支持表达指令，请换用支持指令的音色。")
        data["instruction"] = instructions
    if fmt == "opus":
        data["bit_rate"] = number(params, "opus_bitrate", 32, 6, 510, True)
    language = string(params, "language_hints", 10)
    if language:
        if language not in ("zh", "en", "fr", "de", "ja", "ko", "ru", "pt", "th", "id", "vi", "es", "it", "ms", "fil", "ar"):
            raise error("无效的 Qwen 语言提示。")
        data["language_hints"] = [language]
    for ui_key, api_key, capability in [("ssml", "enable_ssml", "ssml"), ("timestamps", "word_timestamp_enabled", "timestamps"), ("aigc", "enable_aigc_tag", "aigc")]:
        value = params.get(ui_key, False)
        if not isinstance(value, bool):
            raise error(f"{ui_key} 必须是布尔值。")
        if value:
            if capability not in controls:
                raise error(f"所选音色不支持 {ui_key}。")
            data[api_key] = True
    if params.get("aigc"):
        for key in ("aigc_propagator", "aigc_propagate_id"):
            value = string(params, key, 256)
            if value:
                data[key] = value
    raw = params.get("hot_fix", {})
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            raise error("发音与文本替换必须是有效的 JSON 对象。") from None
    if not isinstance(raw, dict) or set(raw) - {"pronunciation", "replace"}:
        raise error("hot_fix 仅接受 pronunciation 与 replace。")
    for items in raw.values():
        if not isinstance(items, list) or any(not isinstance(item, dict) or not item or any(not isinstance(k, str) or not isinstance(v, str) for k, v in item.items()) for item in items):
            raise error("hot_fix 各项应为字符串映射组成的数组。")
    if raw:
        data["hot_fix"] = raw
    return data


def validate_input(data, controls, number, error):
    for key, default, low, high, integer in [("rate", 1, .5, 2, False), ("pitch", 1, .5, 2, False), ("volume", 50, 0, 100, True), ("seed", 0, 0, 65535, True), ("bit_rate", 32, 6, 510, True)]:
        if key in data:
            number(data, key, default, low, high, integer)
    instruction = data.get("instruction", "")
    if not isinstance(instruction, str) or len(instruction) > 4000:
        raise error("Qwen 表达指令必须是最多 4000 字符的字符串。")
    if instruction and "instructions" not in controls:
        raise error("所选音色未声明支持表达指令。")
    for key, capability in [("enable_ssml", "ssml"), ("word_timestamp_enabled", "timestamps"), ("enable_aigc_tag", "aigc")]:
        if key in data:
            if not isinstance(data[key], bool):
                raise error(f"{key} 必须是布尔值。")
            if data[key] and capability not in controls:
                raise error(f"所选音色未声明支持 {capability}。")
    if data.get("enable_aigc_tag") and data.get("format") == "pcm":
        raise error("Qwen AIGC 标识支持 WAV / MP3 / Opus，请选择其中一种格式。")
    if "language_hints" in data:
        hints = data["language_hints"]
        if not isinstance(hints, list) or len(hints) != 1 or hints[0] not in ("zh", "en", "fr", "de", "ja", "ko", "ru", "pt", "th", "id", "vi", "es", "it", "ms", "fil", "ar"):
            raise error("Qwen language_hints 应包含一个官方语言代码。")
    if "hot_fix" in data:
        raw = data["hot_fix"]
        if not isinstance(raw, dict) or set(raw) - {"pronunciation", "replace"} or any(not isinstance(items, list) or any(not isinstance(item, dict) or not item or any(not isinstance(k, str) or not isinstance(v, str) for k, v in item.items()) for item in items) for items in raw.values()):
            raise error("Qwen hot_fix 格式无效。")


def parse_sse(raw, error):
    """Collect SSE audio and word metadata without requiring the vendor SDK."""
    chunks, events = [], []
    final = {}
    normalized = raw.decode("utf-8").replace("\r\n", "\n")
    for frame in normalized.split("\n\n"):
        data = "\n".join(line[5:].lstrip() for line in frame.splitlines() if line.startswith("data:"))
        if not data or data.strip() == "[DONE]":
            continue
        try:
            record = json.loads(data)
        except ValueError:
            raise error("Qwen 流式响应包含无效 JSON。", 502) from None
        if not isinstance(record, dict):
            raise error("Qwen 流式响应格式无效。", 502)
        if record.get("code"):
            raise error("Qwen：" + str(record.get("message") or record["code"]), 502)
        output = record.get("output", {})
        if not isinstance(output, dict):
            raise error("Qwen 流式响应缺少 output。", 502)
        audio = output.get("audio") or {}
        if not isinstance(audio, dict):
            raise error("Qwen 流式响应的 audio 格式无效。", 502)
        if audio.get("data"):
            try:
                chunks.append(base64.b64decode(audio["data"], validate=True))
            except (ValueError, TypeError):
                raise error("Qwen 流式音频编码无效。", 502) from None
        if output.get("sentence") or output.get("original_text"):
            events.append({key: output[key] for key in ("type", "sentence", "original_text") if key in output})
        if output.get("finish_reason") == "stop" or audio.get("url"):
            final = record
    if not final:
        raise error("Qwen 流式响应未完整结束，请重新生成。", 502)
    return b"".join(chunks), final, events
