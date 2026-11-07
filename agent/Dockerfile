FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/models/hf
RUN mkdir -p /models
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN mkdir -p /data /models/fastembed && FASTEMBED_CACHE_PATH=/models/fastembed python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', cache_dir='/models/fastembed')"
RUN mkdir -p /data && python -c "import urllib.request as u; u.urlretrieve('https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx', '/models/speaker.onnx')"
COPY app ./app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=120s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
