FROM python:3.10 as requirements-stage
WORKDIR /tmp
RUN pip install --no-cache-dir poetry==1.8.2
COPY ./pyproject.toml ./poetry.lock /tmp/
RUN poetry export -f requirements.txt --output requirements.txt

FROM python:3.10
WORKDIR /code

RUN apt-get update \
    && apt-get install -y tzdata \
    && ln -snf /usr/share/zoneinfo/Asia/Seoul /etc/localtime \
    && echo "Asia/Seoul" > /etc/timezone \
    && apt-get clean

COPY --from=requirements-stage /tmp/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt \
    && rm -f requirements.txt

COPY ./app /code/app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Seoul

ENTRYPOINT [ "uvicorn", "app.app:app" ]
