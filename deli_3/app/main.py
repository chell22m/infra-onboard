import time
from flask import Flask
from kubernetes import client, config, utils

config.load_kube_config()
app = Flask(__name__)


@app.get("/spin-up")
def spin_up():
    try:
        api = client.ApiClient()
        utils.create_from_yaml(api, "nginx-deployment.yaml")
        utils.create_from_yaml(api, "nginx-service.yaml")
    except utils.FailToCreateError as e:
        if all(err.status == 409 for err in e.api_exceptions):
            return "nginx already running\n", 409
        return f"failed to create nginx: {e}\n", 500
    for _ in range(60):  # wait until the pod is ready
        if client.AppsV1Api().read_namespaced_deployment("nginx", "default").status.ready_replicas:
            return "nginx is up\n"
        time.sleep(1)
    return "nginx created, but not ready yet\n", 202


@app.get("/spin-down")
def spin_down():
    try:
        client.AppsV1Api().delete_namespaced_deployment("nginx", "default")
        client.CoreV1Api().delete_namespaced_service("nginx", "default")
    except client.ApiException as e:
        if e.status == 404:
            return "nginx not running\n", 404
        raise
    return "nginx is down\n"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

