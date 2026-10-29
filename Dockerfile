FROM python:3.11-slim
WORKDIR /app

# 安装依赖
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝全部代码（app、static、run.py等全部）
COPY . .

# CloudBase云托管固定端口：8080
ENV PORT=8080
EXPOSE 8080

# 启动命令，根据你run.py的uvicorn启动方式修改
# 如果 run.py 内部是 uvicorn，直接执行：
CMD ["python","run.py"]
# 👉 如果你的run.py只是定义app，没有启动，则换成：
