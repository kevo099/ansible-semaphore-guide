# Validation record: feature names, tabs and folders, November 2026

[Back to validation and limits](../VALIDATION.md) · [Update a controller](../controller-update.md#feature-names-tabs-and-folders)

On 13 November 2026 release `v1.12.0` was prepared: what the installer seeds
is named after its feature, each feature has a tab in Semaphore, and each
feature's playbooks have a folder. This record says what ran on machines for
it, as a new installation and as an update of controllers of two earlier
releases, and what remains unverified.

## Where

Two virtual machines on Proxmox VE, each returned to its snapshot afterwards:
`rhel9-vendor01`, RHEL 9.8, and `ubuntu24-vendor01`, Ubuntu 24.04.5. Each was
the controller and its own target. Semaphore 2.19.12, ansible-core 2.21.4. The
browser was a headless Chromium driven by Playwright 1.63.0; its
[16-step walk](2026-11-hardened-controller.md#rounds-6-and-7-the-browser-and-fips-mode)
is the one of the hardened-controller record, with the names of this release.

## An update of a v1.11.0 controller

RHEL, installed from the published `v1.11.0` with `--expose https`, onboarded,
with **Ping**, **Baseline preview** and **Users** in its history, a template
of the reader's own that ran `playbooks/patch.yml`, and a playbook of the
reader's own in the lab folder.

| Step | Result |
| --- | --- |
| `update-controller.sh` from this release | The plan: eight renames, the tab **Examples** to add, **Users** and **Webserver** to move, ten seeded templates to point at new paths, and the reader's template listed as one that names an earlier path. Nothing changed. |
| `--apply` | Each rename was read back and confirmed: the project, the repository, the inventory, both keys, the variable group, the tab and the administrator. 34 files were committed in the lab folder, then ten templates were pointed at the new paths. `The readiness check passed`. |
| **Ping**, **Baseline preview**, **Users**, **Health report**, **RHEL 9 · STIG audit** | Passed, so the SSH key and the sudo password kept their secrets under their new names. |
| The reader's template, still on `playbooks/patch.yml` | Passed: the thin playbook at the earlier path ran the moved one. |
| `lab-sudo.py` | `'Inventory file' already uses the key 'Target sudo password'`; nothing changed. |
| The plan again | Nothing to do, beside the reader's template. The reader's playbook was in place, and the marker file had its new name. |
| The walk by address over HTTPS | Passed, 16 of 16, with the project **Ansible Automation** and the administrator **Ansible Admin**. |

**Found here:** after the rename the tab **Baseline** came before
Semaphore's own **All** tab. Both had position 0, and of two tabs at one
position the one saved last comes first. A fresh installation now starts its
tabs at position 1, and an update moves every other tab one place up, once.
On this controller that renumbered eight tabs; **All** was first again, and a
further plan had nothing to do.

## A new installation

| Machine | Result |
| --- | --- |
| RHEL 9.8, `--expose https` | Installed and seeded; the onboarding, `lab-sudo.py`, 18 checks true. The walk passed by address over HTTPS and through the tunnel, 16 of 16 each, with nine tabs in the order **All**, **Baseline**, **Patching**, four **STIG ·** tabs, **Operations**, **Examples**; the certificate's name was `Semaphore controller`. **Baseline apply**, **Users**, **Webserver**, **Health report**, **Patch preview** and **RHEL 9 · STIG audit** passed. **RHEL 9 · STIG apply (approval required)** against the controller itself passed from its new folder: 267 failing rules before, 13 after. The update tool's plan had nothing to do. |
| Ubuntu 24.04, `--expose https` | Installed and seeded; the onboarding, `lab-sudo.py`, 18 checks true. The walk passed by address over HTTPS, 16 of 16. **Baseline apply**, **Users**, **Webserver**, **Health report**, **Patch preview** and **Ubuntu 24.04 · STIG audit** passed. |

## An update of a v1.6.1 controller

RHEL, installed from `v1.6.1`, which seeded twelve templates on the tabs
**Lessons**, **Patching** and **STIG** and kept its tools in `scripts/`.

| Step | Result |
| --- | --- |
| `update-controller.sh` from this release | The plan: seven renames, three tabs to renumber, two variable groups, six tabs and 16 templates to add, the two examples to move, twelve templates to point at new paths, the four earlier STIG templates among them, and six replaced objects. |
| `--apply` | The renames confirmed, 37 files committed, twelve templates pointed at new paths, `The readiness check passed`. The plan then listed only the six replaced objects as kept. |
| `--apply --remove-replaced`, `update-runtime.sh --apply` | The replaced objects removed; SSH connection reuse added. A further plan had nothing to do. The folder `playbooks/templates/`, which the update emptied, was gone. |
| `onboard-target.sh` after copying the service key, `lab-sudo.py`, `check-controller.py` | Passed; the key **Target sudo password** was created; 16 checks true. |
| The walk through the tunnel | Passed, 16 of 16, with the nine tabs in order. |
| **Baseline preview**, **Users**, **Health report**, **Patch preview**, **RHEL 9 · STIG audit** | Passed. The project had 24 templates and none of the earlier STIG ones. |

## After the review: a v1.11.0 controller with things of the reader's own

An independent review of the first rounds found nine things, among them how
the shared checks find their files, a login that may not rename, and edits and
values of the reader's own beside the playbooks that moved. After the fixes, a
RHEL controller was installed from the published `v1.11.0` with
`--expose https`, onboarded, and given: a template on `playbooks/patch.yml`; a
playbook directly in `playbooks/` that imports the guide's shared checks, with
its template; an edit of `playbooks/patch.yml`, committed in the lab folder; a
file in `playbooks/host_vars/`; and a second Semaphore user with the project
role **Manager** and an API token.

| Step | Result |
| --- | --- |
| The plan | Status 1 with three problems: the file both changed; `playbooks/patch.yml ... this release moved it to playbooks/patching/patch.yml`, with the `git show` command for the reader's version; and `playbooks/host_vars holds values that Ansible reads only for a playbook directly in playbooks/`. Nothing changed. |
| The folder moved to `inventories/host_vars`; the plan with the manager's token and `--replace-edited` | Status 0. Six renames, and two notes: `The project keeps its name 'Ansible Practice': this login may not rename a project`, and `The administrator's name was not looked at`. Seven tabs to renumber, ten templates to point at new paths, the replaced edit named with its commit. |
| `--apply --replace-edited` with the manager's token | The six renames confirmed, 34 files committed, ten templates pointed at the new paths, `The readiness check passed`. |
| The plan and `--apply` as the administrator | Two renames, the project and the administrator, and nothing else; both confirmed. A further plan ended with `Plan only. There is nothing to change.` |
| **Ping**, **Baseline preview**, **Users**, **Health report**, **Patch preview**, **RHEL 9 · STIG audit** | Passed; the audit found its summarizer and content folder from `playbooks/stig/`. |
| The reader's template on `playbooks/patch.yml`, and the reader's playbook in `playbooks/` | Both passed; the second ran the guide's shared checks from where it is. |
| A copy of **Users** with a variable group that sets `lab_practice_users` | Stopped before any change: `The variable lab_practice_users is now lab_example_users; rename it where you set it.` |
| The nine thin playbooks, from the command line | Each passed `--syntax-check`. `ansible-inventory --host` showed the value from `inventories/host_vars`. |
| `check-controller.py`; the walk by address over HTTPS | 18 checks true. The walk passed, 16 of 16, with the nine tabs in order. |
| `git revert HEAD` in the lab folder | **Ping**, which names the new path, failed, and the reader's template on the earlier path passed. The plan stopped and named the revert commit. After `git revert` of that commit the files were back, the plan had nothing to change, and **Ping** passed. |

## Offline checks

`python3 scripts/validate.py` and the 516 offline tests pass. The tests added
for this release cover the plan and the result of the update on a project as
`v1.11.0` seeded it; that a second update changes nothing; that the playbook
paths change only after the lab folder holds the new ones; what a reader
renamed, moved or changed, before or after the plan; a new name that
something else has; a rename that Semaphore saved otherwise or not at all; a
login that is no administrator; the tabs' places; the marker file; the thin
playbooks at the earlier paths; the sudo key under its earlier name; and the
wording of everything the guide installs.

One test runs Ansible itself: a play that imports the guide's shared checks is
run from a thin playbook, a feature's folder, `playbooks/` itself,
`playbooks/site/` and one folder deeper, and each finds its files.

## Not established

- **The update on Azure, and of a controller that was updated several times
  before.** Both updates started from a new installation of the earlier
  release.
- **The update of an Ubuntu controller, and of a hardened one.** The new
  installation ran on Ubuntu; the hardened rounds ran on `v1.11.0`.
- **A name that is taken, two objects with an earlier name, a project found
  with `--project-id`, schedules and vault passwords on the templates that
  moved.** Offline tests only. Of the logins that are no administrator, the
  project role Manager ran; an owner's did not.
- **The thin playbooks from the command line.** One ran through a template;
  from the command line only their syntax check ran.
- **A project whose templates run from a Git repository,** as
  [the Git migration appendix](../appendices/git-migration.md) sets up. The
  update renames and repoints what is bound to the lab folder's repository;
  what it reports for templates of another repository was not run.
- **The exercises of chapters 15 to 18,** which create and name objects of
  their own; they were not run again with the new names of the seeded ones.
- **AlmaLinux and Rocky Linux controllers.**
