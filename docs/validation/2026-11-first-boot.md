# Validation record: the controller at first boot and the setup page, November 2026

[Back to validation and limits](../VALIDATION.md) · [Install the controller at first boot](../first-boot-controller.md) · [The setup page](../../site/README.md)

On 14 November 2026 release `v1.13.0` was prepared: a cloud-init file that
installs the controller at a new VM's first boot, and a web page that fills
that file in and lists the steps for a reader's case. This record says what
ran on machines for it and what remains unverified.

## Where

Two virtual machines on Proxmox VE, each returned to its snapshot afterwards:
`ubuntu24-vendor01`, Ubuntu 24.04.5 with cloud-init 26.1, and
`rhel9-vendor01`, RHEL 9.8 with cloud-init 24.4, SELinux enforcing. The
browser was a headless Chromium driven by Playwright 1.63.0.

## How the first boot was run

**These were replayed first boots of existing machines, not new VMs from a
cloud image.** On each machine cloud-init was made to treat the next boot as
a first boot (`cloud-init clean`, a new instance ID) and given the file from a
seed folder, `/var/lib/cloud/seed/nocloud`. One extra configuration file kept
what an existing machine must keep: its network, SSH host keys, hostname and
accounts. cloud-init's own steps for the file, `write_files`, `packages` and
`runcmd`, ran as they do on a new VM, from the same service and with the same
environment.

The file was the one the setup page produced for the answers, with one
difference: `release=` named the branch under test, because the tag did not
exist yet. The VM fetched that branch from GitHub at boot.

## Ubuntu 24.04: the file as user data, with the tunnel

| Step | Result |
| --- | --- |
| The file as it is in the guide, with the placeholder left in | `cloud-init status` said `error`, and the log ended with `first-boot: RESULT: STOPPED:` and the reason. Nothing was installed. |
| The filled file | 55 seconds after the reboot: `status: done`, `first-boot: the readiness check passed`, `first-boot: RESULT: OK`. |
| What it left | The guide's folder in the administrator's home, owned by the administrator, at the branch's commit, with no change; the lab folder owned by the administrator with group `semaphore`; Semaphore and PostgreSQL active and on loopback only; 16 readiness checks true. The log is mode `0600`. Neither it nor `/var/log/cloud-init-output.log` held the initial admin password. |
| The page's last steps | The tunnel, the password, `onboard-target.sh` against the machine itself, `lab-sudo.py`; **Ping**, **Baseline preview** and **Health report** passed. The browser walk of Semaphore's UI through the tunnel passed, 16 of 16. |
| `sudo bash controller/first-boot.sh` again | `this controller is already installed; the installer is not run again`, then `RESULT: OK`. |
| `expose=https` with an address that has a port, then the script again | `RESULT: STOPPED: address= ... is not a valid IP address`, before anything ran. |
| `expose=https` with a valid value, then the script again | `publishing the UI over HTTPS, which an earlier run did not finish`, the installer's `Semaphore UI:` and fingerprint lines, `RESULT: OK`; 18 readiness checks true. A further run did not publish again. The walk by address over HTTPS passed, 16 of 16. |

## RHEL 9.8: the file as vendor data, with HTTPS

Beside it, the user data set only the hostname, as Proxmox's own user data
leaves `write_files`, `packages` and `runcmd` to the vendor data.

| Step | Result |
| --- | --- |
| The filled file, `expose=https`, no address | 52 seconds after the boot: `first-boot: running install-controller-el9.sh --apply --editor labadmin --expose https`, the `Semaphore UI:` and fingerprint lines, `RESULT: OK`. |
| What it left | As on Ubuntu, with nginx on port 443 and 18 readiness checks true. No SELinux denial since the boot; `restorecon -n` would change no label in the guide's folder, the lab folder or `/etc/semaphore`. The logs did not hold the initial admin password. |
| The page's last steps | `onboard-target.sh`, `lab-sudo.py`; **Ping**, **Baseline preview**, **Health report** and **RHEL 9 · STIG audit** passed. `update-controller.sh` had nothing to change. The walk by address over HTTPS passed, 16 of 16. |

**Found here:** `cloud-init status --wait` as the administrator never
returned. RHEL 9.8's cloud-init package makes `/run/cloud-init` root-only, so
the command cannot read the status without `sudo`. The page, this release's
page of the guide and the three earlier pages that showed the command now say
`sudo cloud-init status --wait`.

## The setup page

A headless Chromium opened the page three ways: over HTTP and over HTTPS
under the response header [the page's README](../../site/README.md) gives,
and from a local file. At 1280 pixels in the light theme and at 390 pixels in
the dark theme, 48 of 48 steps passed each way:

- the form refuses an empty login, a login or an address that could change a
  command, and a release that is no tag, each with its reason at the field;
- the keyboard alone chooses, moves on and shows the steps;
- the file on the page is, character for character, what `plan.js` gives for
  the answers, and **Copy** and **Download** hand over the same text, **Copy**
  through the clipboard over HTTPS and through the older copy command
  elsewhere;
- a saved address opens on its steps, an address with a hostile or missing
  value opens on the field with the reason, and nothing from the address
  becomes markup;
- no request leaves the page's own folder, the console stays empty, and
  nothing scrolls sideways.

## Offline checks

`python3 scripts/validate.py` and the 568 offline tests pass. The 52 added for
this release run both scripts with stand-ins for what needs root or a network,
and run the page's logic in Node: every stop and its reason, the installer and
its options per system, the second run after an HTTPS step that failed, the
embedded file against the guide's, each printed command against the script or
the page it comes from, each link against a heading that exists, and the
values the page lets through against what the scripts take.

An independent review of the first version found twelve things, among them a
second run that reported success for an HTTPS publication that had failed, an
address the page accepted and `expose-semaphore.sh` refuses, a release value
that could point the page's links at another repository, and missing
prerequisites in the Proxmox step. All are fixed, and the fixes of the first
two ran on the Ubuntu machine as the table above shows.

## Not established

- **A new VM from a cloud image, on any platform.** The first boots were
  replayed on existing machines. On Proxmox the `qm` commands are Stage 3's,
  which created target VMs before, with the controller's size.
- **Azure.** The file has not run as custom data there.
- **AlmaLinux and Rocky Linux,** whose installer is the one RHEL ran.
- **RHEL before registration,** and a VM without outbound HTTPS: offline
  tests only.
- **A first boot together with Proxmox's own package upgrade,** which a new
  VM there runs first.
- **An installer that fails at its HTTPS step during the first boot.** The
  second run that finishes it ran on a machine; the failure before it was
  made in the offline tests.
- **The page in Firefox and Safari.** Chromium only.
- **An IPv6 address,** which the page leaves to `expose-semaphore.sh`.
