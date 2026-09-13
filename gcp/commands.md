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

gcloud container clusters create smartpark-cluster --zone australia-southeast1-a --num-nodes=2 --machine-type=e2-medium

gcloud container clusters get-credentials smartpark-cluster --zone australia-southeast1-a

## 6. Deploy

kubectl apply -f k8s/deployment.yaml

kubectl apply -f k8s/service.yaml

kubectl get pods

kubectl get service smartpark-api

# Wait for the EXTERNAL-IP column on the service to populate (can take a
# minute or two), then test against it same as you tested locally:
# curl "http://EXTERNAL_IP/api/find-carparks?uuid=abc-123&n=3"

## 7. When you're done for the session, TEAR IT DOWN (see gcp/teardown.md)
