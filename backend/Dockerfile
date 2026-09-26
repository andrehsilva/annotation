FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY manage.py seed.py ./

EXPOSE 8000
# `--forwarded-allow-ips=*` é obrigatório: o uvicorn só confia em X-Forwarded-* de IPs dessa lista, e o
# par dele aqui é o container do nginx (não 127.0.0.1). Sem isso o middleware `refuse_foreign_origin`
# (app/main.py) compara `request.url.scheme` = "http" com o Origin "https://…" e responde 403 em toda
# escrita vinda do SPA.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
