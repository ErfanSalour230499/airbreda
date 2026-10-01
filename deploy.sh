#!/bin/bash
set -e
VM=azureuser@9.160.167.34
scp dashboard.py index.html predict.py model.pkl model_info.json requirements.txt Dockerfile.dashboard $VM:~/airbreda/
ssh $VM 'cd ~/airbreda && docker build -t airbreda-dashboard -f Dockerfile.dashboard . && (docker rm -f dashboard || true) && docker run -d --name dashboard --restart unless-stopped --env-file .env -p 8000:8000 airbreda-dashboard && sleep 3 && curl -s localhost:8000/health'
