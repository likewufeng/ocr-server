FROM python:3.10-bookworm

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN sed -i 's@deb.debian.org@mirrors.tuna.tsinghua.edu.cn@g' /etc/apt/sources.list.d/debian.sources \
  && sed -i 's@security.debian.org@mirrors.tuna.tsinghua.edu.cn@g' /etc/apt/sources.list.d/debian.sources \
  && apt-get update \
  && apt-get install -y \
  libglib2.0-0 \
  libgl1 \
  wget \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
  -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]