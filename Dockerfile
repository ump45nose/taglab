FROM python:3.12-alpine

WORKDIR /app
COPY delete_worker.py .
RUN chmod 0555 /app/delete_worker.py

CMD ["python", "delete_worker.py"]
