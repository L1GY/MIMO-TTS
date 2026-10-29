# VoiceLab 语音工具箱

在线 **语音转文字（ASR）+ 文字转语音（TTS）** 一体化工具站。
单页纵向布局，所有核心功能在首页完成；后端 Python + FastAPI，数据落 SQLite，含账号体系与历史存储。

- **TTS 文字转语音**：音色、语速、音调、采样率可调，生成后可试听、下载、留档
- **ASR 语音转文字**：麦克风录音或上传音频，自动标点、可选分段，支持导出
- **历史记录**：合成与识别任务全部留档，可回放、导出、删除、分页加载
- **明暗主题**：默认浅色（#F8FAFC 底 / 白卡片 / #333 正文），一键切换深色并记忆选择
- 登录：账号密码注册登录（PBKDF2 + JWT），未登录时以页内遮罩引导，不跳页面

界面主色 `#165DFF` 深蓝，辅助色 `#00B4D8` 淡青（用于波形与选中态）。

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

打开 <http://127.0.0.1:8000> 即可使用。接口文档：<http://127.0.0.1:8000/docs>

## 2. 密钥与配置

**密钥只写在 `.env`，由服务端读取，前端代码中不存在任何密钥。**

```env
SPEECH_API_KEY=sk-你的密钥
SPEECH_API_BASE_URL=https://api.xiaomimimo.com/v1
MOCK_MODE=false
```

`.env` 已在 `.gitignore` 中；生产环境建议改用系统环境变量注入。

上游协议要求的模型 ID、预置音色 ID 同样外置在 `.env`
（`TTS_MODEL` / `TTS_MODEL_DESIGN` / `TTS_MODEL_CLONE` / `ASR_MODEL` / `TTS_DEFAULT_VOICE` / `TTS_PRESET_VOICES`），
前端所需模型由 `/api/tts/options` 动态下发，源码中不出现上游品牌字面量。

> ⚠️ 若密钥曾在聊天、截图或日志中暴露，请立即到控制台轮换并替换 `.env` 中的值。

## 3. 页面结构（单页，从上到下）

| 区块 | 内容 |
| --- | --- |
| 顶栏 | Logo + 名称 + 副标题；导航 首页 / API 文档 / 关于；右侧 主题切换 + 登录或账号 |
| 首屏 | 大标题、副标题、说明，下方两张模式卡（TTS / ASR），点选切换工作面板 |
| 工作台 | 左栏输入区（随模式切换）｜右栏结果预览（只读文本 + 波形 + 播放器 + 下载/复制） |
| 功能特性 | 三列卡片：TTS 文字合成 / ASR 语音识别 / 历史与导出 |
| API 文档 | 主要接口一览 |
| 历史记录 | 全部 / 合成 / 识别 分栏，播放、下载、载入文本、删除、加载更多 |
| 页脚 | 版权 / 技术说明 / 隐私与条款 |

## 4. 关于语速 / 音调 / 采样率

**上游接口并不开放这三个参数**，因此它们在服务端通过后处理实现（`app/services/audio_dsp.py`）：

1. 变调：按 `k = 2^(半音/12)` 重采样
2. 变速：OLA（Overlap-Add）时间拉伸，因子 `k / speed`，保证只改时长不改音高
3. 采样率：线性插值重采样，时长与音高均不变

全部为纯 Python 实现，不引入第三方依赖；任一步异常都会**静默回退到原始音频**，
绝不影响合成主流程。默认参数（1.0 / 0 / 跟随上游）不触发任何处理，避免无谓的音质损失。

ASR 侧同理：`punctuate` 关闭时由服务端去掉标点，`segment` 开启时按句切分成段落返回。

## 5. 目录结构

```
Mimo_TTS/
├── .env / .env.example
├── requirements.txt
├── run.py
├── README.md
├── app/
│   ├── main.py / config.py / db.py / models.py / schemas.py
│   ├── security.py / deps.py / errors.py
│   ├── routers/  auth · tts · asr · voices · history · meta
│   └── services/ speech_client · tts_service · asr_service
│                 storage · audio_dsp
├── static/
│   ├── index.html          # 单页（含登录/注册遮罩）
│   ├── oauth_callback.html
│   ├── favicon.svg
│   ├── css/style.css       # 浅色默认 + data-theme="dark" 深色
│   └── js/  wave.js · player.js · api.js · theme.js · workbench.js · main.js
└── data/                   # 运行时生成（已 gitignore）
```

## 6. 数据库

SQLite，首次启动自动建库建表；已存在的旧库会自动补齐新增字段（`ensure_columns`），无需手工迁移。

- **users**：身份信息、PBKDF2 密码哈希、微信 openid
- **voice_presets**：用户设计的音色（名称、描述、样本文本、标识色、使用次数）
- **tts_history**：合成参数（model、voice、voice_name、voice_desc、voice_preset_id、format、optimize）
  与结果（status、text_final、audio_path、audio_size、error_message）、计量（tokens、latency、request_id）
- **asr_history**：识别参数（language、filename、size）与结果（transcript、audio_seconds）、计量

换 PostgreSQL / MySQL 只改 `DATABASE_URL` 并安装驱动即可。

## 7. 接口一览

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

## 8. 异常处理

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

## 9. 模拟模式

未配置密钥或 `MOCK_MODE=true` 时不请求上游：TTS 返回本地生成的 WAV 提示音，ASR 返回占位文本。
整条链路（注册、上传、落盘、下载、记录、鉴权）无需密钥即可验证，页面顶部有模拟模式提示条。

## 10. 常见问题

**端口占用？** `python run.py --port 9000`

**上传失败？** 仅支持 wav / mp3；其他格式先转码 `ffmpeg -i input.m4a -ar 16000 output.wav`

**识别空结果？** 可能是无声或纯音乐片段，换一段有效人声再试

**pcm16 播放异常？** 上游未公开采样率，服务端按 24kHz 单声道补 WAV 头；有差异时改用 wav / mp3

**磁盘清理？** 「我的记录 → 清空生成记录」会同时删除音频文件
