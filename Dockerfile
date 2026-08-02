FROM python:3.10-bookworm

ARG INSTALL_OPENVINO=false
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN sed -i 's@http://deb.debian.org@https://deb.debian.org@g' /etc/apt/sources.list.d/debian.sources \
  && apt-get -o Acquire::Retries=5 update \
  && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
  libglib2.0-0 \
  libgl1 \
  wget \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --index-url "$PIP_INDEX_URL" \
  -r requirements.txt

# 实验镜像才安装 PaddleX HPIP/OpenVINO 和模型转换插件，生产镜像默认跳过。
RUN if [ "$INSTALL_OPENVINO" = "true" ]; then \
      paddlex --install hpi-cpu && \
      paddlex --install paddle2onnx; \
    fi

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
