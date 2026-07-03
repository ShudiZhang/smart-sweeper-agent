FROM python:3.11-slim

WORKDIR /app

# ---- 依赖层（利用 Docker 缓存） ----
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# 只复制包声明文件
COPY pyproject.toml .
# 创建占位包目录 + __init__.py，让 pip install . 能识别
RUN mkdir -p utils model rag agent agent/tools \
    && touch utils/__init__.py model/__init__.py rag/__init__.py \
    agent/__init__.py agent/tools/__init__.py

# 安装依赖（源码变更不影响此层缓存）
RUN pip install --no-cache-dir . && pip cache purge

# 清理编译工具
RUN apt-get remove -y gcc g++ && apt-get autoremove -y

# ---- 源码层 ----
COPY . .

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
