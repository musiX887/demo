"""Current official control contracts, stream completion, and HTTP paths."""
import base64
import io
import json
import unittest
import wave
from unittest.mock import patch

from test_server import job, wav_bytes
import server


def sse(*events):
    return b"\n\n".join(b"data: " + json.dumps(event).encode() for event in events) + b"\n\n"


class CurrentContractTests(unittest.TestCase):
    def test_qwen_audio_all_native_controls(self):
        params = {"speed": 1.2, "volume": 60, "pitch": .9, "seed": 65535, "format": "opus", "sample_rate": 48000, "opus_bitrate": 64,
                  "instructions": "开心", "language_hints": "zh", "ssml": True, "timestamps": True, "aigc": True,
                  "aigc_propagator": "test", "aigc_propagate_id": "123", "hot_fix": '{"pronunciation":[{"重庆":"chong2 qing4"}],"replace":[{"本日":"今天"}]}'}
        payload, fmt, rate = server.build_payload(job("qwen", model="qwen-audio-3.1-tts-flash", params=params))
        self.assertEqual((fmt, rate), ("opus", 48000))
        native = payload["input"]
        self.assertEqual(native["instruction"], "开心")
        self.assertEqual(native["rate"], 1.2)
        self.assertEqual(native["bit_rate"], 64)
        self.assertEqual(native["language_hints"], ["zh"])
        self.assertTrue(all(native[key] for key in ["enable_ssml", "word_timestamp_enabled", "enable_aigc_tag"]))
        self.assertEqual(native["hot_fix"]["replace"], [{"本日": "今天"}])
        self.assertNotIn("instructions", native)

    def test_qwen_workspace_region_and_path(self):
        endpoint = server.qwen_adapter.endpoint
        for region, location in [("cn", "cn-beijing"), ("intl", "ap-southeast-1")]:
            self.assertEqual(endpoint("qwen-audio-3.1-tts-flash", {"region": region, "workspace_id": "ws-123"}, server.UserError),
                             f"https://ws-123.{location}.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer")
        for workspace in ["", "evil.com", "a/b", "a@b", "x\nheader"]:
            with self.subTest(workspace=workspace), self.assertRaises(server.UserError):
                endpoint("qwen-audio-3.1-tts-flash", {"workspace_id": workspace}, server.UserError)
        self.assertIn("dashscope-intl.aliyuncs.com", endpoint("qwen3-tts-flash", {"region": "intl"}, server.UserError))

    def test_qwen_legacy_length_and_unsupported_extra(self):
        server.build_payload(job("qwen", text="测" * 600))
        for change in [{"text": "测" * 601}, {"extra": {"input": {"rate": 1.3}}}]:
            with self.subTest(change=change), self.assertRaises(server.UserError):
                server.build_payload(job("qwen", **change))

    def test_qwen_invalid_encoding_and_hotfix(self):
        for params in [{"format": "opus", "sample_rate": 22050}, {"seed": 65536}, {"volume": 50.5}, {"hot_fix": "[]"}, {"hot_fix": '{"pronunciation":["wrong"]}'}, {"timestamps": "true"}, {"language_hints": "invented"}]:
            with self.subTest(params=params), self.assertRaises(server.UserError):
                server.build_payload(job("qwen", model="qwen-audio-3.1-tts-flash", params=params))

    def test_official_qwen_voice_capabilities_and_regions(self):
        voices = server.PROVIDERS["qwen"]["voices"]
        mary = next(v for v in voices if v["id"] == "loongmary")
        for params in [{"instructions": "开心"}, {"ssml": True}, {"timestamps": True}]:
            with self.subTest(params=params), self.assertRaises(server.UserError):
                server.build_payload(job("qwen", model="qwen-audio-3.0-tts-flash", voice=mary["id"], params=params))
        with self.assertRaises(server.UserError):
            server.build_payload(job("qwen", model="qwen3-tts-flash", voice=mary["id"]))
        restricted = next(v for v in voices if v.get("regions") == ["cn"])
        studio = server.Studio()
        studio.update_settings({"provider": "qwen", "region": "intl", "fields": {"api_key": "test", "workspace_id": "ws-test"}})
        with patch.object(server, "api_request") as upstream, self.assertRaises(server.UserError):
            studio.synthesize(job("qwen", model=restricted["models"][0], voice=restricted["id"]))
        upstream.assert_not_called()

    def test_qwen_stream_audio_timestamps_and_completion(self):
        raw = sse({"output": {"audio": {"data": base64.b64encode(b"part").decode()}, "type": "sentence-synthesis", "sentence": {"words": [{"text": "你", "begin_time": 0}]}}},
                  {"output": {"finish_reason": "stop", "audio": {}}, "usage": {"characters": 1}})
        audio, final, events = server.qwen_adapter.parse_sse(raw, server.UserError)
        self.assertEqual(audio, b"part")
        self.assertEqual(final["usage"]["characters"], 1)
        self.assertEqual(len(events), 1)
        for broken in [raw.split(b"\n\n")[0], sse({"output": {"audio": []}}), sse({"code": "InvalidParameter", "message": "bad"})]:
            with self.assertRaises(server.UserError):
                server.qwen_adapter.parse_sse(broken, server.UserError)

    def test_qwen_audio_http_sse_and_pcm_download(self):
        studio = server.Studio()
        studio.update_settings({"provider": "qwen", "fields": {"api_key": "secret", "workspace_id": "ws-test"}})
        pcm = b"\x00\x00" * 24
        raw = sse({"output": {"audio": {"data": base64.b64encode(pcm).decode()}, "sentence": {"text": "你好"}}}, {"output": {"finish_reason": "stop"}, "request_id": "test-request"})
        with patch.object(server, "api_request", return_value=raw) as upstream:
            result = studio.synthesize(job("qwen", model="qwen-audio-3.1-tts-flash", params={"timestamps": True, "format": "pcm"}))
        self.assertIn("ws-test.cn-beijing.maas.aliyuncs.com", upstream.call_args.args[0])
        self.assertEqual(upstream.call_args.args[2]["X-DashScope-SSE"], "enable")
        self.assertEqual(result["vendorMetadata"]["requestId"], "test-request")
        self.assertEqual(studio.audio[result["id"]]["original"], pcm)
        self.assertEqual(result["format"], "wav")

    def test_minimax_modification_mix_normalization(self):
        params = {"voice_pitch": 25, "intensity": -10, "timbre": 12, "sound_effects": "robotic", "normalization_mode": "quality",
                  "mix_enabled": True, "timbre_weights": [{"voice_id": "v1", "weight": 75}, {"voice_id": "v2", "weight": 25}], "subtitle": True, "subtitle_type": "word", "aigc": True, "channel": 2}
        payload, _, _ = server.build_payload(job(model="speech-2.8-hd", params=params))
        self.assertEqual(payload["voice_modify"], {"pitch": 25, "intensity": -10, "timbre": 12, "sound_effects": "robotic"})
        self.assertEqual(payload["voice_setting"]["voice_id"], "")
        self.assertEqual(payload["timbre_weights"], params["timbre_weights"])
        self.assertEqual(payload["text_normalization_mode"], "quality")
        self.assertEqual(payload["subtitle_type"], "word")
        self.assertTrue(payload["aigc_watermark"])
        self.assertEqual(payload["audio_setting"]["channel"], 2)

    def test_minimax_model_and_format_restrictions(self):
        for model, params in [("speech-2.8-hd", {"emotion": "whisper"}), ("speech-2.6-hd", {"volume": 0}), ("speech-02-hd", {"normalization_mode": "quality"}),
                              ("speech-2.8-hd", {"voice_pitch": 2, "format": "pcm"}), ("speech-2.8-hd", {"voice_pitch": 2, "format": "wav", "vendor_stream": True}),
                              ("speech-2.8-hd", {"format": "pcmu_raw", "sample_rate": 24000}), ("speech-2.8-hd", {"force_cbr": True}),
                              ("speech-2.8-hd", {"aigc": True, "vendor_stream": True}), ("speech-2.8-hd", {"mix_enabled": True, "timbre_weights": [{"voice_id": "a", "weight": 0}]})]:
            with self.subTest(model=model, params=params), self.assertRaises(server.UserError):
                server.build_payload(job(model=model, params=params))
        payload, _, _ = server.build_payload(job(model="speech-2.6-hd", params={"emotion": "whisper"}))
        self.assertEqual(payload["voice_setting"]["emotion"], "whisper")
        payload, _, _ = server.build_payload(job(params={"subtitle": True, "subtitle_type": "word_streaming", "force_cbr": True}))
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["stream_options"], {"exclude_aggregated_audio": True})

    def test_minimax_stream_deduplicates_subtitle_updates(self):
        begin = {"text_begin": 0, "text": "你"}
        end = {"text_begin": 0, "text": "你好"}
        raw = sse({"data": {"status": 1, "audio": "0001", "subtitle": begin}}, {"data": {"status": 1, "audio": "0203", "subtitle": end}}, {"data": {"status": 2, "audio": "00010203", "subtitles": [end]}, "trace_id": "trace"})
        audio, metadata = server.minimax_adapter.parse_sse(raw, server.UserError)
        self.assertEqual(audio, bytes.fromhex("00010203"))
        self.assertEqual(metadata["subtitles"], [end])
        self.assertEqual(metadata["trace_id"], "trace")
        with self.assertRaises(server.UserError):
            server.minimax_adapter.parse_sse(raw.split(b"\n\n")[0], server.UserError)

    def test_minimax_stereo_pcm_and_ulaw_playback(self):
        studio = server.Studio()
        studio.update_settings({"provider": "minimax", "fields": {"api_key": "test"}})
        for fmt, rate, original in [("pcm", 24000, b"\0\0" * 12), ("pcmu_raw", 8000, b"\xff\x7f" * 6)]:
            with self.subTest(fmt=fmt), patch.object(server, "request_json", return_value={"data": {"audio": original.hex()}}):
                result = studio.synthesize(job(params={"format": fmt, "sample_rate": rate, "channel": 2}))
                saved = studio.audio[result["id"]]
                self.assertEqual(saved["original"], original)
                with wave.open(io.BytesIO(saved["audio"]), "rb") as reader:
                    self.assertEqual(reader.getnchannels(), 2)
                    self.assertEqual(reader.getframerate(), rate)
                    if fmt == "pcmu_raw":
                        self.assertEqual(reader.readframes(100), b"\0\0" * len(original))

    def test_catalog_models_have_complete_official_lists(self):
        for provider in server.PROVIDERS.values():
            self.assertTrue(provider["voices"], provider["id"])
            for model in provider["models"]:
                voices = [v for v in provider["voices"] if not v.get("models") or model["id"] in v["models"]]
                self.assertTrue(voices, model["id"])
                self.assertTrue(all(v["verified"] and v["source"] for v in voices))
                self.assertEqual(len({v["id"] for v in voices}), len(voices), model["id"])
        qwen3 = [v for v in server.PROVIDERS["qwen"]["voices"] if "qwen3-tts-flash" in v.get("models", [])]
        self.assertEqual(len(qwen3), 48)
        self.assertEqual(len(server.PROVIDERS["minimax"]["models"]), 8)


if __name__ == "__main__":
    unittest.main()
