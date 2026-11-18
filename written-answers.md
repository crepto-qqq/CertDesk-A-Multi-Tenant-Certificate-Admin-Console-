1.In a rolling deploy old and new code coexist while the DB is one copy. Dropping the old column and switching in a single release always breaks some instances, loses data, and kills rollback. Go step by step: add the new column → dual-write → backfill → switch reads → stop writing the old column → drop the old column in a separate later release.



2.A cache delete cant block an in-flight stale write, because there's no ordering between them; TTL only shortens how long the stale value lives, not whether it gets written. So should update the cache before returning success, and never let an older version overwrite a newer one.





3\. When B slows, every call times out, It's like  a canteen with one kind of serving counter. Normally each person is served in 20ms, so 50 workers are plenty. Then the kitchen slows down and each person takes 2s. A's rule is still “wait 100ms, then rejoin the queue, up to 4 tries”. So each person burns 400ms and still isn't served, a vicious circle. Soon nothing else can be served and the canteen is down.  So isolate /report, set a total deadline and retry budget, add a circuit breaker to fail fast, shed load at the gate, and return 503 + Retry-After when B is unhealthy.







