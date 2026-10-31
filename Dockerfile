# MiMo 声音工坊 —— 生产镜像
#
# 构建（在仓库根执行，CloudBase / CI 的默认上下文就是仓库根）：
#   docker build -t mimo-studio .
#
# 运行：
#   docker run -d --name mimo-studio -p 8080:8080 \
#     --env-file mimo_studio/.env \
#     -v mimo-data:/data \
#     -v mimo-audio:/app/static/audio \
#     mimo-studio
#
# ⚠️ 业务代码在 mimo_studio/ 子目录，所以下面 COPY 都带这个前缀。
#    如果以后把项目整体移到仓库根，要同步去掉前缀。
#
# 数据持久化：数据库写 /data，音色样本与合成音频写 /app/static/audio
# （这个路径由代码里的 STATIC_DIR 决定，不能随意改，否则静态文件会 404）。
# 注意：云托管若不给持久化卷，容器每次重建数据都会丢，见文末说明。
FROM python:3.13-slim

# PYTHONUNBUFFERED  日志不缓冲，平台日志才能实时看到
# PYTHONDONTWRITEBYTECODE  不在镜像层里留 .pyc，也避免非 root 用户写目录失败
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

# 程序用 datetime.now() 直接存本地时间（见 models/base.py），
# 容器默认 UTC 会让所有记录时间偏 8 小时，所以装上时区数据并设为东八区。
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖单独一层：requirements.txt 不变时，改业务代码不会触发重装
COPY mimo_studio/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 只复制业务代码，不把仓库根的其他东西（README、.git）塞进镜像
COPY mimo_studio/ ./

# 服务监听 0.0.0.0（默认的 127.0.0.1 在容器里外部访问不到）；
# 数据库放到 /data，避免落在镜像可写层。
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

EXPOSE 8080

# 用标准库探活，镜像里不用额外装 curl。
# 端口读 $PORT，平台注入不同端口时也能对上。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,sys,urllib.request;p=os.environ.get('PORT','8080');sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+p+'/healthz',timeout=3).status==200 else 1)"

# 必须是单 worker：任务队列是进程内 ThreadPoolExecutor + 数据库状态轮询，
# 多 worker 会让同一个任务被多个进程同时领走、重复扣额度。
# 要横向扩容得先把任务调度换成外部队列（本项目刻意不引入 Redis/Celery）。
#
# 用 sh -c 读 $PORT：云平台常通过环境变量指定端口，写死会绑错端口导致健康检查失败。
# exec 保证 uvicorn 接管 PID 1，docker stop 的 SIGTERM 能正常传到（否则要等 10s 才被杀）。
#
# 如果前面挂 nginx / 网关，需要拿到真实客户端 IP，加 --proxy-headers
# 并配合 --forwarded-allow-ips 限定可信代理，不要直接放开成 *。
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
