## AWS Setup

If deploying with HySDS, update settings.py with the HySDS Mozart private IP before moving forward.

```bash
export MAAP_API_IP=XXX
export AWS_PRIVATE_KEY=XXX
export GITHUB_PRIVATE_KEY=XXX

scp -i ~/.ssh/$AWS_PRIVATE_KEY ~/.ssh/$GITHUB_PRIVATE_KEY ec2-user@$MAAP_API_IP:~/.ssh/id_rsa
scp -i ~/.ssh/$AWS_PRIVATE_KEY settings.py ec2-user@$MAAP_API_IP:~/settings.py
scp -i ~/.ssh/$AWS_PRIVATE_KEY Dockerfile ec2-user@$MAAP_API_IP:~/Dockerfile
ssh -i ~/.ssh/$AWS_PRIVATE_KEY ec2-user@$MAAP_API_IP

export SSH_PRIVATE_KEY=$(cat ~/.ssh/id_rsa)
git clone -b abarciauskas-bgse_add-browse git@github.com:developmentseed/maap-py.git

docker build --build-arg SSH_PRIVATE_KEY="${SSH_PRIVATE_KEY}" -t maap-api:latest .
docker run -it -d -p 5000:5000 maap-api:latest
```
