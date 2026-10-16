# Supervisor used to pass BUILD_FROM; it is accepted and ignored so older
# Supervisors can still build this image.
ARG BUILD_FROM
FROM eclipse-temurin:11-jdk-noble

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        socat iproute2 util-linux jq curl ca-certificates python3 procps \
    && rm -rf /var/lib/apt/lists/*

COPY run.sh inner.sh /
RUN chmod +x /run.sh /inner.sh

CMD ["/run.sh"]
