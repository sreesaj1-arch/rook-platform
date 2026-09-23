FROM python:3.13.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workload
COPY server.py ./server.py
USER 10001:10001
EXPOSE 8080
CMD ["python", "server.py"]
