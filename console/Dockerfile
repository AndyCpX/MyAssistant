FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
RUN mkdir -p /data
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8090/healthz')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
