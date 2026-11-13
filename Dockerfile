FROM python:3.13-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir pillow==13.0.0
WORKDIR /app
COPY dashboard/dash.py rezepte/rezepte.py rezepte/vorrat.py rezepte/prompt.txt rezepte/stil.css rezepte/katalog-start.txt ./
CMD ["python", "-u", "dash.py"]
