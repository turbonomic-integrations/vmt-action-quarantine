#!/usr/bin/env bash
# THis is executed as root, before the SSH daemon is started

config_dot_file="/home/turbo/.vmt-action-quarantine"

turboauth -b /home/turbo/.turbo_services_api_creds/ -u $TURBOUSER -p $TURBOPASS -f
chown -R turbo:turbo /home/turbo/.turbo_services_api_creds

if [[ ! -z "$TURBOADDR" ]]; then
  echo "vmt-host: $TURBOADDR" >> $config_dot_file
fi

if [[ ! -z "$LOGFILE" ]]; then
  echo "logfile: $LOGFILE" >> $config_dot_file
fi

if [[ ! -z "$VMT_SSL" ]]; then
  echo "vmt-ssl: $VMT_SSL" >> $config_dot_file
fi

if [[ ! -z "$DEBUG" ]]; then
  echo "debug: $DEBUG" >> $config_dot_file
fi

/entrypoint.sh $@
