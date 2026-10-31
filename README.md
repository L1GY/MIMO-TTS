# MiMo 声音工坊

文字转语音（TTS）+ 声音克隆工具站，基于小米 MiMo 官方 API。

**项目主体在 [`mimo_studio/`](mimo_studio/) 目录。** 早期基于前后端分离方案的原型（FastAPI + 原生 JS + SQLite）
已整体移除，现在的实现是 FastAPI 服务端渲染（SSR）+ Jinja2 模板。

## 快速启动

```bash
cd mimo_studio
pip install -r requirements.txt
python main.py           # http://127.0.0.1:8100
```

首次运行自动建库建表、生成默认管理员 `admin` / `admin123`、写入 9 个预置音色。

## 配置 API Key

三选一，优先级从高到低：

1. 管理后台 → 系统配置（写入数据库，立即生效）
2. 复制 `.env.example` 为 `.env`，填写 `MIMO_API_KEY=sk-xxxx`
3. 设置环境变量 `MIMO_API_KEY`

> 密钥只在服务端使用，不会出现在任何前端代码中。

完整说明见 [`mimo_studio/README.md`](mimo_studio/README.md)。
