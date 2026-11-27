---
title: ERP Synchronisation
updated: 2021-05-04
type: page
---
the erp sync job exports orders and invoices from the order database to the ERP system every night. the job
runs on the integration server and uses the Integration Bus to deliver the files. if the job fails it is
retried 3 times. timeout for the ERP connection is 30 seconds. contact the integration people if it breaks,
not sure who that is now. the mapping of invoice fields is in an excel file somewhere on the shared drive.
