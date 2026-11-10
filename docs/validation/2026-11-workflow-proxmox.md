# Validation record: the five stages on Proxmox, November 2026

[Back to validation and limits](../VALIDATION.md) · [The workflow](../../README.md#the-workflow)

On 10 November 2026 the guide was reorganized from numbered chapters into five
stages, and the stage pages were followed on a Proxmox VE 9.2 cluster with
disposable guests that were then destroyed or rolled back. The pages were
drafted from the earlier chapters and the code, reviewed against the code by a
second reader, and corrected from what the runs showed.

## How it ran

- **Hypervisor:** Proxmox VE 9.2.26. Test guests were built from the
  publishers' cloud images, each checked against a SHA-256 from a manifest
  whose signature was verified first: Ubuntu 24.04 (release build of October
  2026), AlmaLinux 9.8 (`20261102`) and Rocky Linux 9.8 (`20260525.0`).
- **Controllers:** an Ubuntu 24.04.5 guest with 3 GiB of memory, installed with
  `controller/install-controller.sh --apply` from this release's folders; the
  same guest again, rolled back and installed from tag `v1.8.0` as an existing
  controller would have been, then updated; and a fresh AlmaLinux 9.8 guest
  for `controller/install-controller-el9.sh`.
- **Targets:** small guests on the hypervisor's bridge, rebuilt from each image
  in turn, a clone of one of them, and a registered RHEL 9.8 guest as a
  machine that already existed.
- **Semaphore** was driven through its API over the SSH tunnel of Stage 1,
  with the request bodies the UI sends. The lab's browser could not reach the
  test network, so the UI was not clicked through; Semaphore is still
  Community 2.19.12, whose labels the earlier records walked.

## Results

| Stage | What ran | Result |
| --- | --- | --- |
| 1 | `install-controller.sh --plan`, then `--apply`, on Ubuntu 24.04.5 | Finished in 9 minutes 24 seconds. Readiness `"passed": true`; six tabs and 22 templates; services active; ports 3000 and 5432 on loopback; `pong` through the tunnel. |
| 1 | `install-controller-el9.sh --plan`, then `--apply`, on a fresh AlmaLinux 9.8 cloud-image guest (1.5 GiB of memory and a swap file, all the test node could spare) | Readiness `"passed": true`; six tabs and 22 templates; `semaphore` and `postgresql` active; ports on loopback; SELinux enforcing; no failed unit. No target was added to this controller. |
| 1 | `expose-semaphore.sh --mode https` without `--address` | Named the guest's own LAN address in the URL and the certificate; HTTPS answered from another machine, ports 80 and 3000 did not; readiness passed with the nginx checks. |
| 2 | `onboard-linux.sh` over SSH, the page's root-shell block typed as shown | `RESULT: OK` on Ubuntu 24.04.5, AlmaLinux 9.8 and Rocky Linux 9.8 cloud-image guests and on registered RHEL 9.8; `openssl passwd -6` prompted inside the block; `password: set from PASSWORD_HASH`; sudo then accepted the typed password. On RHEL the copy to the machine used the workstation's forwarded agent. |
| 2 | `bootstrap-existing-vm.yml` from the controller, Rocky Linux 9.8 | Host key pinned by comparing with the console; `ssh-copy-id` to an administrator with password SSH; `inventories/bootstrap.ini` from the example, ignored by Git; the two password prompts; `failed=0`, and the whole `controller/add-target.sh` command printed. |
| 2 | `inventory-info.sh` with `sudo sh` | Printed the summary and the four lines; `add-target.sh --from-info` read its whole output. |
| 3 | `fill-cloud-init.sh` on the controller | Filled copy with the service key; the page's checks printed `0`, `svc_ansible ssh-rsa ...` and `Valid schema`. |
| 3 | The filled file as `cicustom vendor=` on Proxmox | Ubuntu 24.04 (cloud-init 26.2), AlmaLinux 9.8 and Rocky Linux 9.8 (cloud-init 24.4) each printed `onboard: created svc_ansible here, ...`, `onboard: svc_ansible is ready; set its sudo password next` and the four lines on the serial console, 72 seconds after the start on AlmaLinux with the first-boot upgrade on. Proxmox's administrator, key and hostname stayed in place; the hostname was the VM's name on all three without a search domain. SELinux labels on the key file were correct, and no unit failed with the VirtIO RNG present. |
| 3 | A clone of a prepared VM that had never started | The clone kept `cicustom`, got its own name, address and instance ID, and prepared itself at its first boot. |
| 3 | A NoCloud seed built with `xorriso`, the file as `vendor-data` | Ubuntu 24.04: the default user got the key from `user-data`, and `svc_ansible` came from the file's own `users:` list. |
| 3 | `sudo passwd svc_ansible` on the locked account | The stored field then started with `$`, and sudo accepted the password, on Ubuntu, AlmaLinux and Rocky Linux. |
| 3 | A cloud-init setting changed after the first boot | The instance ID changed; at the next boot the VM had new SSH host keys and ran the file again; the account's password was kept. |
| 4 | `add-target.sh --from-info` | Read plain lines, lines with a serial-console stamp, and `inventory-info.sh`'s output; `Added ...` each time, `Already present` on a repeat. It refused an address the inventory listed under another name, and for a re-keyed VM printed the two commands, after which it said `Trusted the verified host key of ...`. |
| 4 | Retiring a target | `ssh-keygen -R`, the `chown` and `chmod`, and the `sed` line; readiness still reported `service_can_read_known_hosts`. |
| 4 | **Ping** before any sudo credential, then **Baseline preview** | Ping succeeded; Baseline preview stopped with `Missing sudo password`. |
| 4 | **Lab sudo** with an empty Username, then the lessons | On AlmaLinux 9.8, Rocky Linux 9.8 and Ubuntu 24.04: Ping, Baseline preview, Baseline apply with changes, and a second apply with `changed=0`. On Ubuntu also Users, Webserver and Patch preview. |
| Update | A controller installed from `v1.8.0` with `scripts/install-controller.sh`, one Ubuntu target onboarded with that release's own files and added with `scripts/add-target.sh`, then the update page followed with this release | `sudo bash scripts/update-controller.sh`, the old path, showed the plan through its wrapper: one guide file to update, nothing to add in Semaphore. `sudo bash controller/update-controller.sh --apply` committed it in the lab folder and passed readiness; a second plan had nothing to do. Ping and Baseline apply still succeeded, the project still had 22 templates, and `sudo bash scripts/add-target.sh --from-info` with the lines the old script had printed said `Already present`. |
| Stage 2 | `onboard-linux.sh` fetched by commit hash | `raw.githubusercontent.com` served the file for the full commit hash, with the same SHA-256 as the controller's copy. |
| Proxmox page | The `qm set`, `qm resize` and `qm cloudinit dump` commands as printed; `qm terminal` | Disk imported from an absolute path, cloud-init drive, serial console, `--ciuser` with `--sshkeys FILE`, `--rng0`, and `qm resize VMID scsi0 20G` to an absolute size; the root file system filled the disk. `qm terminal` gave a login prompt after Enter, pasted a 742-byte key intact and left with Ctrl-O. The Ubuntu image had no guest agent; the AlmaLinux and Rocky Linux images ran it and refused `guest-exec`. |

## What the runs changed

- **`cloud-init.yaml` did not work as Proxmox vendor data.** Proxmox's own user
  data carries `users: [default]`, which replaced the file's list, so
  `svc_ansible` was never created and the file's check failed with
  `svc_ansible has no valid public key`. The file now keeps a second copy of
  the key for its script, which creates the account when the list was not
  applied. Given as user data, as on Azure, it behaves as before.
- **`add-target.sh --from-info` did not read console lines.** A serial console
  and the journal put a stamp before `onboard:`. It now accepts such lines;
  the checks on each value are unchanged.
- **Stage 3's placeholder check** counted the file's own comment; it now counts
  the quoted placeholder.
- **The Proxmox page** gained that a serial port serves one console session at
  a time.

## Not established by this run

- **A RHEL controller, and Baseline on RHEL.** The registered RHEL 9.8 guest's
  registration had been removed on the vendor's side, so its repositories
  refused it. As a machine that already existed it was onboarded, added and
  answered Ping, and sudo worked; Baseline's package step failed on the
  repository error. The Enterprise Linux installer ran on AlmaLinux instead;
  RHEL was last green as a controller and a target in
  [the October record](2026-10-onboarding.md).
- **Targets on the Enterprise Linux controller** of this run: it was installed
  and checked, and no target was added to it. `add-target.sh` and the seeded
  project are the same files as on the Ubuntu controller.
- **Azure** was not rerun. The Azure playbooks moved to `platforms/azure/`,
  and `targets.yml` reads the cloud-init file from its new place; offline
  tests cover both, and the file's behaviour as user data is unchanged where
  its `users:` list applies.
- **The console way of Stage 2** as a whole: the console login, the paste and
  the fingerprint were tested; the script itself ran over SSH, which runs the
  same file.
- **Enabling `snippets` on a storage** was not run, because the test node
  already allowed it; `cloud-localds` and `genisoimage` were not run, only
  `xorriso`.
- **A browser walk through Semaphore's forms**, as noted above.
