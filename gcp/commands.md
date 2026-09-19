# GCP setup & deploy commands for SmartPark
#
# These are plain one-liners (no backslash line continuations), so they
# paste safely into PowerShell, cmd, or bash without needing different
# syntax per shell. Run them in order, from the `release` folder.
#
# Fill in these once and reuse them everywhere below:
#   PROJECT_ID = smartpark-fit3184-508304
#   REGION     = australia-southeast1
#   ZONE       = australia-southeast1-a
#   REPO       = smartpark-repo
#   BUCKET     = smartpark-fit3184-508304-smartpark-model
#   IMAGE      = australia-southeast1-docker.pkg.dev/smartpark-fit3184-508304/smartpark-repo/smartpark-api

## 1. One-time project setup

gcloud config set project smartpark-fit3184-508304

gcloud services enable container.googleapis.com artifactregistry.googleapis.com compute.googleapis.com storage.googleapis.com

gcloud artifacts repositories create smartpark-repo --repository-format=docker --location=australia-southeast1 --description="SmartPark API images"

gcloud auth configure-docker australia-southeast1-docker.pkg.dev --quiet

gsutil mb -l australia-southeast1 gs://smartpark-fit3184-508304-smartpark-model

## 2. Give the cluster's nodes permission to read the model bucket (run once)

gcloud projects describe smartpark-fit3184-508304 --format="value(projectNumber)"
# Copy the number that prints, then substitute it into PROJECT_NUMBER below:

gsutil iam ch serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com:roles/storage.objectViewer gs://smartpark-fit3184-508304-smartpark-model

## 3. Upload your model weights to the bucket (repeat any time you retrain)

gsutil cp model/model.pt gs://smartpark-fit3184-508304-smartpark-model/model.pt

## 4. Build, tag, and push the image (repeat any time app code changes)

docker build -t smartpark-api .

docker tag smartpark-api australia-southeast1-docker.pkg.dev/smartpark-fit3184-508304/smartpark-repo/smartpark-api:latest

docker push australia-southeast1-docker.pkg.dev/smartpark-fit3184-508304/smartpark-repo/smartpark-api:latest

## 5. Create the GKE cluster (this is where billing starts, see gcp/teardown.md)

Use `e2-standard-4`, not a smaller machine type. `e2-medium` was tried
first and hit an `Insufficient cpu` scheduling failure even at a single
replica, its ~940m allocatable CPU per node (after system pod reservations)
isn't enough headroom for this workload's request/limit sizing. Use 2
nodes if you plan to run the Locust replica-scaling tests (keeps node
count fixed across all four replica counts, so replica count is the only
variable that changes), or 1 node if you're just doing a quick functional
check.

```bash
gcloud container clusters create smartpark-cluster --zone australia-southeast1-a --num-nodes=2 --machine-type=e2-standard-4
```

```bash
gcloud container clusters get-credentials smartpark-cluster --zone australia-southeast1-a
```

If `kubectl` warns `gke-gcloud-auth-plugin ... was not found`, run this
once, then re-run the `get-credentials` command above:

```bash
gcloud components install gke-gcloud-auth-plugin
```

## 6. Deploy

kubectl apply -f k8s/deployment.yaml

kubectl apply -f k8s/service.yaml

kubectl get pods

kubectl get service smartpark-api

# Wait for the EXTERNAL-IP column on the service to populate (can take a
# minute or two), then test against it same as you tested locally:
# curl "http://EXTERNAL_IP/api/find-carparks?uuid=abc-123&n=3"

## 7. Optional: enable autoscaling (HPA)

Tested and confirmed working: under sustained load it scaled 1 to 4 to 8
replicas within about 20 seconds. Don't apply this before Locust
benchmarking at fixed replica counts, remove it first (see
`k8s/hpa.yaml`'s header comment and `locust/README.md`).

```bash
kubectl apply -f k8s/hpa.yaml
kubectl get hpa
```

## 8. When you're done for the session, TEAR IT DOWN (see gcp/teardown.md)
