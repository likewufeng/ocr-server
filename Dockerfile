FROM python:3.10-bookworm

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

RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
  -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
