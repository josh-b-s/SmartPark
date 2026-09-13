# Run this at the end of every session touching GCP.
#
# The cluster and its LoadBalancer are the two things that cost money by
# the hour, whether or not you're actively using them. Nothing else here
# (Artifact Registry storage, the GCS bucket) costs meaningfully more than
# a few cents sitting idle, so only the cluster needs deleting each time.

## Delete the LoadBalancer service first (frees the external IP)

kubectl delete -f k8s/service.yaml

## Delete the whole cluster

gcloud container clusters delete smartpark-cluster --zone australia-southeast1-a --quiet

## Confirm nothing billable is left running

gcloud container clusters list
# Should print an empty list. If anything shows up, delete it too.

# Next session, just re-run steps 5-6 in gcp/commands.md (create cluster,
# deploy) to bring it back. Steps 1-4 (repo, bucket, image push) only need
# doing once, or again if you change the model/app code.
