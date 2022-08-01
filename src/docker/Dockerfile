FROM python:3.8-alpine AS compile-image

RUN apk add --update --no-cache gcc musl-dev libc-dev libxslt-dev libffi-dev openssl-dev python3-dev rust cargo
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt requirements.txt
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

FROM python:3.8-alpine
COPY --from=compile-image /opt/venv /opt/venv
COPY ./entrypoint.sh /entrypoint.sh

COPY entrypoint.sh /entrypoint.sh
COPY src/python/quarantine.py /opt/turbonomic/actionscripts/quarantine/
COPY src/bash/docker-preentrypoint.sh /opt/turbonomic/actionscripts/quarantine/

RUN apk update && \
    apk --no-cache add bash git openssh augeas shadow jq curl && \
    groupadd -g 1000 turbo && \
    useradd -r -m -p '' -u 1000 -g 1000 -c 'SSHD User' -s /bin/bash turbo && \
    mkdir -p /etc/authorized_keys && \
    mkdir -p /etc/ssh/keys && \
    chmod +x /opt/turbonomic/actionscripts/quarantine/docker-preentrypoint.sh && \
    chmod +x /opt/turbonomic/actionscripts/quarantine/docker-preentrypoint.sh && \
    chown turbo:turbo /opt/turbonomic/actionscripts/quarantine/quarantine.py && \
    chmod +x /opt/turbonomic/actionscripts/quarantine/quarantine.py && \
    augtool 'set /files/etc/ssh/sshd_config/AuthorizedKeysFile "/etc/authorized_keys/%u"' && \
    augtool 'set /files/etc/ssh/sshd_config/HostKey[1] /etc/ssh/keys/hostkey' && \
    echo -e "Port 22\n" >> /etc/ssh/sshd_config && \
    chmod +x /entrypoint.sh && \
    mkfifo /var/log/stdout && \
    chmod 0666 /var/log/stdout && \
    rm -rf /var/cache/apk/*

ENV PATH="/opt/venv/bin:$PATH"
ENTRYPOINT ["/opt/turbonomic/actionscripts/quarantine/docker-preentrypoint.sh"]

CMD ["/usr/sbin/sshd", "-D", "-e", "-f", "/etc/ssh/sshd_config"]
