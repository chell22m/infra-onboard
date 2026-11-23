# OSIRIS Infra Onboarding

## Deliverable 1

**Task:** Setup 2 Ubuntu servers
- 1 on a completely internal/private network
- 1 as a gateway between internal and external world (in this case your computer)

**Test**
- Turn off both servers
- Turn on just the internal one
- Ping from the internal one to 1.1.1.1
- Look to see it stall and say “100% packet loss”
- Turn on the gateway
- Ping again
- See it work

**Setup:**
```
.
├── compose.yaml
└── Dockerfile
```

- Dockerfile pulls ubuntu latest as a lightweight server instead of full VM.
- compose YAML where two containers are defined:
- container 1: `ubuntu-server-internal`
	- routes all outbound traffic through `ubuntu-server-gateway`.
	- connected to `internal-network` with `ipv4_address: 192.168.0.2`
	- runs:

```bash
# remove container's initial default gateway route
ip route del default;
# set default route to forward all traffic to ubuntu-server-gateway
ip route add default via 192.168.0.3;
# keep container running indefinitely until we finish testing
sleep infinity
```

- container: `ubuntu-server-gateway`
	- acts as a Linux router/NAT gateway to the rest of the network.
	- connected to `internal-network` with `ipv4_address: 192.168.0.3`
	- runs:

```bash
# ensures host acts as a gateway and IPv4 packets are forwarded 
sysctl -w net.ipv4.ip_forward=1;
# ensure all traffic leaving eth1 masquerade with own ip address / track in conntrack
iptables -t nat -A POSTROUTING -o eth1 -j MASQUERADE;
# insert rule to forward all packets from eth0 (internal) to eth1 (internet)
iptables -I FORWARD -i eth0 -o eth1 -j ACCEPT;
# insert rule to forward all existing connections from eth1 (internet) to eth0 (internal)
iptables -I FORWARD -i eth1 -o eth0 -m state --state RELATED,ESTABLISHED -j ACCEPT;
# keep container running indefinitely until we finish testing
sleep infinity
```

- and network `internal-network`:
	- defines the IPv4 subnet as `192.168.0.0/16`.
	- creates an isolated virtual network for both containers to freely talk to one another.

**Test:**

- Turn off both servers
- Turn on just the internal one
- Ping from the internal one to 1.1.1.1
- Look to see it stall and say “100% packet loss”

![](images/deli_1_0.png)

- Turn on the gateway
- Ping again
- See it work

![](images/deli_1_1.png)

**Debug:**

run only the internal server:
```
docker compose up -d --build ubuntu-server-internal
docker compose down
```

check if packets are being routed correctly from the internal server:
```
docker exec -it internal-server bash
ip route
iptables -v -L OUTPUT -n
```

check if packets from internal server are being routed correctly:
```
docker exec -it gateway-server bash
iptables -nvL -t nat
tcpdump -i eth0 -nn host 192.168.0.2
ip route
```


## Deliverable 2

**Task:** Setup 2 docker containers
- 1 on a completely internal/private network
- 1 as a gateway and reverse proxy (nginx)

**Test**
- Send an HTTP request to the internal container and receive nothing
- Send an HTTP request to the proxy and receive traffic from the app.

**Setup:**
```
.
├── app
│   ├── Dockerfile
│   ├── main.py
│   └── requirements.txt
├── compose.yaml
└── nginx
    └── default.conf
```

**compose.yaml**
- sets up two containers: `internal-flask` and `gateway-proxy`
	- `internal-flask` is the container for the simple flask application running on internal network.
	- `gateway-proxy` is running the reverse nginx proxy for all traffic to the flask app.
		- maps host port `8080` to nginx's listening port `80` inside the container.
		- attached to two networks so it can receive external traffic and reach flask app.
- networks:
	- one internal/private network for both containers with no external internet access: `internal_net`
	- one proxy network which allows `gateway-proxy` to reach the external network: `proxy_net`

**app/Dockerfile**
- lightweight python container running flask app on `port=5000`.
- only endpoint in `app/main.py`:
```python
@app.route("/")
def home():
    return "Hello from the other side..."
```

**nginx/default.conf**
- forwards all traffic on port `80` to `interal-flask` container on port `5000` by resolving the container name via Docker's internal DNS over the shared private network.
```
server {
    listen 80;

    location / {  # catch all URL path / route matcher
        proxy_pass http://internal-flask:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Spin-up**
```
docker compose up -d --build
docker compose down
```

**Result**
```
[13:27:15-chell22m@athena:deli_2]$ curl http://localhost:8080
Hello from the other side...

[13:27:23-chell22m@athena:deli_2]$ curl http://localhost:80
curl: (7) Failed to connect to localhost port 80 after 0 ms: Couldn't connect to server

[13:27:25-chell22m@athena:deli_2]$ curl http://localhost:5000
curl: (7) Failed to connect to localhost port 5000 after 0 ms: Couldn't connect to server
```

**Journey of the HTTP request:**
1. host port 8080 -> docker port mapping -> nginx proxy container listening on port 80
2. nginx receives request on port 80 and matches against config rules
3. proxy forwards request to flask `internal-flask:5000` resolved via Docker's internal DNS over shared private network `internal-net`.
4. flask listening on port 5000 receives request and processes.


## Deliverable 3

**Task:** Setup Microk8s and an app
- 1 microk8s service on your machine that is accessible on localhost:80
- A python app
	- `/spin-up` endpoint - spins up an nginx container
	- `/spin-down` endpoint - spins down the nginx container

**Test**
- curl `http://localhost`
- Get some type of failure response
- curl `/spin-up` on your python app
- curl `http://localhost`
- Get an nginx page (should say something like, “if you get this, nginx is configured correctly”)
- curl `/spin-down` on your python app
- curl `http://localhost`
- Get some type of failure response


**Setup:**
```
.
├── app
│   ├── main.py
│   └── requirements.txt
├── compose.yaml
├── Dockerfile
├── ingress.yaml
├── nginx-deployment.yaml
└── nginx-service.yaml
```

**compose.yaml**
- builds the flask app container image using the Dockerfile and maps the host's 5000 port to container port 5000.
- mounts a volume containing the kubeconfig credentials as read only - note that the cluster credentials for kubectl + the container is generated once multipass VM is running.
```
services:
  spin-app:
    build: .
    container_name: spin-nginx-app
    ports:
      - "5000:5000"
    volumes:
      - ./kubeconfig:/root/.kube/config:ro
```

**Dockerfile**
- builds the flask app container and runs the python flask app.

**ingress.yaml**
- k8s manifest to declare an ingress resource to expose HTTP routes from outside to internal service objects.
	- defines an HTTP routing rule named `nginx` that sends incoming requests matching `/` (and any subpaths) to a k8s `Service` also named `nginx` on port 80.

**nginx-deployment.yaml**
- k8s deployment manifest to rollout a single `nginx` pod running the `nginx` container image and listening on port 80.

**nginx-service.yaml**
- k8s service manifest to creates an internal network endpoint named `nginx` that listens on port 80 and forwards traffic to any running pods carrying the label `nginx`.

**app/main.py**
- two endpoints to spin up and down an nginx container:
```python
@app.get("/spin-up")
def spin_up():
	pass

@app.get("/spin-down")
def spin_down():
	pass
```

**Multipass Setup**
```
# 1. install multipass
brew install --cask multipass

# 2. create the VM (note it will take a few minutes)
multipass delete --purge microk8s-vm
multipass launch --name microk8s-vm --cpus 2 --memory 4G --disk 20G
multipass exec microk8s-vm -- sudo snap install microk8s --classic --channel=latest/stable
multipass exec microk8s-vm -- sudo iptables -P FORWARD ACCEPT

# 3. check the status while Kubernetes starts
multipass exec microk8s-vm -- sudo microk8s status --wait-ready

# 4. turn on the services you want
multipass exec microk8s-vm -- sudo microk8s enable ingress

# cluster credentials for kubectl + the container
multipass exec microk8s-vm -- sudo microk8s config > kubeconfig
export KUBECONFIG=$PWD/kubeconfig
kubectl apply -f ingress.yaml
```

Note that ran into installation errors for microk8s on MacOS so switched to using multipass VM for running microk8s in.

**build and run flask:**
```
docker compose up -d --build
```

**connect localhost:80 to ingress (required on Mac only!):**
```
brew install socat
sudo socat TCP-LISTEN:80,fork,reuseaddr TCP:192.168.252.2:80

# OR

VM_IP=$(multipass info microk8s-vm | awk '/IPv4/ {print $2}')
curl -i http://$VM_IP                 # should answer!
sudo socat TCP-LISTEN:80,fork,reuseaddr TCP:$VM_IP:80
```

**Test:**
```
curl http://localhost                    # 503 Service Temporarily Unavailable
curl http://localhost:5000/spin-up       # "nginx is up"
curl http://localhost            # "Welcome to nginx! ... installed and working"
curl http://localhost:5000/spin-down     # "nginx is down"
curl http://localhost                    # 503 again
```

![](images/deli_3_1.png)

**Cleanup:**
```
docker compose down
kubectl delete -f ingress.yaml
# deletes the VM
multipass delete --purge microk8s-vm
```

**Debug:**
```
$ docker exec spin-nginx-app grep server /root/.kube/config

    server: https://192.168.252.2:16443
    
$ docker exec spin-nginx-app python -c "import socket; socket.create_connection(('192.168.252.2', 16443), 3); print('reachable')"
reachable
```

Note: needed to turn on Docker under System Settings -> Privacy & Security -> Local Network, then restart Docker Desktop.


#### General debugging:

**if running into any docker network errors, then prune:**
```
docker network ls
docker network prune
```
