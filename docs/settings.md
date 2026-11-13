# Settings and your own playbooks

[Back to the guide](../README.md) · [Chapter 6: Semaphore](06-semaphore.md) · [Runbooks](runbooks.md)

The guide's playbooks carry their own defaults, and the installer copies them
into the lab folder. This page lists the few values that are meant to be
changed, how to change one without editing a playbook, and where playbooks of
your own belong. Editing a guide playbook works too, but the
[update tool](controller-update.md#do-read-the-plan) then treats that file as
yours and stops when a release changes it as well.

## Where each kind of setting lives

| What | Where | Who changes it |
| --- | --- | --- |
| The Semaphore service: its address, database and SSH options | `/etc/semaphore/config.json`, readable by root and the service | The installer, `expose-semaphore.sh` and `update-runtime.sh` |
| How Ansible behaves in a run | `ansible.cfg` in the lab folder | The guide; an edit of yours is kept by updates |
| The machines and their groups | `inventories/lab.ini` in the lab folder | `add-target.sh`, `onboard-target.sh` and `remove-target.sh` |
| The SSH key and the sudo password | Semaphore's Key Store: **Target SSH key** and **Target sudo password** | The installer and `lab-sudo.py` |
| A playbook's values, below | The playbook itself, overridden by a variable group | You, in Semaphore |

## The values you can change

| Variable | Default | Playbook | Meaning |
| --- | --- | --- | --- |
| `allow_reboot` | `false` | Patch, STIG apply | Reboot a target when the system asks for it. The seeded variable group **Allow required reboot** sets it. |
| `report_disk_limit` | `90` | Health report | Percent of the root file system from which a host needs attention. |
| `report_memory_limit` | `90` | Health report | Percent of memory in use from which a host needs attention. |
| `report_units_shown` | `5` | Health report | How many failed units the report names. |
| `stig_profile_el` | `xccdf_org.ssgproject.content_profile_stig` | STIG audit and apply | The vendor profile on Enterprise Linux. |
| `stig_usg_profile` | `disa_stig` | STIG audit and apply | The profile `usg` uses on Ubuntu. |
| `stig_content_file`, `stig_content_profile` | empty | STIG audit | A DISA SCAP benchmark from the lab folder's `content/` folder and its profile. The seeded **DISA SCAP file ·** groups set both. |
| `stig_tailoring_file` | empty | STIG audit and apply | An exceptions file; without it, `content/<system>/<version>/tailoring.xml` is used when it exists. |
| `stig_fetch_remote_resources` | `false` | STIG audit and apply | Let `oscap` download what the content refers to. |
| `lab_example_users` | `lab_alice`, `lab_bob` | Users | The example accounts; each name starts with `lab_`. |
| `lab_web_message` | `I deployed this page with Ansible.` | Webserver | The sentence on the example page. |

[Chapter 9](09-security-benchmarks.md) explains the STIG values, and
[the runbooks](runbooks.md#check-every-machines-health) the report's.

## Do: change a value with a variable group

**Where: Semaphore, as its administrator.** A variable group's **Extra
variables** reach the playbook as `--extra-vars`, which outrank the playbook's
own values. A file under `inventories/group_vars/` cannot change these:
Ansible ranks a play's variables above the inventory's.

1. Open **Variable Groups → New Group**, and name the group after what it
   does, for example `Health report at 80 percent`.
2. Switch **Extra variables** from **Table** to **JSON**, and replace the
   editor's `{}` with the values:

   ```json
   {
     "report_disk_limit": 80,
     "report_memory_limit": 80
   }
   ```

3. Open the template, here **Health report**, and choose that group under
   **Variable Groups** in place of **Defaults**. To keep the seeded template
   as it is, copy it first and change the copy.

**Check:** run the template; the report now names a host from 80 percent on.

## Your own playbooks

The lab folder has one folder per feature under `playbooks/`: `baseline/`,
`patching/`, `operations/`, `stig/` and `examples/`. `tasks/` and `vars/` hold
what those playbooks share.

Put playbooks of your own in `playbooks/site/`, and name the path, such as
`playbooks/site/my-playbook.yml`, as the **Playbook Filename** of a template
on a tab of your own. The update tool never changes a file it did not put
there. One folder below `playbooks/`, a playbook imports the guide's checks of
the limit and the operating system like this:

```yaml
- name: My play
  hosts: lab
  gather_facts: false
  pre_tasks:
    - name: Check scope and supported operating system
      ansible.builtin.import_tasks: ../tasks/preflight.yml
      tags: always
```

Keep values that belong to your machines, not to a playbook, such as
`ansible_port`, in `inventories/group_vars/` or `inventories/host_vars/` in
the lab folder. Ansible reads those two folders beside the inventory for
every playbook, whichever folder the playbook is in; it does not read a
`group_vars/` at the top of the lab folder. The lab folder's `.gitignore`
keeps `inventories/` out of its Git history.
