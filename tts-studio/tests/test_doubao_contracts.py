"""Doubao official field combinations and completed stream playback."""
import io
import json
import unittest
import wave

from test_server import job, wav_bytes
import server


def doubao(model="seed-tts-2.0", **changes):
    voice = next(v for v in server.PROVIDERS["doubao"]["voices"] if model in v.get("models", []) and (model != "seed-tts-2.0" or v["id"] == "zh_female_vv_uranus_bigtts"))
    return job("doubao", model=model, voice=voice["id"], **changes)


class DoubaoContractTests(unittest.TestCase):
    def test_form_controls_serialize_into_additions(self):
        params = {"instructions": "开心", "silence_duration": 500, "enable_auto_language_recognition": True,
                  "explicit_language": "zh-cn", "explicit_dialect": "sichuan", "context_language": "id",
                  "disable_markdown_filter": True, "disable_emoji_filter": True, "enable_latex_tn": True,
                  "latex_parser": "v2", "max_length_to_filter_parenthesis": 50,
                  "unsupported_char_ratio_thresh": .4, "aigc_watermark": True,
                  "aigc_metadata": {"enable": True, "content_producer": "test"},
                  "cache_config": {"text_type": 1, "use_cache": False}, "pronunciation": ["重庆/(chong2)(qing4)"], "section_id": "session-1"}
        payload, _, _ = server.build_payload(doubao(params=params))
        self.assertIsInstance(payload["req_params"]["additions"], str)
        additions = json.loads(payload["req_params"]["additions"])
        for key in ("silence_duration", "explicit_language", "explicit_dialect", "context_language", "disable_markdown_filter", "disable_emoji_filter", "enable_latex_tn", "latex_parser", "section_id"):
            self.assertEqual(additions[key], params[key])
        self.assertEqual(additions["context_texts"], ["开心"])
        self.assertEqual(additions["pronunciation_dict"]["tone"], params["pronunciation"])
        self.assertTrue(additions["aigc_metadata"]["enable"])
        self.assertFalse(additions["cache_config"]["use_cache"])

    def test_invalid_combinations_and_extra_cannot_bypass(self):
        additions = [
            {"silence_duration": -1}, {"silence_duration": 30001}, {"silence_duration": True},
            {"disable_markdown_filter": "true"}, {"enable_latex_tn": True}, {"latex_parser": "v3"},
            {"context_language": "invented"}, {"explicit_language": "fake"},
            {"explicit_dialect": "fake"}, {"aigc_metadata": {"enable": "true"}},
            {"cache_config": {"use_cache": "true"}}, {"cache_config": {"text_type": True}},
            {"pronunciation_dict": {"tone": ["wrong"]}}, {"pronunciation_dict": {"tone": ["重 庆/读音"]}},
            {"pronunciation_dict": {"tone": ["重庆/a", "重庆/b"]}},
            {"tone_fidelity": True}, {"use_tag_parser": True}, {"mute_cut_threshold": "400", "mute_cut_remain_ms": "50"},
        ]
        for value in additions:
            with self.subTest(value=value), self.assertRaises(server.UserError):
                server.build_payload(doubao(extra={"req_params": {"additions": json.dumps(value)}}))
        for params in [{"format": "pcm", "aigc_metadata": {"enable": True}},
                       {"enable_subtitle": True, "cache_config": {"text_type": 1, "use_cache": True}},
                       {"enable_subtitle": True, "enable_latex_tn": True, "disable_markdown_filter": True},
                       {"timestamps": True, "disable_default_bit_rate": True, "bitrate": 12345}]:
            with self.subTest(params=params), self.assertRaises(server.UserError):
                server.build_payload(doubao(params=params))

    def test_catalogue_unsupported_s2s_and_voice_dialect(self):
        record = next(v for v in server.PROVIDERS["doubao"]["voices"] if v.get("models") == [])
        with self.assertRaises(server.UserError):
            server.build_payload(job("doubao", model="seed-tts-2.0", voice=record["id"]))
        with self.assertRaises(server.UserError):
            server.build_payload(doubao("seed-tts-1.0", params={"explicit_dialect": "sichuan"}))
        self.assertNotIn("ssml", server.effective_controls("doubao", "seed-tts-2.0", "zh_female_vv_uranus_bigtts"))

    def test_ssml_and_silence_trim_1_0(self):
        payload, _, _ = server.build_payload(doubao("seed-tts-1.0", text="<speak>你好</speak>", params={"ssml": True, "mute_cut_threshold": "400", "mute_cut_remain_ms": "50"}))
        self.assertEqual(payload["req_params"]["ssml"], "<speak>你好</speak>")
        self.assertEqual(json.loads(payload["req_params"]["additions"])["mute_cut_remain_ms"], "50")
        with self.assertRaises(server.UserError):
            server.build_payload(doubao("seed-tts-1.0", params={"ssml": True, "disable_markdown_filter": True}))

    def test_mix_weights_and_compatible_official_voices(self):
        voices = [v for v in server.PROVIDERS["doubao"]["voices"] if v.get("mixSupported")][:2]
        weights = [{"voice_id": voice["id"], "weight": 50} for voice in voices]
        payload, _, _ = server.build_payload(doubao("seed-tts-1.0", params={"mix_enabled": True, "timbre_weights": weights}))
        self.assertEqual(payload["req_params"]["speaker"], "custom_mix_bigtts")
        self.assertEqual([v["mix_factor"] for v in payload["req_params"]["mix_speaker"]["speakers"]], [.5, .5])
        self.assertNotIn("loudness_rate", payload["req_params"]["audio_params"])
        for weights in [[{"voice_id": voices[0]["id"], "weight": 25}], [{"voice_id": "zh_female_vv_uranus_bigtts", "weight": 100}]]:
            with self.subTest(weights=weights), self.assertRaises(server.UserError):
                server.build_payload(doubao("seed-tts-1.0", params={"mix_enabled": True, "timbre_weights": weights}))

    def test_repeated_wav_headers_are_merged(self):
        audio = wav_bytes()
        merged = server.normalize_wav_stream(audio + audio)
        with wave.open(io.BytesIO(merged), "rb") as reader:
            self.assertEqual(reader.getnframes(), 480)
            self.assertEqual(reader.getframerate(), 24000)
        for broken in [audio[:-1], b"bad", audio + b"bad"]:
            with self.subTest(broken=broken[:10]), self.assertRaises(server.UserError):
                server.normalize_wav_stream(broken)


if __name__ == "__main__":
    unittest.main()
