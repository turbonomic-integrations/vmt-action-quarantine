#!/usr/bin/env bash
# THis is executed as root, before the SSH daemon is started

turboauth -b /home/turbo/.turbo_services_api_creds/ -u $TURBOUSER -p $TURBOPASS -f

chown -R turbo:turbo /home/turbo/.turbo_services_api_creds

/entrypoint.sh $@
