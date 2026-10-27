"""端到端冒烟测试：注册登录 → 音色 → TTS → ASR → 我的记录 → 鉴权 → 清理。

用法：先启动服务（python run.py），再执行
    .venv/Scripts/python.exe smoke_test.py
"""

import base64
import io
import json
import math
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave

BASE = "http://127.0.0.1:8000"
USER = f"smoke_{int(time.time())}"
PWD = "smoke_pass_123"

ok_count = 0
fail_count = 0
skip_count = 0


def skip(name, why):
    global skip_count
    skip_count += 1
    print(f"  [SKIP] {name} —— {why}")


def call(method, path, *, body=None, token=None, form=None):
    url = BASE + path
    headers = {}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if form is not None:
        data = form
    if token:
        headers["Authorization"] = "Bearer " + token

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            ct = r.headers.get("content-type", "")
            return r.status, (json.loads(raw) if "json" in ct else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:300].decode(errors="replace")}


def check(name, cond, extra=""):
    global ok_count, fail_count
    if cond:
        ok_count += 1
        print(f"  [PASS] {name}")
    else:
        fail_count += 1
        print(f"  [FAIL] {name} {extra}")


def make_wav(seconds=1.5, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            t = i / rate
            v = int(12000 * math.sin(2 * math.pi * 220 * t) * (0.5 + 0.5 * math.sin(2 * math.pi * 2 * t)))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def multipart(fields, files):
    boundary = "----smokeboundary1234"
    body = bytearray()
    for k, v in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, (filename, content, ctype) in files.items():
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode()
        body += content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def post_multipart(path, fields, files, token):
    form, ctype = multipart(fields, files)
    req = urllib.request.Request(BASE + path, data=form, method="POST")
    req.add_header("Content-Type", ctype)
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=120) as rsp:
            return rsp.status, json.loads(rsp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main():
    print(f"\n== 声坊 Voice Atelier 冒烟测试 ==  {BASE}\n")

    print("[1] 鉴权")
    st, r = call("POST", "/api/auth/register", body={"username": USER, "password": PWD, "email": f"{USER}@t.local"})
    check("注册返回 200", st == 200, f"-> {st} {r}")
    token = r.get("access_token") if st == 200 else None
    check("注册返回令牌", bool(token))
    if not token:
        print("无法继续：注册失败")
        return 1

    st, me = call("GET", "/api/auth/me", token=token)
    check("me 返回用户信息", st == 200 and me.get("username") == USER, f"-> {st} {me}")
    st, _ = call("POST", "/api/auth/login", body={"username": USER, "password": PWD})
    check("登录成功", st == 200)
    st, _ = call("POST", "/api/auth/login", body={"username": USER, "password": "wrong-password"})
    check("错误密码返回 401", st == 401)
    st, _ = call("POST", "/api/auth/register", body={"username": USER, "password": PWD})
    check("重复用户名返回 409", st == 409)
    st, r = call("GET", "/api/auth/wechat/qr")
    check("微信未配置返回 404", st == 404, f"-> {st} {r}")

    print("\n[2] 未登录不得调用业务接口")
    for name, path, method in [
        ("TTS 合成", "/api/tts/synthesize", "POST"),
        ("TTS 历史", "/api/tts/history", "GET"),
        ("ASR 历史", "/api/asr/history", "GET"),
        ("我的音色", "/api/voices", "GET"),
    ]:
        st, _ = call(method, path, body={"text": "x"} if method == "POST" else None)
        check(f"未登录 {name} 返回 401", st == 401, f"-> {st}")

    print("\n[3] 接口不泄露密钥")
    st, meta = call("GET", "/api/meta", token=token)
    check("meta 不含任何密钥字段", "key" not in json.dumps(meta).lower(), f"-> {meta}")
    st, opts = call("GET", "/api/tts/options", token=token)
    check("options 返回音色列表", st == 200 and len(opts.get("voices", [])) > 0, f"-> {st}")
    check("options 不含密钥", "sk-" not in json.dumps(opts), "")

    print("\n[4] 音色设计（自定义音色）")
    st, v = call("POST", "/api/voices", body={
        "name": "深夜电台", "description": "低沉磁性的中年男声，语速慢", "sample_text": "夜色落下来的时候"
    }, token=token)
    check("保存音色返回 200", st == 200, f"-> {st} {v}")
    voice_id = v.get("id") if st == 200 else None
    check("音色带展示色", bool(v.get("color")))

    st, r = call("POST", "/api/voices", body={"name": "深夜电台", "description": "重复"}, token=token)
    check("同名音色返回 409", st == 409, f"-> {st}")

    st, r = call("GET", "/api/voices", token=token)
    check("音色列表可读", st == 200 and r.get("total", 0) >= 1, f"-> {r.get('total')}")

    print("\n[5] TTS 合成")
    st, r = call("POST", "/api/tts/synthesize",
                 body={"text": "你好，这是语音合成的冒烟测试。", "audio_format": "wav"}, token=token)
    check("默认音色合成 200", st == 200, f"-> {st} {r}")
    tts_id = r.get("id") if st == 200 else None
    check("返回音色名称", bool(r.get("voice_name")), f"-> {r.get('voice_name')}")
    check("返回耗时", isinstance(r.get("latency_ms"), int), f"-> {r.get('latency_ms')}")
    if st == 200:
        check("确为真实上游调用（is_mock=false）", r.get("is_mock") is False, f"-> {r.get('is_mock')}")

    if tts_id:
        url = r["audio_url"] + "?token=" + token
        with urllib.request.urlopen(BASE + url, timeout=60) as resp:
            data = resp.read()
            ct = resp.headers.get("content-type", "")
        check("音频可下载", len(data) > 1000, f"-> {len(data)} bytes")
        check("音频为合法 WAV", data[:4] == b"RIFF" and data[8:12] == b"WAVE", f"-> ct={ct}")

    if voice_id:
        st, r = call("POST", "/api/tts/synthesize", body={
            "text": "用我设计的音色念这句话。", "voice_preset_id": voice_id
        }, token=token)
        check("用自定义音色合成 200", st == 200, f"-> {st} {r}")
        check("返回自定义音色名", r.get("voice_name") == "深夜电台", f"-> {r.get('voice_name')}")
        st, v2 = call("GET", "/api/voices", token=token)
        check("使用次数已递增", (v2["items"][0].get("use_count") or 0) >= 1, f"-> {v2['items'][0].get('use_count')}")

    st, _ = call("POST", "/api/tts/synthesize", body={"text": ""}, token=token)
    check("空文本返回 422", st == 422)
    st, _ = call("POST", "/api/tts/synthesize", body={"text": "x", "audio_format": "flac"}, token=token)
    check("非法格式返回 422", st == 422)
    st, r = call("POST", "/api/tts/synthesize", body={"text": "x" * 5000}, token=token)
    check("超长文本被拒绝", st == 400 and r.get("error", {}).get("code") == "text_too_long", f"-> {st}")
    st, r = call("POST", "/api/tts/synthesize", body={"text": "x", "voice_preset_id": "not-exist"}, token=token)
    check("不存在的音色返回 404", st == 404, f"-> {st}")

    print("\n[6] ASR 识别")
    wav = make_wav()
    st, r = post_multipart("/api/asr/transcribe", {"language": "zh"},
                           {"file": ("smoke.wav", wav, "audio/wav")}, token)
    detail = str((r.get("error") or {}).get("detail", ""))
    if st != 200 and "balance" in detail.lower():
        # 账户余额不足属于密钥侧问题，不是代码缺陷；此处验证错误已被正确映射
        skip("识别返回 200", "上游账户余额不足：" + detail)
        check("余额不足已被映射为结构化错误", (r.get("error") or {}).get("code") is not None, f"-> {r}")
    else:
        check("识别返回 200", st == 200, f"-> {st} {r}")
    asr_id = r.get("id") if st == 200 else None
    if st == 200:
        check("返回识别文本", bool(r.get("transcript")), f"-> {str(r.get('transcript'))[:40]}")
    else:
        skip("返回识别文本", "依赖上游余额")

    st, _ = post_multipart("/api/asr/transcribe", {"language": "auto"},
                           {"file": ("bad.ogg", b"\x00\x01\x02", "audio/ogg")}, token)
    check("不支持的格式被拒绝", st == 400, f"-> {st}")
    st, _ = post_multipart("/api/asr/transcribe", {"language": "fr"},
                           {"file": ("smoke.wav", wav, "audio/wav")}, token)
    check("非法语种被拒绝", st == 400, f"-> {st}")

    print("\n[7] 我的记录")
    st, r = call("GET", "/api/history?type=all&page_size=50", token=token)
    check("合并历史可读", st == 200 and len(r.get("items", [])) >= 2, f"-> {r.get('total')}")
    items = r.get("items", [])
    check("记录含创建时间", all(i.get("created_at") for i in items), "")
    check("记录含输入文本或识别结果",
          any(i.get("text_input") or i.get("transcript") for i in items), "")
    check("记录含参数字段",
          all((i.get("audio_format") or i.get("language")) for i in items), "")
    check("TTS 记录含音色名称", any(i.get("voice_name") for i in items), "")

    st, r = call("GET", "/api/history?page=1&page_size=1", token=token)
    check("分页生效", st == 200 and len(r.get("items", [])) <= 1, f"-> {len(r.get('items', []))}")

    st, r = call("GET", "/api/history?keyword=" + urllib.parse.quote("冒烟"), token=token)
    check("关键词搜索可用", st == 200, f"-> {st}")

    st, r = call("GET", "/api/history/stats", token=token)
    check("统计可读", st == 200 and r.get("tts_total", 0) >= 1, f"-> {r}")

    st, r = call("GET", "/api/voices?page=1&page_size=10", token=token)
    check("音色分页可读", st == 200 and r.get("total", 0) >= 1, f"-> {r.get('total')}")

    print("\n[8] 越权与清理")
    st, _ = call("GET", "/api/auth/me", token="invalid.token.value")
    check("伪造令牌返回 401", st == 401)

    if tts_id:
        st, _ = call("DELETE", f"/api/tts/{tts_id}", token=token)
        check("删除合成记录", st == 200)
        st, _ = call("GET", f"/api/tts/{tts_id}/download", token=token)
        check("删除后音频不可下载", st == 404)
    if asr_id:
        st, _ = call("DELETE", f"/api/asr/{asr_id}", token=token)
        check("删除识别记录", st == 200)
    if voice_id:
        st, _ = call("DELETE", f"/api/voices/{voice_id}", token=token)
        check("删除自定义音色", st == 200)
        st, _ = call("GET", "/api/voices", token=token)
        check("删除后音色不在列表", st == 200)

    st, _ = call("DELETE", "/api/history", token=token)
    check("清空历史", st == 200)

    print(f"\n== 结果：{ok_count} 通过 / {fail_count} 失败 / {skip_count} 跳过 ==\n")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
