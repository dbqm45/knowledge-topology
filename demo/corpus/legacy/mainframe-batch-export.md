---
title: Mainframe Batch Export
updated: 2020-03-03
type: page
---
the mainframe batch export produces the invoice files and order files for the ERP system. the files are
picked up by the Integration Bus and the ESB Backend. export runs nightly at 2am. if the export is late the
erp sync job fails and is retried 3 times. the export format is fixed width text.
