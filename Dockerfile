FROM python:3.12-alpine
RUN apk add --no-cache tzdata
COPY app.py /app/app.py
USER nobody
EXPOSE 8080
CMD ["python3", "-I", "/app/app.py"]
