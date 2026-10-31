# MiMo 声音工坊 · 文字转语音 + 声音克隆

基于 **小米 MiMo 官方 API** 的全栈 Web 应用：FastAPI + Jinja2 服务端渲染 + SQLite + 原生 HTML/CSS/JS（Tailwind CSS v3 + Font Awesome）。
登录注册、多音色合成、参考音频克隆、异步任务、合成记录、管理员后台全部可用，**不需要任何模型代码，只做业务层与 API 中转**。

---

## 一、快速启动

```bash
cd mimo_studio

# 1) 安装依赖（Python 3.10+）
python -m venv .venv
.venv\Scripts\activate            # macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt

# 2) 配置 API Key（三选一，详见下一节）
copy .env.example .env            # Windows；macOS/Linux 用 cp
# 编辑 .env，填入 MIMO_API_KEY=sk-xxxx

# 3) 启动
python main.py
```

打开 <http://127.0.0.1:8100>

**默认管理员账号：`admin` / `admin123`**（首次启动自动创建，请登录后立即在「个人中心」改密码）

首次启动会自动完成：建库建表（`mimo.db`）、创建默认管理员、写入 9 个官方预置音色、创建 `static/audio/{samples,outputs}` 目录。

---

## 二、API Key 配置位置（三种方式，后者优先）

| 方式 | 位置 | 说明 |
| --- | --- | --- |
| 1. 环境变量 | `MIMO_API_KEY=sk-xxxx` | 优先级最低，适合容器部署 |
| 2. `.env` 文件 | 项目根目录 `.env` → `MIMO_API_KEY=` | 复制 `.env.example` 后填写 |
| 3. 后台页面 | 登录管理员 → **管理后台 → 系统配置 → API Key** | **优先级最高**，写入数据库，改完立即生效不用重启 |

`.env` 已被 `.gitignore` 忽略；密钥只在服务端使用，任何页面源码、接口响应、日志里都不会出现完整密钥（后台只展示 `sk-ca6hfm********hply` 这样的掩码）。

---

## 三、MiMo API 对接（已按真实接口校准）

```
POST https://api.xiaomimimo.com/v1/chat/completions
Headers: api-key: <你的 Key>   Content-Type: application/json
```

```jsonc
{
  "model": "mimo-v2.5-tts",                     // 或 mimo-v2.5-tts-voiceclone
  "messages": [{ "role": "assistant", "content": "要合成的文本" }],
  "audio": {
    "format": "mp3",
    "voice": "冰糖",                             // 预置音色传音色标识
    "speed": 1.0
  }
}
```

响应音频在 `choices[0].message.audio.data`（base64），解码后落盘为 mp3。

### ⚠️ 三处必须知道的实测差异（本项目的实现依据）

需求文档给出的请求示例中 `role` 是 `user`，但**真实接口会直接 400 拒绝**：

```
{"param": "messages must contain an assistant role for TTS model"}
```

用真实 Key 实测后确认的三条规则，代码中已按此实现：

| 项 | 实测结论 | 代码位置 |
| --- | --- | --- |
| 消息角色 | **必须 `role: assistant`**，传 `user` 直接 400 | `services/mimo_api.py` → `ROLE_ASSISTANT` |
| 克隆音色 `voice` | **必须是 DataURL**：`data:audio/wav;base64,xxx`；传裸 base64 会 400 | `synthesis_clone_tts()` |
| 预置音色 `voice` | 传官方音色标识（`冰糖` / `Mia` / `mimo_default` 等） | `synthesis_tts()` |

> 正是因为「克隆不需要预先创建音色 ID」，本项目把「我的音色」实现为**保存用户上传的参考音频文件**，
> 每次合成时把该文件转成 DataURL 传给接口即可，没有任何额外的建音色调用。

---

## 四、功能清单

### 用户与权限
- 注册 / 登录 / 退出，密码 **bcrypt** 哈希（cost 12）
- 会话用 `itsdangerous` 签名的 Cookie（HttpOnly + SameSite=Lax），不依赖任何外部存储
- 角色：普通用户 / 管理员；所有页面与接口都做登录校验，私有数据按 `user_id` 隔离
- 个人中心：资料、额度、任务与音色统计、修改密码

### 音色（声音克隆）
- 拖拽或点击上传 wav / mp3，**前端 + 后端双重校验**：格式、≤10MB、时长 3-10 秒
- 时长由服务端解析音频帧计算（wav 读头、mp3 逐帧解析），不依赖 ffmpeg
- 必须勾选声音授权协议，授权时间与原文永久入库留痕
- 列表支持在线试听、重命名、删除（同步删除本地样本文件）
- 数据隔离：只能看到和操作自己的音色

### 语音合成
- 多行文本 + 实时字数统计（上限可在后台配置，默认 3000 字）
- 音色 Tab 切换：公共音色（9 个官方预置）/ 我的音色
- 语速 0.5-2.0（默认 1.0）
- 提交前校验剩余额度，不足直接拦截
- **异步任务**：`ThreadPoolExecutor` + 数据库状态，页面每 3 秒轮询，不阻塞请求
- **长文本自动分段**：按段落 → 句末标点 → 硬切的顺序切成约 280 字的片段，逐段调用后拼接
- **拼接方式**：去掉每段 mp3 的 ID3 标签后按帧顺序拼接，接缝处既无静音也无爆音（可用播放器拖到接缝处验证）
- 文本预处理：清洗多余空行/空格 + 敏感词遮蔽（命中词入库日志，管理员可查）
- 合成记录：文本摘要、音色、时长、体积、分段数、耗时、状态；支持播放、下载、复用文本、删除

### 管理员后台（`/admin`，仅管理员）
- **概览**：用户/任务/音色/成功率指标卡、近 7 天任务量柱状图、最近任务
- **用户管理**：搜索、启用/禁用、逐个调整额度（可同时重置已用量）
- **合成任务**：按状态筛选，查看失败原因
- **音色管理**：查看全平台克隆音色、试听、强制删除（可填原因）
- **系统配置**：API Key、默认赠送额度、单条文本上限、敏感词、站点公告
- **操作日志**：注册/登录/提交/删除/改名/后台操作全部留痕（含 IP）

---

## 五、项目结构

```
mimo_studio/
├── main.py                  # 入口：应用装配、全局异常、启动流程
├── config.py                # 全局配置（API Key、额度、限额、公共音色…）
├── database.py              # SQLite 连接、ORM 初始化、建表
├── requirements.txt
├── .env.example             # 配置模板
├── models/                  # SQLAlchemy 模型
│   ├── user.py              # 用户（bcrypt 密码、角色、额度）
│   ├── voice.py             # 音色（preset / clone）
│   ├── task.py              # 合成任务（状态机、进度、结果）
│   ├── oplog.py             # 操作日志
│   └── setting.py           # 系统配置键值
├── schemas/                 # Pydantic 校验（注册、改密、音色、合成）
├── services/
│   ├── mimo_api.py          # ★ MiMo API 统一封装（重试、错误映射）
│   ├── audio_service.py     # 音频时长解析、拼接、落盘与清理
│   ├── task_service.py      # 线程池 + 任务状态推进
│   ├── security.py          # bcrypt 哈希、签名会话
│   ├── settings_service.py  # 数据库配置覆盖默认值
│   ├── text_utils.py        # 清洗、敏感词、分段
│   └── bootstrap.py         # 首次启动种子数据
├── routers/
│   ├── deps.py              # 模板渲染、登录/权限依赖、日志
│   ├── auth.py              # 登录、注册、退出
│   ├── tts.py               # 合成页、提交、状态轮询、记录
│   ├── voice.py             # 我的音色增删改查
│   ├── user.py              # 个人中心、改密
│   └── admin.py             # 管理后台全部页面
├── templates/               # Jinja2 模板（SSR）
│   ├── base.html / base_auth.html
│   ├── login.html / register.html
│   ├── index.html           # 语音合成
│   ├── voices.html / records.html / profile.html
│   ├── error.html
│   └── admin/               # 概览 / 用户 / 任务 / 音色 / 配置 / 日志
└── static/
    ├── css/app.css          # 播放器、选中态等补充样式
    ├── js/app.js            # Toast、主题、菜单、防重复提交
    ├── js/player.js         # 自绘播放器（进度、音量）
    ├── js/tts.js            # 字数、音色切换、任务轮询
    ├── js/voice.js          # 拖拽上传与前端校验
    ├── js/records.js        # 记录页进度轮询
    └── audio/
        ├── samples/         # 用户上传的参考音频
        └── outputs/         # 合成结果 mp3
```

---

## 六、如何添加更多公共音色

编辑 `config.py` 的 `PUBLIC_VOICES`，追加一条即可（`voice_key` 必须是 MiMo 官方音色标识，`name`/`desc` 随便写）：

```python
PUBLIC_VOICES: list[dict] = [
    {"voice_key": "mimo_default", "name": "默认音色", "desc": "自然均衡，通用播报"},
    {"voice_key": "冰糖", "name": "冰糖", "desc": "清亮甜美，少女感"},
    # 新增一行：
    {"voice_key": "你的官方音色标识", "name": "展示名", "desc": "一句话描述"},
]
```

重启服务后自动同步进数据库：已存在的只更新名称与描述，不会重复插入。

---

## 七、异常处理与稳定性

- **API 层重试**：网络异常 / 超时 / 5xx / 429 自动重试 3 次（指数退避）；4xx 参数类错误不浪费重试，直接抛出
- **错误翻译**：密钥无效、额度不足、参数错误、音频过大、上游 5xx、超时，都转换成中文提示展示给用户
- **额度保护**：提交时预扣，任务失败自动退回，不会出现「失败也扣额度」
- **幂等与并发**：任务状态机保证不会重复执行；表单提交按钮点击后立即禁用，防重复提交
- **音频安全**：删除文件前会校验路径必须位于 `static/` 内，避免越权删除
- **XSS**：Jinja2 默认转义；前端注入文本统一用 `textContent`
- **越权**：所有查询带 `user_id` 条件；任务/音频下载都校验归属（管理员除外）

---

## 八、常见问题

**Q：合成一直失败，提示「MiMo 账户额度不足」？**
去 MiMo 控制台确认账户余额；TTS 与克隆模型可能分别计费。

**Q：上传音色提示「无法解析该 mp3 文件的时长」？**
个别编码器产出的 mp3 帧头不规范。用任意工具转成 wav 再上传即可，wav 是直接读文件头，最稳。

**Q：重启后登录态失效？**
没设置 `SECRET_KEY` 时每次启动都会随机生成。把 `.env` 里的 `SECRET_KEY` 填一个固定值即可。

**Q：能部署到服务器吗？**
可以，`uvicorn main:app --host 0.0.0.0 --port 8100`。生产环境请改 `SECRET_KEY`、`ADMIN_PASSWORD`，
并在 https 下把 `COOKIE_SECURE=1`。SQLite 单机足够；若要换库，改 `DATABASE_URL` 并装对应驱动即可。

**Q：长文本上限/分段长度怎么调？**
后台「系统配置」改单条文本上限；分段长度在 `config.py` 的 `CHUNK_MAX_CHARS`（默认 280）。
