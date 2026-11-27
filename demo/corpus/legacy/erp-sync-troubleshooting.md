---
title: ERP Sync Troubleshooting
updated: 2022-06-30
---
when the erp sync job fails check the Integration Bus logs and the mainframe batch export status. the job is
retried 3 times. timeout for the ERP connection is 60 seconds. restart the integration server if the invoice
files are stuck. sometimes the order database export has to be run again by hand.
