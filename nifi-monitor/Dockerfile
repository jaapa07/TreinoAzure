FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

ENV NIFI_BASE_URL=https://nifi-tierc.lincros.com/nifi \
    NIFI_USERNAME="" \
    NIFI_PASSWORD="" \
    NIFI_VERIFY_SSL=false \
    POLL_INTERVAL=30 \
    MAX_HISTORY=500

CMD ["python", "app.py"]
