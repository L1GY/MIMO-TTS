# MiMo 声音工坊 —— 生产镜像
#
# 构建：
#   docker build -t mimo-studio .
#
# 运行（推荐用 docker-compose，见 docker-compose.yml）：
#   docker run -d --name mimo-studio -p 8100:8100 \
#     --env-file .env \
#     -v mimo-data:/data \
#     -v mimo-audio:/app/static/audio \
#     mimo-studio
#
# 数据持久化说明：数据库写 /data，用户上传的音色样本与合成音频写
# /app/static/audio（这个路径由代码里的 STATIC_DIR 决定，不能随意改，
# 否则静态文件服务会 404）。两个目录都必须挂卷，否则容器重建即丢。
FROM python:3.13-slim

# PYTHONUNBUFFERED  日志不缓冲，docker logs 才能实时看到
# PYTHONDONTWRITEBYTECODE  不在镜像层里留 .pyc
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

# 程序用 datetime.now() 直接存本地时间（见 models/base.py），
# 容器默认 UTC 会让记录时间偏 8 小时，所以装上时区数据并设为东八区。
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖单独一层：requirements.txt 不变时，改业务代码不会触发重装
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 服务监听 0.0.0.0（默认的 127.0.0.1 在容器里外部访问不到）；
# 数据库放到 /data，避免落在镜像可写层。
#
# 注意：容器内端口固定 8100（EXPOSE 和 CMD 都是）。PORT 只影响启动日志里
# 打印的地址，要换对外端口请改 -p 映射，例如 -p 9000:8100。
# 同理用 --env-file .env 时，.env 里的 HOST=127.0.0.1 会覆盖这里的值，
# 只会让日志显示得不对（实际绑定仍由 CMD 决定），想显示正确就加 -e HOST=0.0.0.0。
ENV HOST=0.0.0.0 \
    PORT=8080 \
    DB_PATH=/data/mimo.db

# 非 root 运行。只把「需要写」的两个目录给 appuser，
# 代码目录保持 root 只读——容器被攻破也改不动业务代码。
# 若不 chown，音色上传与合成落盘会报 Permission denied。
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /data /app/static/audio/samples /app/static/audio/outputs \
 && chown -R appuser:appuser /data /app/static/audio

USER appuser

VOLUME ["/data", "/app/static/audio"]

EXPOSE 8100

# 用标准库探活，镜像里不用额外装 curl
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/healthz',timeout=3).status==200 else 1)"

# 必须是单 worker：任务队列是进程内 ThreadPoolExecutor + 数据库状态轮询，
# 多 worker 会让同一个任务被多个进程同时领走、重复扣额度。
# 要横向扩容得先把任务调度换成外部队列（本项目刻意不引入 Redis/Celery）。
#
# 如果前面挂 nginx / 网关，需要拿到真实客户端 IP，可改用：
#   CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8100","--proxy-headers"]
# 并配合 --forwarded-allow-ips 限定可信代理，不要直接放开成 *。
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
