"""Offline adapter and HTTP integration checks; never contact vendor APIs."""
import base64
import concurrent.futures
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def job(provider="minimax", **changes):
    value = {"provider": provider, "model": {"minimax": "speech-02-hd", "doubao": "seed-tts-1.0", "qwen": "qwen3-tts-flash"}.get(provider, "invalid-model"),
             "voice": "test-voice", "text": "你好，hello。", "params": {}, "extra": {}}
    value.update(changes)
    return value


def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\x00\x00" * 240)
    return buffer.getvalue()


class AdapterTests(unittest.TestCase):
    def test_minimax_controls_reach_native_fields(self):
        payload, fmt, rate = server.build_payload(job(params={"speed": 1.3, "volume": 2, "pitch": -3, "emotion": "angry", "format": "mp3", "sample_rate": 44100, "bitrate": 256000, "pronunciation": ["处理/(chu3)(li3)"], "latex_read": True}))
        self.assertEqual(payload["voice_setting"], {"voice_id": "test-voice", "speed": 1.3, "vol": 2, "pitch": -3, "emotion": "angry", "latex_read": True})
        self.assertEqual(payload["pronunciation_dict"]["tone"], ["处理/(chu3)(li3)"])
        self.assertEqual((fmt, rate), ("mp3", 44100))
        self.assertEqual(payload["audio_setting"]["bitrate"], 256000)
        self.assertNotIn("english_normalization", payload)
        self.assertTrue(payload["voice_setting"]["latex_read"])
        self.assertEqual(payload["language_boost"], "Chinese")

    def test_mp3_bitrate_omitted_for_wav(self):
        payload, _, _ = server.build_payload(job(params={"format": "wav"}))
        self.assertNotIn("bitrate", payload["audio_setting"])

    def test_qwen_plain_has_no_fake_emotion_or_speed_controls(self):
        payload, _, _ = server.build_payload(job("qwen", params={"speed": 2, "emotion": "happy", "instructions": "开心"}))
        self.assertEqual(payload, {"model": "qwen3-tts-flash", "input": {"text": "你好，hello。", "voice": "test-voice", "language_type": "Auto"}})

    def test_qwen_audio_instructions(self):
        payload, _, _ = server.build_payload(job("qwen", model="qwen-audio-3.1-tts-flash", params={"instructions": "开心地说，语速快一点", "speed": 1.4, "pitch": .8, "volume": 70}))
        self.assertEqual(payload["input"]["instruction"], "开心地说，语速快一点")
        self.assertEqual(payload["input"]["rate"], 1.4)
        self.assertEqual(payload["input"]["volume"], 70)
        self.assertEqual(payload["input"]["pitch"], .8)
        self.assertNotIn("optimize_instructions", payload["input"])

    def test_doubao_uses_native_rate_and_emotion(self):
        voice = next(v for v in server.PROVIDERS['doubao']['voices']
                     if 'seed-tts-1.0' in v.get('models', [])
                     and any((item.get('id') if isinstance(item, dict) else item) == 'sad'
                             for item in v.get('emotions', [])))
        payload, _, _ = server.build_payload(job("doubao", voice=voice['id'], params={"speed": -20, "volume": 15, "emotion": "sad", "emotion_scale": 5}))
        self.assertEqual(payload["req_params"]["audio_params"], {"format": "mp3", "sample_rate": 24000, "speech_rate": -20, "loudness_rate": 15, "bit_rate": 64000, "emotion": "sad", "emotion_scale": 5})

    def test_doubao_omits_implicit_emotion(self):
        payload, _, _ = server.build_payload(job("doubao"))
        self.assertNotIn("emotion", payload["req_params"]["audio_params"])
        self.assertNotIn("emotion_scale", payload["req_params"]["audio_params"])

    def test_extra_deep_merge_and_identity_invariants(self):
        payload, fmt, _ = server.build_payload(job(extra={"model": "wrong", "text": "wrong", "stream": False, "voice_setting": {"voice_id": "wrong", "speed": 1.5}, "audio_setting": {"format": "wav"}}))
        self.assertEqual(payload["model"], "speech-02-hd")
        self.assertEqual(payload["text"], "你好，hello。")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["voice_setting"]["voice_id"], "test-voice")
        self.assertEqual(payload["voice_setting"]["speed"], 1.5)
        self.assertEqual(fmt, "wav")

    def test_bad_inputs_fail_before_cloud_call(self):
        cases = [job(params={"speed": 30}), job(params={"speed": float("nan")}), job(params={"speed": True}), job(params={"pitch": 1.5}), job(params={"emotion": "invented"}), job(params={"format": "exe"}), job(params={"sample_rate": 48000}), job(params={"latex_read": "false"}), job(extra={"voice_setting": None})]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(server.UserError):
                server.build_payload(case)
        for case in [job(provider="unknown"), job(voice=""), job(text=" " * 5), job(text="x" * 10001), job(extra=[]), job(extra={"endpoint": "https://evil.test"})]:
            with self.subTest(case=case), self.assertRaises(server.UserError):
                server.validate_job(case)

    def test_custom_models_only_have_base_controls(self):
        payload, _, _ = server.build_payload(job(model="future-model", params={"speed": 2, "emotion": "sad"}))
        self.assertEqual(payload["voice_setting"], {"voice_id": "test-voice"})

    def test_doubao_ndjson_audio_chunks_and_errors(self):
        raw = b'\n'.join(json.dumps(item).encode() for item in [
            {"code": 0, "data": base64.b64encode(b"part1").decode()},
            {"code": 0, "data": base64.b64encode(b"part2").decode()},
            {"code": 20000000, "message": "ok"}])
        self.assertEqual(server.parse_doubao(raw), b"part1part2")
        for data in [b'{"code":123,"message":"bad voice"}', b'{"code":0,"data":"%%%"}', b'{"code":20000000}', b'not json']:
            with self.subTest(data=data), self.assertRaises(server.UserError):
                server.parse_doubao(data)

    def test_minimax_hex_and_error(self):
        self.assertEqual(server.parse_minimax({"base_resp": {"status_code": 0}, "data": {"audio": "000102"}}), b"\x00\x01\x02")
        for result in [{"base_resp": {"status_code": 1001, "status_msg": "bad key"}}, {"data": {"audio": "invalid"}}, {}]:
            with self.assertRaises(server.UserError):
                server.parse_minimax(result)

    def test_pcm_wrapping_preserves_frames(self):
        pcm = b"\x00\x00\xff\x7f" * 120
        with wave.open(io.BytesIO(server.pcm_to_wav(pcm, 24000)), "rb") as reader:
            self.assertEqual(reader.getframerate(), 24000)
            self.assertEqual(reader.getnchannels(), 1)
            self.assertEqual(reader.getsampwidth(), 2)
            self.assertEqual(reader.readframes(1000), pcm)

    def test_audio_url_allowlist(self):
        server.check_url("https://result.oss-cn-beijing.aliyuncs.com/audio.wav", ("aliyuncs.com",))
        for url in ["http://foo.aliyuncs.com/audio", "https://aliyuncs.com.evil.test/a", "https://evilaliyuncs.com/a", "https://127.0.0.1/a", "https://key@foo.aliyuncs.com/a", "https://foo.aliyuncs.com:8443/a"]:
            with self.subTest(url=url), self.assertRaises(server.UserError):
                server.check_url(url, ("aliyuncs.com",))

    def test_qwen_signed_http_audio_uses_https(self):
        original = "http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a%2Fb.wav?Expires=123&Signature=a%2Bb%2F%3D&OSSAccessKeyId=test"
        expected = "https" + original[4:]
        self.assertEqual(server.normalize_qwen_audio_url(original), expected)
        self.assertEqual(server.normalize_qwen_audio_url(original.replace(".com/", ".com:80/")), expected)
        self.assertEqual(server.normalize_qwen_audio_url(expected), expected)
        with patch.object(server.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(b"wav-audio")
            self.assertEqual(server.download_qwen_audio(original), b"wav-audio")
            opener.return_value.open.assert_called_once_with(expected, timeout=120)

    def test_qwen_audio_normalization_rejects_unsafe_urls_before_download(self):
        urls = ["http://127.0.0.1/a.wav", "http://aliyuncs.com.evil.test/a.wav",
                "http://evilaliyuncs.com/a.wav", "http://key@foo.aliyuncs.com/a.wav",
                "http://foo.aliyuncs.com:8080/a.wav", "https://foo.aliyuncs.com:80/a.wav",
                "http://foo.aliyuncs.com:bad/a.wav", "file:///audio.wav", "//foo.aliyuncs.com/a.wav"]
        for url in urls:
            with self.subTest(url=url), patch.object(server.urllib.request, "build_opener") as opener, self.assertRaises(server.UserError):
                try:
                    server.download_qwen_audio(url)
                finally:
                    opener.assert_not_called()

    def test_qwen_redirect_upgrades_official_host_and_rejects_other_hosts(self):
        redirect = server.SafeRedirect(server.QWEN_AUDIO_SUFFIXES, server.normalize_qwen_audio_url)
        request = urllib.request.Request("https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a.wav")
        url = "http://result.oss-cn-beijing.aliyuncs.com/b.wav?Signature=a%2Bb%3D"
        redirected = redirect.redirect_request(request, None, 302, "Found", {}, url)
        self.assertEqual(redirected.full_url, "https" + url[4:])
        with self.assertRaises(server.UserError):
            redirect.redirect_request(request, None, 302, "Found", {}, "http://127.0.0.1/private")


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "settings.local.json"

    def test_restart_restores_settings_and_blank_fields_preserve_values(self):
        studio = server.Studio(self.path)
        studio.update_settings({"provider": "qwen", "region": "intl", "fields": {"api_key": "test-key", "workspace_id": "test-workspace"}})
        studio.update_settings({"provider": "minimax", "fields": {"api_key": "other-key"}})
        studio.update_settings({"provider": "qwen", "region": "intl", "fields": {"api_key": "", "workspace_id": "new-workspace"}})
        restored = server.Studio(self.path)
        self.assertEqual(restored.get_credentials("qwen"), {"api_key": "test-key", "workspace_id": "new-workspace", "region": "intl"})
        self.assertEqual(restored.get_credentials("minimax")["api_key"], "other-key")
        response = json.dumps(restored.status())
        for secret in ("test-key", "new-workspace", "other-key"):
            self.assertNotIn(secret, response)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_clear_stays_cleared_after_restart_even_with_environment_defaults(self):
        with patch.dict(server.os.environ, {"DASHSCOPE_API_KEY": "environment-key", "QWEN_WORKSPACE_ID": "environment-space"}):
            studio = server.Studio(self.path)
            studio.update_settings({"provider": "qwen", "fields": {"api_key": "test-key"}})
            studio.update_settings({"provider": "qwen", "clear": True, "fields": {"api_key": "ignored"}})
            restored = server.Studio(self.path)
        self.assertFalse(restored.status()["providers"]["qwen"]["configured"])
        self.assertEqual(restored.credentials["qwen"], {"api_key": "", "workspace_id": "", "region": "cn"})
        self.assertNotIn("test-key", self.path.read_text(encoding="utf-8"))
        self.assertNotIn("environment-key", self.path.read_text(encoding="utf-8"))

    def test_failed_write_keeps_previous_file_and_memory(self):
        studio = server.Studio(self.path)
        studio.update_settings({"provider": "qwen", "fields": {"api_key": "old-key", "workspace_id": "old-space"}})
        original = self.path.read_bytes()
        with patch.object(server.os, "replace", side_effect=PermissionError("private-error-detail")), self.assertRaises(server.UserError) as error:
            studio.update_settings({"provider": "qwen", "fields": {"api_key": "new-key"}})
        self.assertNotIn("private-error-detail", str(error.exception))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(studio.get_credentials("qwen")["api_key"], "old-key")
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_parallel_saves_keep_all_providers(self):
        studio = server.Studio(self.path)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(studio.update_settings, [{"provider": provider, "fields": {"api_key": provider + "-key"}} for provider in server.ENV_FIELDS]))
        restored = server.Studio(self.path)
        for provider in server.ENV_FIELDS:
            self.assertEqual(restored.get_credentials(provider)["api_key"], provider + "-key")

    def test_invalid_local_file_is_not_overwritten_or_exposed(self):
        for content in ("private-malformed-content", '{"version": 1, "providers": {"qwen": {"api_key": "secret"}}}'):
            self.path.write_text(content, encoding="utf-8")
            with self.assertRaises(server.UserError) as error:
                server.Studio(self.path)
            self.assertNotIn("secret", str(error.exception))
            self.assertEqual(self.path.read_text(encoding="utf-8"), content)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.studio = server.Studio(Path(cls.directory.name) / "settings.local.json")
        cls.http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.http.studio = cls.studio
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=3)
        cls.directory.cleanup()

    def request(self, path, data=None, headers=None):
        request = urllib.request.Request(self.base + path, data=json.dumps(data).encode() if data is not None else None,
                                         headers={"Content-Type": "application/json", "X-Session-Token": self.studio.token, **(headers or {})})
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_static_assets_catalog_and_no_secret_files(self):
        for path in ["/", "/app.js", "/style.css", "/api/catalog"]:
            self.assertEqual(self.request(path)[0], 200)
        for path in ["/.env", "/settings.local.json", "/settings.local.json.fake.tmp", "/server.py", "/../server.py", "/web/../../.env"]:
            self.assertEqual(self.request(path)[0], 404)

    def test_rejects_host_spoofing_and_cross_site_writes(self):
        self.assertEqual(self.request("/api/settings", headers={"Host": "evil.test"})[0], 403)
        self.assertEqual(self.request("/api/preview", job(), {"Origin": "https://evil.test"})[0], 403)
        self.assertEqual(self.request("/api/preview", job(), {"X-Session-Token": "wrong"})[0], 403)
        self.assertEqual(self.request("/api/settings", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_credentials_are_never_echoed_and_can_be_cleared(self):
        status, _, _ = self.request("/api/settings", {"provider": "qwen", "region": "cn", "fields": {"api_key": "private-test-key"}})
        self.assertEqual(status, 200)
        result = self.request("/api/settings")[2]
        self.assertNotIn(b"private-test-key", result)
        self.assertTrue(json.loads(result)["providers"]["qwen"]["configured"])
        restored = server.Studio(self.studio.settings_path)
        self.assertEqual(restored.get_credentials("qwen")["api_key"], "private-test-key")
        self.assertEqual(self.request("/settings.local.json")[0], 404)
        self.assertEqual(self.studio.redact("bad private-test-key"), "bad [已隐藏]")
        self.request("/api/settings", {"provider": "qwen", "clear": True})
        self.assertFalse(self.studio.status()["providers"]["qwen"]["configured"])

    def test_preview_works_without_credentials(self):
        status, _, raw = self.request("/api/preview", job("qwen"))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["payload"]["input"]["voice"], "test-voice")

    def test_full_qwen_adapter_audio_and_download(self):
        self.studio.update_settings({"provider": "qwen", "fields": {"api_key": "test-key"}, "region": "cn"})
        audio = wav_bytes()
        audio_url = "http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a.wav?Signature=a%2Bb%3D"
        with patch.object(server, "request_json", return_value={"output": {"audio": {"url": audio_url}}}) as upstream, patch.object(server.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(audio)
            status, _, raw = self.request("/api/synthesize", job("qwen"))
            opener.return_value.open.assert_called_once_with("https" + audio_url[4:], timeout=120)
        self.assertEqual(status, 200, raw)
        result = json.loads(raw)
        self.assertNotIn("test-key", raw.decode())
        self.assertIn("dashscope.aliyuncs.com", upstream.call_args.args[0])
        self.assertEqual(self.request(result["audioUrl"])[2], audio)
        status, headers, data = self.request(result["downloadUrl"])
        self.assertEqual(data, audio)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(self.request("/api/audio/does-not-exist")[0], 404)

    def test_doubao_stream_and_pcm_download(self):
        self.studio.update_settings({"provider": "doubao", "fields": {"app_id": "test-app", "api_key": "test-token", "resource_id": "custom-resource"}})
        pcm = b"\x00\x00" * 240
        raw = json.dumps({"code": 0, "data": base64.b64encode(pcm).decode()}).encode() + b'\n{"code":20000000}'
        with patch.object(server, "api_request", return_value=raw) as upstream:
            status, _, body = self.request("/api/synthesize", job("doubao", params={"format": "pcm"}))
        self.assertEqual(status, 200, body)
        result = json.loads(body)
        self.assertEqual(result["format"], "wav")
        self.assertEqual(self.request(result["audioUrl"])[2][:4], b"RIFF")
        self.assertEqual(self.request(result["downloadUrl"])[2], pcm)
        self.assertEqual(upstream.call_args.args[2]["X-Api-Resource-Id"], "custom-resource")

    def test_minimax_system_voice_refresh(self):
        self.studio.update_settings({"provider": "minimax", "fields": {"api_key": "test-key"}, "region": "intl"})
        with patch.object(server, "request_json", return_value={"base_resp": {"status_code": 0}, "system_voice": [{"voice_id": "official-voice", "voice_name": "Official Voice"}]}) as upstream:
            status, _, raw = self.request("/api/voices/refresh", {})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["count"], 1)
        self.assertEqual(upstream.call_args.args[0], "https://api.minimax.io/v1/get_voice")
        result = json.loads(self.request("/api/catalog")[2])
        voices = next(p for p in result["providers"] if p["id"] == "minimax")["voices"]
        self.assertTrue(voices[0]["verified"])
        self.assertEqual(voices[0]["id"], "official-voice")

    def test_cache_evicts_oldest_clip(self):
        self.studio.update_settings({"provider": "minimax", "fields": {"api_key": "test-key"}})
        with self.studio.lock:
            self.studio.audio.clear()
            self.studio.audio_bytes = 0
        with patch.object(server, "MAX_CLIPS", 2), patch.object(server, "request_json", return_value={"data": {"audio": "0001"}}):
            results = [self.studio.synthesize(job()) for _ in range(3)]
        self.assertEqual(self.request(results[0]["audioUrl"])[0], 404)
        self.assertEqual(self.request(results[2]["audioUrl"])[0], 200)
        self.assertEqual(len(self.studio.audio), 2)

    def test_parallel_requests_and_capacity_failure(self):
        self.studio.update_settings({"provider": "minimax", "fields": {"api_key": "test-key"}})
        with patch.object(server, "request_json", return_value={"data": {"audio": "0001"}}), concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: self.request("/api/synthesize", job()), range(3)))
        self.assertTrue(all(result[0] == 200 for result in results))
        for _ in range(3):
            self.studio.active.acquire()
        try:
            self.assertEqual(self.request("/api/synthesize", job())[0], 429)
        finally:
            for _ in range(3):
                self.studio.active.release()


if __name__ == "__main__":
    unittest.main(verbosity=2)
