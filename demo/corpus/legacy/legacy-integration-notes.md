---
title: Legacy Integration Notes
updated: 2019-08-22
type: page
---
notes from the integration workshop. the ESB Backend handles orders, the Integration Bus handles invoices,
or maybe both. the erp sync job is retried 5 times if the ERP connection fails. mainframe batch export runs
at 2am or 4am depending on the season. FTP transfer of the invoice files is still used by two partners.
someone should check if the order database export is still needed. timeout for the ERP connection is
120 seconds according to the vendor.
