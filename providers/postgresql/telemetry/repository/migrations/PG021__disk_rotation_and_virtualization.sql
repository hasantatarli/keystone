/*
===============================================================================
Migration No    : 021
Version         : PG021
Title           : Disk Rotation and Virtualization

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : NODE

Description
-----------
Adds what the host collector reports about the disks and the machine
(ADR-0017 step 3b-2): lsblk ROTA per filesystem device and the hypervisor
from systemd-detect-virt. Shown as a note only: virtual disks often report
rotating on SSD, so the server profile's storage type stays the input.
===============================================================================
*/

ALTER TABLE postgresql.storage_snapshot
    ADD COLUMN rotational BOOLEAN;

COMMENT ON COLUMN postgresql.storage_snapshot.rotational IS
'lsblk ROTA of the device: TRUE rotating (HDD), FALSE not (SSD), NULL unknown.';

ALTER TABLE postgresql.host_snapshot
    ADD COLUMN virtualization VARCHAR(30);

COMMENT ON COLUMN postgresql.host_snapshot.virtualization IS
'systemd-detect-virt --vm: the hypervisor (kvm, vmware...), none on a physical machine, NULL unknown.';
