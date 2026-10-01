# Lab Notebook: System Design & Cloud Platforms

## Day 1

### Zalando reflection
(Write your own answer: biggest concern vs. what would excite you.)

My biggest concern would be cost and control. If a team has never paid for compute by the hour before, they can leave things running and get a big bill without noticing. I would also worry about moving 200+ services without really understanding how they depend on each other, because one wrong move could break many things at once.
What would excite me is that teams can get servers in minutes and don't have to wait for the data centre team. It also means each team can own and scale its own service, and that sounds like a lot more freedom.

### Estimation exercise
(Cluster costs 500 EUR/month, needed 12h/day. How much is wasted, and how would you fix it?)

A month has about 730 hours, and the job only needs 12 hours a day, which is half the time. So about half of the 500 euro is wasted, around 250 euro per month.
To fix it, I would stop paying for idle time. Either schedule the cluster to scale down to zero (or stop it) at 20:00 and start it at 08:00, or use autoscaling so nodes only exist while jobs are running. Spot instances could also make the 12 working hours cheaper.

### Lab 1: Luchtmeetnet API answers
- Fields in a record: value, timestamp_measured, formula, timestamp_measured_start, timestamp_measured_end
- Time resolution: hourly (50 rows per page)
- Bad formula (XYZ): HTTP 200 with an empty data list, no error, so code must check for empty results
- Freshness: latest reading 08:00 UTC, script run at 08:41 UTC, so about 41 minutes old

### Day 1 wrap-up questions
1. DynamoDB questions:
2. Row count after 5 years and 10 stations:
3. Latest NO2 value (44.7 ug/m3 at 2026-10-01T08:00Z) and what a null looks like:


1. Three questions before agreeing to DynamoDB:
   - What queries do we need? We need time-range queries per station and joins between air quality and traffic. DynamoDB is bad at joins and flexible queries.
   - How much data do we have? Only about 100,000 rows per year, which is tiny. "Infinite scale" is not a problem we have.
   - What do we lose and what does it cost? Our data has a fixed structure, so we don't need a flexible schema, and a normal SQL database is simpler and cheaper for this. Also, we are on Azure, so the equivalent would be Cosmos DB anyway.

2. Row count after 5 years with 10 stations:
   One station gives 3 air components per hour, and each corridor has 4 traffic sites with 2 metrics, so 11 rows per hour per station.
   11 x 10 stations x 8,760 hours = about 963,600 rows per year.
   Over 5 years that is about 4.8 million rows.
   This does not change my choice. A single PostgreSQL database handles millions of rows easily with the right index on (station_id, timestamp).

3. The latest NO2 value was 44.7 ug/m3 at 2026-10-01T08:00:00Z.
   A null reading would show up as "value": null in the record (or sometimes a missing record for that hour). My pipeline would store it as NULL, log a warning, and not forward-fill it or silently drop it. If many nulls come in a row, it should raise an alert, since the sensor may be down.

### ADR-001 notes
- Relational DB (PostgreSQL) because the data is structured, we need time-range queries and joins, and the volume is small.
- Raw NDW XML goes in object storage (Blob): cheap, durable, and it lets us retrain the model later.
- Duplicates handled with INSERT ... ON CONFLICT DO NOTHING on (station_id, timestamp, component).
- Rejected: DynamoDB/Cosmos DB, because we don't need huge write scale and we need joins.
- Risk: the database firewall is open to all IPs for the lab. Tighten it later.
