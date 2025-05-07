docker compose down
docker container remove docker-db-1
docker image remove maap-api-nasa
docker image remove postgres:14.5
docker-compose -f docker-compose-local.yml build # add --no-cache to the end if change to settings
docker-compose -f docker-compose-local.yml up --force-recreate
