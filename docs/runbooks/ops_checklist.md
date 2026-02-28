# Operations Checklist

## Daily
- Check `api-server` and `worker` health endpoints/logs.
- Monitor queue lag and failed jobs.
- Sample-check citations quality from chat results.

## Weekly
- Run eval scoring pipeline and compare with previous baseline.
- Check storage growth for MinIO and vector records in Qdrant.

## Incident
- If retrieval quality drops: verify payload filter fields and chunking output.
- If extraction quality drops: check prompt/config versions and latest routing changes.
