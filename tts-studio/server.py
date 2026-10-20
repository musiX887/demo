"""Local TTS workbench. Python 3.12+, standard library only."""
from __future__ import annotations

import argparse
import base64
import binascii
import copy
import io
import json
import math
import os
import re
from pathlib import Path
import secrets
import struct
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from catalog import CATALOG, model_info, voice_info, effective_controls
import qwen_adapter
import minimax_adapter
import doubao_adapter

ROOT = Path(__file__).resolve().parent
MAX_BODY = 512 * 1024
MAX_REMOTE = 48 * 1024 * 1024
MAX_TEXT = 10000
MAX_CLIPS = 30
MAX_AUDIO_BYTES = 96 * 1024 * 1024
PROVIDERS = {p["id"]: p for p in CATALOG["providers"]}
ENV_FIELDS = {
    "doubao": {"app_id": "DOUBAO_APP_ID", "api_key": "DOUBAO_API_KEY", "resource_id": "DOUBAO_RESOURCE_ID"},
    "minimax": {"api_key": "MINIMAX_API_KEY"},
    "qwen": {"api_key": "DASHSCOPE_API_KEY", "workspace_id": "QWEN_WORKSPACE_ID"},
}
MIME = {"mp3": "audio/mpeg", "wav": "audio/wav", "pcm": "application/octet-stream", "flac": "audio/flac", "opus": "audio/ogg", "ogg_opus": "audio/ogg", "aac": "audio/aac", "pcmu_raw": "application/octet-stream", "pcmu_wav": "audio/wav"}


def required_fields(provider):
    optional = {field["id"] for field in PROVIDERS[provider]["credentialFields"] if field.get("optional")}
    return set(ENV_FIELDS[provider]) - optional


class UserError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def load_env(path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def read_limited(stream, limit=MAX_REMOTE):
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise UserError("远端返回内容过大，请缩短文本。", 502)
    return data


def check_url(url, allowed_suffixes):
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if (parts.scheme != "https" or parts.username or parts.password
            or parts.port not in (None, 443)
            or not any(host == suffix or host.endswith("." + suffix) for suffix in allowed_suffixes)):
        raise UserError("上游返回的音频地址不在允许的官方域名范围内。", 502)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_suffixes, normalize=None):
        self.allowed_suffixes = allowed_suffixes
        self.normalize = normalize

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.normalize is not None:
            newurl = self.normalize(newurl)
        check_url(newurl, self.allowed_suffixes)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise UserError("上游 API 返回了意外重定向。", 502)


def api_request(url, payload, headers, timeout=120):
    request = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(),
                                     headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            return read_limited(response)
    except urllib.error.HTTPError as exc:
        detail = read_limited(exc, 8192).decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            detail = parsed.get("message") or parsed.get("error", {}).get("message") or parsed.get("base_resp", {}).get("status_msg") or "请检查凭据、配额、地域和模型权限。"
        except (ValueError, AttributeError):
            detail = "请检查凭据、配额、地域和模型权限。"
        raise UserError(f"上游 HTTP {exc.code}：{str(detail)[:400]}", 502) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UserError("连接上游服务失败或超时，请检查网络后重试。", 502) from None


def request_json(url, payload, headers):
    try:
        result = json.loads(api_request(url, payload, headers))
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, UnicodeError):
        raise UserError("上游没有返回有效的 JSON 对象。", 502) from None


QWEN_AUDIO_SUFFIXES = ("aliyuncs.com", "alicdn.com")


def normalize_qwen_audio_url(url):
    # Official responses can contain signed HTTP OSS URLs; use TLS without
    # rewriting the host, escaped path, or signature query string.
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme == "http" and parts.port in (None, 80):
            authority = parts.netloc[:-3] if parts.netloc.endswith(":80") else parts.netloc
            url = urllib.parse.urlunsplit(parts._replace(scheme="https", netloc=authority))
        check_url(url, QWEN_AUDIO_SUFFIXES)
    except (ValueError, TypeError):
        raise UserError("Qwen 返回的音频地址格式无效。", 502) from None
    return url


def download_qwen_audio(url):
    url = normalize_qwen_audio_url(url)
    try:
        with urllib.request.build_opener(SafeRedirect(QWEN_AUDIO_SUFFIXES, normalize_qwen_audio_url)).open(url, timeout=120) as response:
            return read_limited(response)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UserError("语音已生成，但下载上游音频失败。", 502) from None


def number(params, key, default, low, high, integer=False):
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise UserError(f"{key} 必须是有限数值。")
    if not low <= value <= high or (integer and int(value) != value):
        raise UserError(f"{key} 必须在 {low} 到 {high} 之间" + ("，且为整数。" if integer else "。"))
    return int(value) if integer else value


def optional_string(params, key, limit=2000):
    value = params.get(key, "")
    if not isinstance(value, str) or len(value) > limit:
        raise UserError(f"{key} 必须是长度不超过 {limit} 的字符串。")
    return value.strip()


def recursive_merge(target, extra):
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            recursive_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


def validate_job(data):
    if not isinstance(data, dict):
        raise UserError("请求必须是 JSON 对象。")
    provider = data.get("provider")
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise UserError("请选择有效厂商。")
    model = optional_string(data, "model", 160)
    voice = optional_string(data, "voice", 200)
    if any(item["id"] == data.get("voice") for item in PROVIDERS[provider]["voices"]):
        voice = data["voice"]
    text = optional_string(data, "text", MAX_TEXT)
    if not model or not voice or not text:
        raise UserError("模型、音色和文本不能为空。")
    params = data.get("params", {})
    extra = data.get("extra", {})
    if not isinstance(params, dict) or not isinstance(extra, dict):
        raise UserError("params 和 extra 必须是 JSON 对象。")
    if len(json.dumps(extra)) > 32000:
        raise UserError("高级参数过大。")
    # Transport settings and credentials never come from an arbitrary payload.
    blocked = {"api_key", "token", "authorization", "headers", "url", "endpoint"}
    if blocked.intersection(key.lower() for key in extra):
        raise UserError("高级参数不能包含凭据或网络地址配置。")
    return {"provider": provider, "model": model, "voice": voice, "text": text, "params": params, "extra": extra}


def build_payload(job):
    provider, model, voice, text, params = (job[key] for key in ("provider", "model", "voice", "text", "params"))
    info = model_info(provider, model)
    controls = effective_controls(provider, model, voice)
    record = voice_info(provider, voice)
    if "models" in record and model not in record["models"]:
        raise UserError("所选官方音色不适用于当前模型，请重新选择音色。")
    max_text = info.get("maxText", MAX_TEXT)
    if len(text) > max_text:
        raise UserError(f"所选模型单次最多支持 {max_text} 个字符，请缩短文本。")
    if info.get("maxTextBytes") and len(text.encode("utf-8")) > info["maxTextBytes"]:
        raise UserError(f"所选模型文本上限为 {info['maxTextBytes']} 个 UTF-8 字节。")
    # Custom models start with base fields; their additional fields belong in extra.
    fmt = params.get("format", "wav" if provider == "qwen" else "mp3")
    if fmt not in info.get("formats", PROVIDERS[provider]["formats"]):
        raise UserError("当前厂商不支持所选输出格式。")
    sample_rate = number(params, "sample_rate", 24000, 8000, 48000, True)
    if sample_rate not in info.get("sampleRates", PROVIDERS[provider]["sampleRates"]):
        raise UserError("不支持的采样率。")
    if provider == "minimax":
        payload = minimax_adapter.build(model, voice, text, params, controls, info, number, optional_string, UserError)
    elif provider == "qwen":
        if info.get("kind") == "qwen-audio" or model.startswith("qwen-audio-"):
            input_data = qwen_adapter.audio_input(text, voice, params, controls, number, optional_string, UserError)
        else:
            language = optional_string(params, "language", 60) or "Auto"
            if language not in ("Auto", "Chinese", "English", "German", "Italian", "Portuguese", "Spanish", "Japanese", "Korean", "French", "Russian"):
                raise UserError("无效的 Qwen3 文本语言。")
            input_data = {"text": text, "voice": voice, "language_type": language}
            fmt, sample_rate = "wav", 24000
        payload = {"model": model, "input": input_data}
    else:
        payload = doubao_adapter.build(model, voice, text, params, controls, record, number, optional_string, UserError)
    recursive_merge(payload, job["extra"])
    # Restore form identity and validate the final merged vendor request.
    if provider == "minimax":
        payload.update(model=model, text=text, output_format="hex")
        if not isinstance(payload.get("voice_setting"), dict) or not isinstance(payload.get("audio_setting"), dict):
            raise UserError("voice_setting 和 audio_setting 必须是对象。")
        payload["voice_setting"]["voice_id"] = voice
        minimax_adapter.validate(payload, info, PROVIDERS[provider].get("languages", []), number, UserError)
        fmt = payload["audio_setting"].get("format", fmt)
        sample_rate = payload["audio_setting"].get("sample_rate", sample_rate)
    elif provider == "qwen":
        payload["model"] = model
        if not isinstance(payload.get("input"), dict):
            raise UserError("input 必须是对象。")
        payload["input"].update(text=text, voice=voice)
        if model.startswith("qwen-audio-"):
            qwen_adapter.validate_input(payload["input"], controls, number, UserError)
            fmt = payload["input"].get("format", fmt)
            sample_rate = payload["input"].get("sample_rate", sample_rate)
            if fmt == "opus" and sample_rate not in (8000, 12000, 16000, 24000, 48000):
                raise UserError("Qwen Opus 的采样率不受支持。")
        elif any(key in payload["input"] for key in ("instructions", "instruction", "optimize_instructions", "rate", "speed", "pitch", "volume", "emotion")):
            raise UserError("Qwen3 Flash 未提供这些表达控制，请切换 Qwen-Audio 模型。")
    else:
        if not isinstance(payload.get("req_params"), dict) or not isinstance(payload["req_params"].get("audio_params"), dict):
            raise UserError("req_params 和 audio_params 必须是对象。")
        payload["req_params"].update(text=text, speaker=voice)
        doubao_adapter.validate(payload, controls, record, number, UserError)
        for speaker in payload["req_params"].get("mix_speaker", {}).get("speakers", []):
            source = speaker["source_speaker"]
            source_record = voice_info(provider, source)
            if source_record and (model not in source_record.get("models", []) or not source_record.get("mixSupported")):
                raise UserError("混合音色须为官方明确支持混音的 1.0 音色。")
            if not source_record and not source.startswith(("S_", "icl_")):
                raise UserError("自定义混合音色须为已开通的 S_ / icl_ 克隆音色。")
        fmt = payload["req_params"]["audio_params"].get("format", fmt)
        sample_rate = payload["req_params"]["audio_params"].get("sample_rate", sample_rate)
    if fmt not in info.get("formats", PROVIDERS[provider]["formats"]) or sample_rate not in info.get("sampleRates", PROVIDERS[provider]["sampleRates"]):
        raise UserError("高级参数中的音频格式或采样率无效。")
    return payload, fmt, sample_rate


def parse_minimax(result):
    base = result.get("base_resp", {})
    if not isinstance(base, dict) or base.get("status_code", 0) != 0:
        raise UserError(f"MiniMax：{base.get('status_msg', '合成失败') if isinstance(base, dict) else '响应格式错误'}", 502)
    data = result.get("data") or {}
    if not isinstance(data, dict):
        raise UserError("MiniMax 响应缺少音频对象。", 502)
    audio = data.get("audio")
    if not isinstance(audio, str) or not audio:
        raise UserError("MiniMax 没有返回音频数据。", 502)
    try:
        return bytes.fromhex(audio)
    except ValueError:
        raise UserError("MiniMax 返回的音频编码无效。", 502) from None


def parse_doubao(raw, with_metadata=False):
    chunks, events, usage, finished = [], [], {}, False
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            result = json.loads(line)
            if not isinstance(result, dict):
                raise ValueError()
        except ValueError:
            raise UserError("豆包返回的流式数据格式无效。", 502) from None
        code = result.get("code")
        if code not in (0, 20000000):
            raise UserError(f"豆包 {code}：{str(result.get('message', '合成失败'))[:400]}", 502)
        if code == 20000000:
            finished = True
        if result.get("sentence"):
            events.append(result["sentence"])
        if result.get("usage"):
            usage = result["usage"]
        audio = result.get("data")
        if audio:
            try:
                chunks.append(base64.b64decode(audio, validate=True))
            except (ValueError, TypeError, binascii.Error):
                raise UserError("豆包返回的音频编码无效。", 502) from None
    if not chunks:
        raise UserError("豆包没有返回音频。请检查音色与 Resource ID 的兼容性。", 502)
    if not finished:
        raise UserError("豆包音频响应未完整结束，请重新生成。", 502)
    audio = b"".join(chunks)
    return (audio, {"subtitles": events, "usage": usage}) if with_metadata else audio


def normalize_wav_stream(audio):
    """Merge complete RIFF segments returned by streaming WAV synthesis."""
    offset, frames, parameters = 0, [], None
    try:
        while offset < len(audio):
            if audio[offset:offset + 4] != b"RIFF" or audio[offset + 8:offset + 12] != b"WAVE":
                raise ValueError()
            size = struct.unpack_from("<I", audio, offset + 4)[0] + 8
            if size < 44 or offset + size > len(audio):
                raise ValueError()
            with wave.open(io.BytesIO(audio[offset:offset + size]), "rb") as reader:
                current = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getcomptype())
                if parameters is not None and current != parameters:
                    raise ValueError()
                parameters = current
                data = reader.readframes(reader.getnframes())
                if len(data) != reader.getnframes() * reader.getnchannels() * reader.getsampwidth():
                    raise ValueError()
                frames.append(data)
            offset += size + (size % 2)
        if not frames:
            raise ValueError()
        result = io.BytesIO()
        with wave.open(result, "wb") as writer:
            writer.setnchannels(parameters[0])
            writer.setsampwidth(parameters[1])
            writer.setframerate(parameters[2])
            writer.writeframes(b"".join(frames))
        return result.getvalue()
    except (ValueError, EOFError, struct.error, wave.Error):
        raise UserError("豆包流式 WAV 容器不完整或编码不一致，请改用 PCM / MP3。", 502) from None


def pcm_to_wav(audio, sample_rate, channels=1):
    if len(audio) % (2 * channels):
        raise UserError("上游返回的 PCM 数据长度无效。", 502)
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(audio)
    return output.getvalue()


def ulaw_to_wav(audio, sample_rate, channels=1, container=False):
    if container:
        if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise UserError("上游返回的 μ-law WAV 容器无效。", 502)
        position, frames = 12, None
        while position + 8 <= len(audio):
            kind, size = struct.unpack_from("<4sI", audio, position)
            position += 8
            if position + size > len(audio):
                raise UserError("上游 μ-law WAV 数据不完整。", 502)
            if kind == b"fmt " and size >= 16:
                encoding, channels, sample_rate = struct.unpack_from("<HHI", audio, position)
                if encoding != 7 or channels not in (1, 2) or sample_rate != 8000:
                    raise UserError("上游 μ-law WAV 编码与请求不一致。", 502)
            if kind == b"data":
                frames = audio[position:position + size]
            position += size + (size % 2)
        if frames is None:
            raise UserError("上游 μ-law WAV 缺少音频数据。", 502)
        audio = frames
    pcm = bytearray()
    for value in audio:
        value = ~value & 0xff
        magnitude = (((value & 0x0f) << 3) + 0x84) << ((value >> 4) & 7)
        sample = 0x84 - magnitude if value & 0x80 else magnitude - 0x84
        pcm.extend(struct.pack("<h", sample))
    return pcm_to_wav(pcm, sample_rate, channels)


class Studio:
    def __init__(self, settings_path=None):
        self.settings_path = Path(settings_path) if settings_path is not None else None
        self.saved_credentials = {}
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)
        self.credentials = {}
        self.active = threading.BoundedSemaphore(3)
        self.audio = OrderedDict()
        self.audio_bytes = 0
        self.catalog = copy.deepcopy(CATALOG)
        for provider, fields in ENV_FIELDS.items():
            self.credentials[provider] = {key: os.getenv(env, "") for key, env in fields.items()}
            self.credentials[provider]["region"] = os.getenv(provider.upper() + "_REGION", "cn")
        if not self.credentials["doubao"].get("api_key"):
            self.credentials["doubao"]["api_key"] = os.getenv("DOUBAO_ACCESS_TOKEN", "")
        if not self.credentials["doubao"].get("resource_id"):
            self.credentials["doubao"]["resource_id"] = "auto"
        self.load_settings()

    def load_settings(self):
        if self.settings_path is None:
            return
        try:
            raw = self.settings_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError:
            raise UserError("无法读取本地连接配置，请检查文件权限。", 500) from None
        try:
            saved = json.loads(raw)
            if not isinstance(saved, dict) or saved.get("version") != 1 or not isinstance(saved.get("providers"), dict):
                raise ValueError()
            for provider, record in saved["providers"].items():
                if provider not in ENV_FIELDS or not isinstance(record, dict):
                    raise ValueError()
                if set(record) != set(ENV_FIELDS[provider]) | {"region"}:
                    raise ValueError()
                if record["region"] not in {r["id"] for r in PROVIDERS[provider]["regions"]}:
                    raise ValueError()
                if any(not isinstance(value, str) or len(value) > 4096 or "\n" in value or "\r" in value for value in record.values()):
                    raise ValueError()
            self.saved_credentials = saved["providers"]
        except (ValueError, TypeError):
            raise UserError("本地连接配置格式无效，请检查 settings.local.json。", 500) from None
        for provider, record in self.saved_credentials.items():
            self.credentials[provider] = record.copy()

    def save_settings(self, providers):
        if self.settings_path is None:
            return
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.settings_path.parent,
                                             prefix=self.settings_path.name + ".", suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                json.dump({"version": 1, "providers": providers}, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.settings_path)
        except OSError:
            raise UserError("连接配置未保存到本地，请检查配置目录的写入权限后重试。", 500) from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def status(self):
        with self.lock:
            result = {}
            for provider, credentials in self.credentials.items():
                required = required_fields(provider)
                result[provider] = {"configured": all(credentials.get(key) for key in required),
                                    "region": credentials["region"],
                                    "fields": {key: bool(credentials.get(key)) for key in ENV_FIELDS[provider]}}
            return {"providers": result, "sessionToken": self.token}

    def update_settings(self, data):
        provider = data.get("provider")
        if not isinstance(provider, str) or provider not in PROVIDERS:
            raise UserError("无效厂商。")
        region = data.get("region", "cn")
        if region not in {r["id"] for r in PROVIDERS[provider]["regions"]}:
            raise UserError("无效地域。")
        fields = data.get("fields", {})
        if not isinstance(fields, dict):
            raise UserError("凭据格式错误。")
        clean = {}
        for key in ENV_FIELDS[provider]:
            value = fields.get(key, "")
            if not isinstance(value, str) or len(value) > 4096 or "\n" in value or "\r" in value:
                raise UserError("凭据格式错误。")
            if value.strip():
                clean[key] = value.strip()
        with self.lock:
            current = self.credentials[provider].copy()
            if data.get("clear") is True:
                current = {key: "" for key in ENV_FIELDS[provider]}
                current["region"] = region
            else:
                current.update(clean, region=region)
            saved = {**self.saved_credentials, provider: current}
            self.save_settings(saved)
            self.saved_credentials = saved
            self.credentials[provider] = current
        return self.status()

    def get_credentials(self, provider):
        with self.lock:
            creds = self.credentials[provider].copy()
        if not all(creds.get(key) for key in required_fields(provider)):
            raise UserError("请先在「连接设置」中配置该厂商的凭据。")
        return creds

    def redact(self, message):
        with self.lock:
            values = [value for cred in self.credentials.values() for key, value in cred.items() if key in ("api_key", "app_id") and value]
        for value in sorted(values, key=len, reverse=True):
            message = message.replace(value, "[已隐藏]")
        return message[:700]

    def refresh_voices(self):
        creds = self.get_credentials("minimax")
        host = "api.minimax.cn" if creds["region"] == "cn" else "api.minimax.io"
        result = request_json(f"https://{host}/v1/get_voice", {"voice_type": "system"}, {"Authorization": "Bearer " + creds["api_key"]})
        base = result.get("base_resp", {})
        if base.get("status_code", 0) != 0:
            raise UserError("音色刷新失败：" + str(base.get("status_msg", "未知错误")), 502)
        voices = []
        known = {voice["id"]: voice for voice in PROVIDERS["minimax"]["voices"]}
        for item in result.get("system_voice", []):
            if isinstance(item, dict) and isinstance(item.get("voice_id"), str):
                record = copy.deepcopy(known.get(item["voice_id"], {}))
                record.update(id=item["voice_id"], name=str(item.get("voice_name") or record.get("name") or item["voice_id"]),
                              language=str(item.get("language") or record.get("language") or "官方系统音色"), verified=True,
                              source="MiniMax get_voice · system", description=item.get("description") or record.get("description", ""))
                voices.append(record)
        if not voices:
            raise UserError("接口没有返回系统音色；已保留原列表。", 502)
        with self.lock:
            next(p for p in self.catalog["providers"] if p["id"] == "minimax")["voices"] = voices
        return {"count": len(voices), "voices": voices}

    def synthesize(self, data):
        job = validate_job(data)
        payload, fmt, sample_rate = build_payload(job)
        creds = self.get_credentials(job["provider"])
        record = voice_info(job["provider"], job["voice"])
        if record.get("regions") and creds["region"] not in record["regions"]:
            raise UserError("该官方音色未在当前地域提供，请调整地域或更换音色。")
        if not self.active.acquire(blocking=False):
            raise UserError("已有 3 个合成任务进行中，请稍后重试。", 429)
        start = time.monotonic()
        try:
            provider = job["provider"]
            vendor_metadata = {}
            if provider == "minimax":
                host = "api.minimax.cn" if creds["region"] == "cn" else "api.minimax.io"
                headers = {"Authorization": "Bearer " + creds["api_key"]}
                if payload.get("stream"):
                    audio, vendor_metadata = minimax_adapter.parse_sse(api_request(f"https://{host}/v1/t2a_v2", payload, headers), UserError)
                else:
                    result = request_json(f"https://{host}/v1/t2a_v2", payload, headers)
                    audio = parse_minimax(result)
                    vendor_metadata = {key: result[key] for key in ("extra_info", "trace_id") if key in result}
                    subtitle = (result.get("data") or {}).get("subtitle_file")
                    if subtitle:
                        vendor_metadata["subtitleFile"] = subtitle
            elif provider == "qwen":
                url = qwen_adapter.endpoint(job["model"], creds, UserError)
                headers = {"Authorization": "Bearer " + creds["api_key"]}
                if payload["input"].get("word_timestamp_enabled"):
                    headers["X-DashScope-SSE"] = "enable"
                    chunks, result, events = qwen_adapter.parse_sse(api_request(url, payload, headers), UserError)
                    vendor_metadata["timestamps"] = events
                else:
                    result = request_json(url, payload, headers)
                    chunks = b""
                output = result.get("output", {})
                audio_info = output.get("audio", {}) if isinstance(output, dict) else {}
                audio_url = audio_info.get("url") if isinstance(audio_info, dict) else None
                if isinstance(audio_url, str) and audio_url:
                    audio = download_qwen_audio(audio_url)
                elif chunks:
                    audio = chunks
                else:
                    raise UserError("Qwen：" + str(result.get("message") or "没有返回完整音频。"), 502)
                vendor_metadata.update(usage=result.get("usage", {}), requestId=result.get("request_id", ""))
            else:
                headers = {"X-Api-Resource-Id": job["model"] if creds["resource_id"] == "auto" else creds["resource_id"],
                           "X-Api-Request-Id": str(uuid.uuid4())}
                if creds.get("app_id"):
                    headers.update({"X-Api-App-Id": creds["app_id"], "X-Api-Access-Key": creds["api_key"]})
                else:
                    headers["X-Api-Key"] = creds["api_key"]
                audio, vendor_metadata = parse_doubao(api_request("https://openspeech.bytedance.com/api/v3/tts/unidirectional", payload, headers), with_metadata=True)
                if fmt == "wav":
                    audio = normalize_wav_stream(audio)
            if not audio:
                raise UserError("上游返回了空音频。", 502)
            original_format = fmt
            original_audio = audio
            converted = fmt in ("pcm", "pcmu_raw", "pcmu_wav")
            channels = payload.get("audio_setting", {}).get("channel", 1) if provider == "minimax" else 1
            if fmt == "pcm":
                audio = pcm_to_wav(audio, sample_rate, channels)
                fmt = "wav"
            elif fmt in ("pcmu_raw", "pcmu_wav"):
                audio = ulaw_to_wav(audio, sample_rate, channels, container=fmt == "pcmu_wav")
                fmt = "wav"
            clip_id = uuid.uuid4().hex
            metadata = {"id": clip_id, "provider": provider, "model": job["model"], "voice": job["voice"],
                        "text": job["text"], "params": job["params"], "format": fmt, "originalFormat": original_format,
                        "sampleRate": sample_rate, "bytes": len(original_audio), "elapsed": round(time.monotonic() - start, 2),
                        "createdAt": time.time(), "audioUrl": f"/api/audio/{clip_id}", "downloadUrl": f"/api/audio/{clip_id}?download=1",
                        "payload": payload, "vendorMetadata": vendor_metadata}
            with self.lock:
                stored_size = len(audio) + (len(original_audio) if converted else 0)
                if stored_size > MAX_AUDIO_BYTES:
                    raise UserError("单条音频超出本机缓存上限，请缩短文本。", 502)
                while self.audio and (len(self.audio) >= MAX_CLIPS or self.audio_bytes + stored_size > MAX_AUDIO_BYTES):
                    _, removed = self.audio.popitem(last=False)
                    self.audio_bytes -= removed["size"]
                self.audio[clip_id] = {"audio": audio, "original": original_audio if converted else None,
                                       "metadata": metadata, "size": stored_size}
                self.audio_bytes += stored_size
            return metadata
        finally:
            self.active.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "TTSStudio/0.1"

    @property
    def studio(self):
        return self.server.studio

    def log_message(self, format_string, *args):
        # Text, request bodies, audio URLs and credentials stay out of logs.
        return

    def send_bytes(self, data, content_type, status=200, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    def send_json(self, data, status=200):
        self.send_bytes(json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

    def check_host(self):
        valid = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host", "").lower() not in valid:
            raise UserError("仅支持通过本机地址访问。", 403)
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + host for host in valid}:
            raise UserError("拒绝跨站请求。", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise UserError("拒绝跨站请求。", 403)

    def do_GET(self):
        try:
            self.check_host()
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/catalog":
                with self.studio.lock:
                    result = copy.deepcopy(self.studio.catalog)
                self.send_json(result)
            elif path == "/api/settings":
                self.send_json(self.studio.status())
            elif path.startswith("/api/audio/"):
                clip_id = path.rsplit("/", 1)[-1]
                with self.studio.lock:
                    clip = self.studio.audio.get(clip_id)
                if not clip:
                    raise UserError("音频已从内存中释放，请重新合成。", 404)
                download = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("download") == ["1"]
                meta = clip["metadata"]
                fmt = meta["originalFormat"] if download else meta["format"]
                audio = (clip["original"] or clip["audio"]) if download else clip["audio"]
                headers = {"Accept-Ranges": "none"}
                if download:
                    headers["Content-Disposition"] = f'attachment; filename="{meta["provider"]}-{clip_id[:8]}.{fmt}"'
                self.send_bytes(audio, MIME[fmt], extra_headers=headers)
            elif path in ("/", "/index.html", "/app.js", "/style.css"):
                filename = "index.html" if path == "/" else path[1:]
                content_type = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}[filename]
                self.send_bytes((ROOT / "web" / filename).read_bytes(), content_type)
            else:
                raise UserError("未找到页面。", 404)
        except UserError as exc:
            self.send_json({"error": self.studio.redact(str(exc))}, exc.status)
        except Exception:
            self.send_json({"error": "本地服务读取数据失败。"}, 500)

    def do_POST(self):
        try:
            # Consume bounded bodies before rejecting headers. Closing a Windows
            # socket with unread POST data can reset it before the error arrives.
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise UserError("无效请求长度。") from None
            if not 0 < length <= MAX_BODY:
                raise UserError("请求为空或过大。", 413)
            raw_body = self.rfile.read(length)
            self.check_host()
            token = self.headers.get("X-Session-Token", "")
            if not secrets.compare_digest(token, self.studio.token):
                raise UserError("会话已失效，请刷新页面。", 403)
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise UserError("请使用 application/json。", 415)
            try:
                body = json.loads(raw_body)
            except (ValueError, UnicodeError):
                raise UserError("请求 JSON 无效。") from None
            if not isinstance(body, dict):
                raise UserError("请求必须是 JSON 对象。")
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/settings":
                result = self.studio.update_settings(body)
            elif path == "/api/preview":
                job = validate_job(body)
                payload, fmt, sample_rate = build_payload(job)
                result = {"payload": payload, "format": fmt, "sampleRate": sample_rate}
            elif path == "/api/synthesize":
                result = self.studio.synthesize(body)
            elif path == "/api/voices/refresh":
                result = self.studio.refresh_voices()
            else:
                raise UserError("未找到接口。", 404)
            self.send_json(result)
        except UserError as exc:
            self.send_json({"error": self.studio.redact(str(exc))}, exc.status)
        except Exception:
            self.send_json({"error": "处理上游响应失败，请检查接口版本、模型和音色是否兼容。"}, 502)


def main():
    parser = argparse.ArgumentParser(description="Local multi-vendor TTS Studio")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    load_env(ROOT / ".env")
    studio = Studio(settings_path=ROOT / "settings.local.json")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.studio = studio
    print(f"TTS Studio: http://127.0.0.1:{server.server_port}", flush=True)
    print("Connection settings are saved locally; generated audio remains in memory. Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
