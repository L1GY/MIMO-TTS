# 声坊 Voice Atelier

文本转语音、音色设计与语音识别工作台。
后端 Python + FastAPI，前端原生 HTML/CSS/JS，数据落 SQLite，含完整的注册登录与鉴权。

- **文本转语音**：预置音色或自定义音色，生成后可试听、下载、删除
- **音色设计**：用一句话描述声音，试听满意后保存成自己的音色，随时复用
- **音频转文字**：上传 wav / mp3，返回带标点的文本，源音频归档
- **我的记录**：生成记录与已设计音色分栏管理，支持试听、导出、删除与分页加载
- **鉴权**：用户名密码注册登录（PBKDF2 + JWT），未登录无法调用任何业务接口
- 微信扫码登录：可选，未配置时自动关闭，不影响账号密码登录

---

## 1. 启动

```bash
cd Mimo_TTS
python -m venv .venv
.venv\Scripts\activate          # macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # 已存在可跳过
python run.py                   # http://127.0.0.1:8000
```

打开 <http://127.0.0.1:8000> 注册账号后即可使用。接口文档：<http://127.0.0.1:8000/docs>

自检：`python smoke_test.py`（需先启动服务）。

## 2. 密钥与配置

**密钥只写在 `.env`，由服务端读取，前端代码中不存在任何密钥。**

```env
SPEECH_API_KEY=sk-你的密钥
SPEECH_API_BASE_URL=https://api.xiaomimimo.com/v1
MOCK_MODE=false
```

调用链：浏览器 → 本后端（读取 `.env` 中的密钥）→ 上游语音服务。
浏览器永远不接触密钥：`/api/meta`、`/api/tts/options` 等接口只下发能力与开关，
任何响应都不含密钥字段（冒烟测试中有断言覆盖）。

`.env` 已在 `.gitignore` 中；生产环境建议改用系统环境变量注入。

上游协议要求的模型 ID、预置音色 ID 同样外置在 `.env`
（`TTS_MODEL` / `TTS_MODEL_DESIGN` / `TTS_MODEL_CLONE` / `ASR_MODEL` / `TTS_DEFAULT_VOICE` / `TTS_PRESET_VOICES`），
**源码与前端中不含任何上游品牌字面量**，前端所需模型由 `/api/tts/options` 动态下发。

> ⚠️ 若密钥曾在聊天、截图或日志中暴露，请立即到控制台轮换并替换 `.env` 中的值。

## 3. 目录结构

```
Mimo_TTS/
├── .env / .env.example          # 配置与密钥（.env 不入库）
├── requirements.txt
├── run.py                       # 启动入口
├── smoke_test.py                # 端到端自检
├── README.md
│
├── app/
│   ├── main.py                  # 应用装配、静态站点、全局异常处理
│   ├── config.py                # 配置中心 + 音色/格式常量
│   ├── db.py                    # 引擎、会话、缺列自动补齐
│   ├── models.py                # User / VoicePreset / TTSRecord / ASRRecord
│   ├── schemas.py               # 请求响应模型
│   ├── security.py              # PBKDF2 密码哈希 + JWT
│   ├── deps.py                  # 鉴权依赖
│   ├── errors.py                # 统一异常与错误响应
│   ├── routers/
│   │   ├── auth.py              # 注册 / 登录 / 微信扫码登录
│   │   ├── tts.py               # 合成 / 历史 / 下载 / 删除
│   │   ├── asr.py               # 上传识别 / 历史 / 源音频下载
│   │   ├── voices.py            # 自定义音色增删改查
│   │   ├── history.py           # 合并历史、统计、清空
│   │   └── meta.py              # 能力开关与健康检查
│   └── services/
│       ├── speech_client.py     # 上游 HTTP 客户端（超时、重试、错误映射）
│       ├── tts_service.py       # 合成请求组装与响应解析
│       ├── asr_service.py       # 识别请求组装与响应解析
│       └── storage.py           # 音频落盘 / 读取 / 删除
│
├── static/
│   ├── index.html               # 登录 / 注册
│   ├── app.html                 # 工作台（首屏 + 四个视图）
│   ├── oauth_callback.html      # 微信登录回调中转页
│   ├── favicon.svg
│   ├── css/style.css            # 设计系统
│   └── js/
│       ├── api.js               # 接口层（令牌、错误、提示、播放器渲染）
│       ├── wave.js              # 声纹可视化（Web Audio 频谱驱动）
│       ├── auth.js              # 登录注册
│       ├── tts.js               # 文本转语音
│       ├── voicedesign.js       # 音色设计
│       ├── asr.js               # 音频转文字
│       ├── records.js           # 我的记录
│       └── app.js               # 外壳与路由
│
└── data/                        # 运行时生成（已 gitignore）
    ├── app.db
    ├── audio/{user_id}/         # 合成音频
    └── uploads/{user_id}/       # 上传源音频
```

## 4. 界面结构

首屏为深色声纹带，集中呈现三项核心能力，点击进入对应视图：

| 视图 | 说明 |
| --- | --- |
| 文本转语音 | 文本输入 + 音色选择（我的音色 / 预置音色分组）+ 格式，右侧即时试听与最近生成 |
| 音色设计 | 描述音色 → 生成试听 → 命名保存；提供描述灵感标签与「我的音色」卡片墙 |
| 音频转文字 | 拖拽上传 → 语种选择 → 识别结果复制 / 导出 |
| 我的记录 | 「生成记录」与「我的音色」分栏；支持搜索、分页加载更多、试听、导出、删除、清空 |

## 5. 数据库

SQLite，首次启动自动建库建表；已存在的旧库会自动补齐新增字段（`ensure_columns`），无需手工迁移。

- **users**：身份信息、PBKDF2 密码哈希、微信 openid
- **voice_presets**：用户设计的音色（名称、描述、样本文本、标识色、使用次数）
- **tts_history**：合成参数（model、voice、voice_name、voice_desc、voice_preset_id、format、optimize）
  与结果（status、text_final、audio_path、audio_size、error_message）、计量（tokens、latency、request_id）
- **asr_history**：识别参数（language、filename、size）与结果（transcript、audio_seconds）、计量

换 PostgreSQL / MySQL 只改 `DATABASE_URL` 并安装驱动即可。

## 6. 接口一览

除 `/api/meta`、`/api/health` 与鉴权接口外，**全部需要** `Authorization: Bearer <token>`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/register` / `/api/auth/login` | 注册 / 登录 |
| GET | `/api/auth/me` | 当前用户 |
| GET | `/api/auth/wechat/status` \| `/qr` \| `/callback` | 微信登录（未配置 → 404） |
| GET | `/api/tts/options` | 音色（含我的音色来源）、格式、模型、上限 |
| POST | `/api/tts/synthesize` | 合成，支持 `voice` / `voice_desc` / `voice_preset_id` |
| GET | `/api/tts/history` \| `DELETE /api/tts/{id}` | 历史与删除 |
| GET | `/api/tts/{id}/download` | 下载，`?disposition=inline` 可在线播放 |
| GET | `/api/asr/options` \| POST `/api/asr/transcribe` | 识别（multipart） |
| GET | `/api/asr/history` \| `DELETE /api/asr/{id}` | 历史与删除 |
| GET/POST | `/api/voices` | 我的音色列表 / 保存 |
| PATCH/DELETE | `/api/voices/{id}` | 改名改描述 / 删除 |
| GET | `/api/history` \| `/api/history/stats` | 合并历史与统计 |
| DELETE | `/api/history/{tts\|asr}/{id}` \| `/api/history` | 删单条 / 清空 |

> `<audio src>` 无法自定义请求头，音频地址支持 `?token=xxx` 形式鉴权。

## 7. 异常处理

统一结构，前端按 `code` 差异化提示：

```json
{ "error": { "code": "upstream_rate_limited", "message": "上游平台限流（RPM/TPM 超限），请稍后重试", "detail": "..." } }
```

| 环节 | 处理 |
| --- | --- |
| 参数校验 | 422，提取首个字段给出可读提示 |
| 未登录 / 令牌失效 | 401（`unauthorized` / `token_expired` / `invalid_token`），前端跳登录页 |
| 越权访问 | 记录不属于当前用户 → 404，避免资源枚举 |
| 缺密钥 / 配置不全 | 503（`missing_api_key` / `upstream_not_configured`），提示对照 `.env.example` |
| 上游密钥无效 | 401 `upstream_auth_failed` |
| 上游限流 | 429 `upstream_rate_limited` |
| 音频过大 | 413 |
| 上游超时 / 不可达 / 5xx | 504 / 503 / 502 |
| 返回无音频 / 空结果 | 502 `empty_audio` / `empty_transcript` |
| 未捕获异常 | 500 `internal_error`，堆栈只记日志 |

对 `408/409/429/5xx` 与连接、超时错误自动重试（`SPEECH_MAX_RETRIES`，默认 2 次），
退避 `0.8 × 2ⁿ` 秒 + 随机抖动；非幂等的 4xx 不重试。
调用前先落 `status=pending`，成败都写回 `error_message` 与耗时，失败也留痕。

> 账户类问题（如余额不足）会以 `upstream_bad_request` 带上上游原文返回，便于快速定位。

## 8. 模拟模式

未配置密钥或 `MOCK_MODE=true` 时不请求上游：TTS 返回本地生成的 WAV 提示音，ASR 返回占位文本。
整条链路（注册、上传、落盘、下载、记录、鉴权）无需密钥即可验证，页面顶部有模拟模式提示条。

## 9. 常见问题

**端口占用？** `python run.py --port 9000`

**上传失败？** 仅支持 wav / mp3；其他格式先转码 `ffmpeg -i input.m4a -ar 16000 output.wav`

**识别空结果？** 可能是无声或纯音乐片段，换一段有效人声再试

**pcm16 播放异常？** 上游未公开采样率，服务端按 24kHz 单声道补 WAV 头；有差异时改用 wav / mp3

**磁盘清理？** 「我的记录 → 清空生成记录」会同时删除音频文件
