FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core tzdata \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /app
COPY dashboard/dash.py rezepte/rezepte.py rezepte/vorrat.py rezepte/prompt.txt rezepte/stil.css rezepte/katalog-start.txt ./
CMD ["python", "-u", "dash.py"]
