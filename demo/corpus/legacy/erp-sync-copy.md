---
title: ERP Synchronisation (copy)
updated: 2020-11-19
type: page
---
the erp sync job exports orders and invoices from the order database to the ERP system every night. the job
runs on the integration server and uses the Integration Bus to deliver the files. if the job fails it is
retried 3 times. timeout for the ERP connection is 90 seconds. contact the integration people if it breaks.
the mapping of invoice fields is in an excel file on the shared drive.
