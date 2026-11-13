FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core tzdata \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /app
COPY dashboard/dash.py rezepte/rezepte.py rezepte/vorrat.py rezepte/prompt.txt rezepte/stil.css rezepte/katalog-start.txt ./
CMD ["python", "-u", "dash.py"]
