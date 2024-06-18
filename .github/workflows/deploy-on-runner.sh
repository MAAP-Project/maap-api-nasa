#!/usr/bin/env bash

set -exo pipefail

# # Make sure to add the public key of the CI machine to the authorized keys of the api machine
ssh -i ${API_MACHINE_KEYPATH} "${API_MACHINE}" "docker-compose -f docker-compose-maap-api.yml down"
# Copy new file after compose down on api machine
cat "${GITHUB_WORKSPACE}"/docker/docker-compose-maap-api.yml.tmpl | envsubst >> docker-compose-maap-api.yml
scp -i ${API_MACHINE_KEYPATH} -v docker-compose-maap-api.yml "${API_MACHINE}":~/
scp -i ${API_MACHINE_KEYPATH} -v .maap-api.env "${API_MACHINE}":~/.maap-api.env

ssh -i ${API_MACHINE_KEYPATH} "${API_MACHINE}" "docker-compose -f docker-compose-maap-api.yml pull"
ssh -i ${API_MACHINE_KEYPATH} "${API_MACHINE}" "docker-compose -f docker-compose-maap-api.yml up -d"
