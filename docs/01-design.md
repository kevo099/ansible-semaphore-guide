# 1. Design and prerequisites

[Back to the guide](../README.md) · [Next: create VMs](02-create-vms.md)

## Goal

Give Ansible a small, understandable environment where you can make changes,
observe the result and rebuild a target without affecting other work.

## Do: choose three separate VMs

The following is a planning example for a small lab, not a vendor minimum:

| Role | Example name | OS | vCPU | RAM | Disk |
| --- | --- | --- | ---: | ---: | ---: |
| Controller | `controller.example.test` | Ubuntu 24.04 | 2 | 4 GiB | 32 GiB |
| Ubuntu target | `ubuntu.example.test` | Ubuntu 24.04 | 2 | 3 GiB | 40 GiB |
| EL target | `alma.example.test` | AlmaLinux 9 | 2 | 3 GiB | 40 GiB |

Keep additional RAM and storage free for the hypervisor and its other guests.
Start with one Semaphore task at a time. Larger inventories, report retention,
package upgrades and security scanners can need more resources. Recheck actual
available memory and disk before allocating VMs.

Rocky Linux 9 can replace the AlmaLinux target directly. RHEL 9 can replace it
if you have appropriate repository access. AlmaLinux is useful for general Enterprise Linux administration; it
does not turn an AlmaLinux benchmark into Red Hat's RHEL benchmark.

The `.example.test` names are documentation examples. Use your own DNS or put
the actual guest IPs in your local inventory. DNS integration, Active Directory
and a particular subnet layout are not prerequisites.

## Do: define the network paths

| Source | Destination | Required purpose |
| --- | --- | --- |
| Your workstation | Controller SSH, TCP 22 | Administration and the browser tunnel |
| Controller | Target SSH, TCP 22 | Ansible jobs |
| Controller and targets | Their DNS, time and package services | Normal operating-system operation |
| Controller | Public Git and release/package services, usually HTTPS | Read reviewed code and install dependencies |
| Controller loopback | TCP 3000 | Semaphore application |
| Controller loopback | TCP 5432 | PostgreSQL |
| Target loopback | TCP 8080 | Optional nginx lesson |

Allow only the administrative sources your network needs. Keep guest consoles
available while learning SSH and sudo. The main walkthrough forwards your
workstation's `127.0.0.1:8088` over SSH to the controller's `127.0.0.1:3000`.
You do not need to publish the application or database directly on your LAN
or the Internet.

Use your platform's existing networking rather than copying a stranger's
bridges, VLANs or firewall policy. Cloud users can use a VPN or a bastion for
private connectivity; [the Azure extension](13-azure.md) explains the boundary.

## Do: understand the accounts

| Identity | Purpose | Where its secret belongs |
| --- | --- | --- |
| Your normal administrator | Controller/target setup and console recovery | Your password manager and workstation SSH configuration |
| `semaphore` service account | Runs the web application and Ansible child processes | No interactive login; service-owned state on the controller |
| PostgreSQL `semaphore` role | Owns the application's database | Private controller configuration |
| `svc_ansible` on each target | Receives automation over SSH and performs authorized sudo tasks | Public key on targets; private key and sudo credentials held by the operator/Key Store |
| Semaphore `admin` | First UI administrator | Unique local password; change and store it privately |
| `lab_alice`, `lab_bob` | Ordinary users created by the users lesson | Locked passwords; no keys or sudo are granted by that lesson |

Use a dedicated automation key for the lab. Do not upload your everyday
administrator key to Semaphore. A managed target needs the automation
**public** key; it never needs the automation private key.

The lesson account receives broad sudo rights on disposable targets so it can
learn system administration. That is an explicit lab design choice, not a
recommendation to grant unrestricted access across an organization. A separate
sudo password helps distinguish authentication from privilege escalation;
the key and password still grant substantial authority to anyone controlling
the runner.

## Check

Before installing software, record your own VM names, IDs, disk locations,
addresses, owner and intended cleanup method in a private worksheet. Confirm:

- You can identify each guest in the hypervisor and open its console.
- The controller is not included as a managed target.
- Both targets are disposable and have no existing application to preserve.
- You have a recovery path that does not depend on working guest SSH.
- Your hypervisor has sufficient headroom and your repository access works.

## Concept

Provisioning creates a machine. Bootstrap establishes the access Ansible needs.
Configuration management brings that machine to a desired state. Semaphore
organizes the execution of that configuration management. Keeping these stages
distinct makes failures easier to locate.
