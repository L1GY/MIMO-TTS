FROM python:3.11-slim
WORKDIR /app

# 预先创建data目录，sqlite存放数据库、音频
RUN mkdir -p /app/data/audio /app/data/uploads

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
EXPOSE 8080

# 你的run.py启动
CMD ["python","run.py"]
