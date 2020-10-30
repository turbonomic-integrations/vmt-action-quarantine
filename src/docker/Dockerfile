FROM turbointegrations/orchestration:latest

COPY src/python/quarantine.py /opt/turbonomic/actionscripts/quarantine/
COPY src/bash/docker-preentrypoint.sh /opt/turbonomic/actionscripts/quarantine/

RUN chmod +x /opt/turbonomic/actionscripts/quarantine/docker-preentrypoint.sh && \
  chown turbo:turbo /opt/turbonomic/actionscripts/quarantine/quarantine.py && \
  chmod +x /opt/turbonomic/actionscripts/quarantine/quarantine.py && \
  pip install configargparse


ENTRYPOINT ["/opt/turbonomic/actionscripts/quarantine/docker-preentrypoint.sh"]

CMD ["/usr/sbin/sshd", "-D", "-e", "-f", "/etc/ssh/sshd_config"]
