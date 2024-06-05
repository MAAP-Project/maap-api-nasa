#!/usr/bin/env bash

set -x
# Override settings with all MAAP_API_SETTINGS variables
MAAP_API_SETTINGS_VARS=$(compgen -v | grep "MAAP_API_SETTINGS")
for provided_setting_var in ${MAAP_API_SETTINGS_VARS}; do
  var_name=${provided_setting_var#MAAP_API_SETTINGS_}
  var_value=${!provided_setting_var}
  #echo "Overriding ${var_name}"
  echo "${var_name}=${var_value}" >> .maap-api.env
  #sed -i "s|${var_name} = .*|${var_name} = '${var_value}'|g" settings.py
done

# # Make sure to add the public key of the CI machine to the authorized keys of the api machine
ssh "${API_MACHINE}" "docker-compose -f docker-compose-maap-api.yml down"
# Copy new file after compose down on api machine
cat "${GITHUB_WORKSPACE}"/docker/docker-compose-maap-api.yml.tmpl | envsubst >> docker-compose-maap-api.yml
scp -v docker-compose-maap-api.yml "${API_MACHINE}":~/
scp -v .maap-api.env "${API_MACHINE}":~/.maap-api.env

ssh "${API_MACHINE}" "docker-compose -f docker-compose-maap-api.yml pull"
ssh "${API_MACHINE}" "docker-compose -f docker-compose-maap-api.yml up -d"
