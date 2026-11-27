FROM clamav/clamav:1.5.5@sha256:12177441d1b40cef3c47b44c4090d59d4babc4c67bedd5af0fa315e603aa6dd8
RUN apk add --no-cache python3
COPY docker/clamav/gateway.py /gateway.py
COPY docker/clamav/clamd.conf /etc/clamav/clamd.conf
COPY docker/clamav/freshclam.conf /etc/clamav/freshclam.conf
COPY docker/clamav/healthcheck.sh /healthcheck.sh
ENTRYPOINT ["/sbin/tini", "--", "python3", "/gateway.py"]
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s CMD sh /healthcheck.sh
