# AutoInsight 语义分析服务
# 构建：docker build -t autoinsight-service .
# 运行：docker run --env-file .env -p 8000:8000 -v ./data:/app/data -v ./reports:/app/reports autoinsight-service
FROM python:3.13-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 整体复制 + .dockerignore（auto-042 6.1）：逐文件枚举已两次与代码结构脱节
# （引用已删除的 db_mirror.py / intent.py，同时漏掉 kernel、semantic、research、
# routing、integrations 五个包）。镜像内容应等于仓库内容减去忽略项。
COPY . .

# 服务与分析子进程使用无特权用户。部署时由容器运行时再叠加只读根目录、
# capability drop、no-new-privileges 和资源上限。
RUN addgroup --system --gid 10001 autoinsight \
    && adduser --system --uid 10001 --ingroup autoinsight autoinsight \
    && mkdir -p /app/reports /tmp \
    && chown -R autoinsight:autoinsight /app/reports /tmp
USER 10001:10001

# 沙箱在容器内回退为容器自身的 python -I 子进程（VENV_PYTHON 不存在时自动回退）
EXPOSE 8000
CMD ["python", "app.py"]
