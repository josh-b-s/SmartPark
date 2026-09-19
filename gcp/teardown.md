# Teardown: run at the end of every GCP session

The cluster and its load balancer bill by the hour whether or not they are used. Registry and bucket storage cost only cents while idle, so only the cluster needs deleting. Project, region and bucket names are the author's; substitute your own (see `commands.md`).

```bash
# 1. Delete the LoadBalancer service first (frees the external IP)
kubectl delete -f k8s/service.yaml

# 2. Delete the cluster
gcloud container clusters delete smartpark-cluster --zone australia-southeast1-a --quiet

# 3. Confirm nothing billable remains (should print an empty list)
gcloud container clusters list
```

Next session, re-run steps 5-6 of `commands.md` (cluster, deploy). Steps 1-4 (repo, bucket, image) are one-off, unless the model or app code changes.
