FROM python:3.12-alpine

WORKDIR /app
COPY delete_worker.py .

CMD ["python", "delete_worker.py"]
