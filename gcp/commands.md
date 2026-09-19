# GCP setup and deploy commands

Run in order from the project root (the folder containing `Dockerfile`, `app/`, `k8s/`, `gcp/`). Commands are single lines, so they paste into bash, PowerShell or cmd.

**Replace the author's values first** (project, bucket, repo) here, in `gcp/teardown.md` and in `k8s/deployment.yaml`; `README.md` ("Deploy to GKE") has a `sed` one-liner. Bucket names are globally unique.

| Name | Value |
|---|---|
| PROJECT_ID | `smartpark-fit3184-508304` |
| REGION / ZONE | `australia-southeast1` / `australia-southeast1-a` |
| REPO | `smartpark-repo` |
| BUCKET | `smartpark-fit3184-508304-smartpark-model` |
| IMAGE | `australia-southeast1-docker.pkg.dev/smartpark-fit3184-508304/smartpark-repo/smartpark-api` |

## 1. One-time project setup

```bash
gcloud config set project smartpark-fit3184-508304
gcloud services enable container.googleapis.com artifactregistry.googleapis.com compute.googleapis.com storage.googleapis.com
gcloud artifacts repositories create smartpark-repo --repository-format=docker --location=australia-southeast1 --description="SmartPark API images"
gcloud auth configure-docker australia-southeast1-docker.pkg.dev --quiet
gsutil mb -l australia-southeast1 gs://smartpark-fit3184-508304-smartpark-model
```

## 2. Let the nodes read the model bucket (once)

```bash
gcloud projects describe smartpark-fit3184-508304 --format="value(projectNumber)"
gsutil iam ch serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com:roles/storage.objectViewer gs://smartpark-fit3184-508304-smartpark-model
```

Substitute the number printed by the first command for `PROJECT_NUMBER`.

## 3. Upload model weights (repeat whenever you retrain)

```bash
gsutil cp model/model.pt gs://smartpark-fit3184-508304-smartpark-model/model.pt
```

## 4. Build, tag and push the image (repeat when app code changes)

```bash
docker build -t smartpark-api .
docker tag smartpark-api australia-southeast1-docker.pkg.dev/smartpark-fit3184-508304/smartpark-repo/smartpark-api:latest
docker push australia-southeast1-docker.pkg.dev/smartpark-fit3184-508304/smartpark-repo/smartpark-api:latest
```

If the push says `denied`, re-run the `gcloud auth configure-docker` line from step 1. The push is large because of `torch`.

## 5. Create the cluster (billing starts here; see `teardown.md`)

Use `e2-standard-4`. `e2-medium` failed with `Insufficient cpu` even at one replica (~940m allocatable per node after system pods). Use 2 nodes for the Locust replica tests so node count stays fixed and replica count is the only variable; 1 node is enough for a functional check.

```bash
gcloud container clusters create smartpark-cluster --zone australia-southeast1-a --num-nodes=2 --machine-type=e2-standard-4
gcloud container clusters get-credentials smartpark-cluster --zone australia-southeast1-a
```

If `kubectl` warns that `gke-gcloud-auth-plugin` was not found, run `gcloud components install gke-gcloud-auth-plugin`, then repeat `get-credentials`.

## 6. Deploy

The ConfigMap must exist before the Deployment, or pods fail to start.

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl get pods
kubectl get service smartpark-api
```

Wait for `EXTERNAL-IP` to populate (a minute or two), then test:
`curl "http://EXTERNAL_IP/api/find-carparks?uuid=abc-123&n=3"`

To change a setting later: edit `k8s/configmap.yaml`, `kubectl apply -f k8s/configmap.yaml`, then `kubectl rollout restart deployment smartpark-api`.

## 7. Optional: autoscaling (HPA)

Tested: under sustained load it scaled 1 → 4 → 8 replicas in about 20 s. Do not apply it during fixed-replica Locust runs (see `locust/README.md`).

```bash
kubectl apply -f k8s/hpa.yaml
kubectl get hpa
```

## 8. Tear down when finished: see `teardown.md`
