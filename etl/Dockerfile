FROM apache/airflow:2.9.0-python3.10
USER root
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
  && apt-get autoremove -yqq --purge \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/airflow/data \
  && chown -R airflow:0 /opt/airflow/data \
  && chmod -R 775 /opt/airflow/data

USER airflow
