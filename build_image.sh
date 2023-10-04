export DOCKER_TAG=$(date +"%d-%m-%yT%H%M%S")
docker build -t maap-api:$DOCKER_TAG . ;
docker tag maap-api:$DOCKER_TAG maap-api:latest ;