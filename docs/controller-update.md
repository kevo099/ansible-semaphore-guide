# Update a controller to a newer guide release

[Back to the guide](../README.md) · [Stage 1: install the controller](stage-1-controller.md)

**Where: the controller, as its administrator.** A controller whose installer
seeded the practice project can take a newer release of the guide without being
reinstalled: any Enterprise Linux controller, and an Ubuntu controller installed
from release `v1.5.0` on. An Ubuntu controller from an earlier release, or one
built [by hand](manual-controller-ubuntu.md), has no seeded project, so the
update tool refuses it with `This controller was not set up by an installer
that seeds Semaphore; there is nothing to update.`; build its project by hand
as [chapter 6](06-semaphore.md) describes. The installers refuse to run a
second time, so use [`controller/update-controller.sh`](../controller/update-controller.sh)
instead of installing again. It works the same on Ubuntu and Enterprise Linux
controllers, including the SELinux labels of the files it writes.

The whole upgrade is at most four steps, each described below. A controller
installed from `v1.8.0` or later needs only the first two.

1. [Get the newer copy](#do-get-the-newer-copy-of-the-guide) and
   [read the plan](#do-read-the-plan).
2. [Apply the update](#do-apply-the-update) to the lab folder and the
   Semaphore project.
3. [Update the Ansible runtime and Semaphore's SSH settings](#do-update-the-ansible-runtime-and-semaphores-ssh-settings),
   when the last lines of the plan name them.
4. If you like, [bring machines you added earlier to the current
   standard](#do-bring-earlier-machines-to-the-current-standard).

## Controllers installed from v1.8.0 or earlier

Releases up to `v1.8.0` kept the controller tools in the guide's `scripts/`
folder. Newer copies of the guide keep them in `controller/`, and this page
uses those paths.

- In the newer copy, `sudo bash scripts/update-controller.sh` still works for
  one release: it is a small wrapper that passes its options on to
  `controller/update-controller.sh`. Prefer the new path.
- VMs prepared with an earlier copy of the onboarding files print
  `sudo bash scripts/add-target.sh --from-info`. That command also still works
  in the newer copy for one release, through the same kind of wrapper; the new
  path is `controller/add-target.sh`.
- Nothing in the lab folder or in Semaphore moves. The lab folder keeps
  `playbooks/`, `ansible.cfg` and `scripts/summarize_xccdf.py` where they
  were, and the seeded templates keep running the same playbook paths.
- Earlier versions of this page cloned each release into a new folder, such as
  `~/guide-v1.8.0`. You can keep using that folder as the guide's folder, or
  clone again into `~/ansible-semaphore-guide`.

## Do: get the newer copy of the guide

**Where: the controller, in the guide's folder, as your administrator.**
Replace `RELEASE_TAG` with the tag of the release you want, as the repository's
releases page names it; `git tag --list` shows the tags you have after the
fetch:

```bash
cd ~/ansible-semaphore-guide   # or your guide's folder, such as ~/guide-v1.8.0
git status --short
git fetch --tags origin
git checkout RELEASE_TAG
```

`git status --short` should print nothing; if it lists a guide file you edited,
copy your edit aside first. Git warns that the checkout is a "detached HEAD";
that is expected for a release tag. Run every command on this page from this
folder, and run `add-target.sh` from it too.

## Do: read the plan

```bash
sudo bash controller/update-controller.sh
```

Without options it only shows its plan, and it exits with status 1 while the
plan lists a problem, ending with `Plan only. Resolve the N problem(s) above
before you run it with --apply.` For each guide file in the lab folder
(`playbooks/`, `ansible.cfg` and the report summarizer) it compares three
versions: yours, the guide's version you last installed, and the new one.

- A file only the new release changed is updated, and a file it no longer
  ships is removed if you never changed it.
- A file only you changed is kept as it is.
- A guide file you deleted stays deleted, unless the release changed it.
- Anything both changed stops the update: a file you and the release both
  changed, a file you changed that the release removes, a guide file you
  deleted that the release changed, or a file of yours at a path the release
  now uses. Compare them and decide; `--replace-edited` takes the release's
  version, and the folder's Git history keeps yours.
- Other files you added are never touched.

The plan also lists the `content/` folders it would create for SCAP files you
supply, the Semaphore variable groups, template tabs and templates it would
add, the seeded templates it would put on a tab, and the seeded objects that
this release replaces. It shows whether the readiness check passes before the
update. Its last lines name the Ansible runtime and Semaphore's SSH settings
when those are older than this copy, as
[their section](#do-update-the-ansible-runtime-and-semaphores-ssh-settings)
shows.

To keep the plan, add `| tee ~/update-plan.txt` to the command. When the tool
asks for a Semaphore login, the question appears on the terminal and stays out
of the saved file.

## Do: apply the update

When the plan is what you expect, apply it:

```bash
sudo bash controller/update-controller.sh --apply
```

It changes nothing when the lab folder has staged changes, uncommitted changes
to guide files, a link where a guide file or folder belongs, files that both
changed, or no `.guide-files.json` after an earlier update; it then says how to
restore that file from Git, or how to apply a reverted update again. Each
uncommitted guide file comes with advice: when `.guide-files.json` is among
them, an earlier update wrote every file and stopped before its commit, so
commit them together; otherwise commit your own edit, or discard what an
interrupted update wrote. It also refuses to run twice at once, to run while
`semaphore.service` is stopped, and to update a lab folder that belongs to
root. It finds the installer's first commit on any local branch, so a folder
whose history was re-rooted as [the Git migration appendix](appendices/git-migration.md)
shows updates normally while the old history is kept on a local branch.

It then logs in to Semaphore and checks the project before changing anything.
Only templates bound to the lab folder's repository and inventory count as
seeded, so a template of yours with the same name is left alone. In Semaphore it
adds what the project lacks, and puts a seeded template that has no tab on its
tab. When all your seeded templates use the same vault password, as the
per-target sudo option in
[Stage 4](stage-4-add-target-first-job.md#do-give-semaphore-the-sudo-password)
sets up, the new templates get it too. Before it edits any template, it saves
every template to a root-only file under `/root/ansible-lab-update/`, and it
confirms each template it edits, putting it back if Semaphore changed any other
setting. If it cannot confirm an edit, it leaves a `pending-template-ID.json`
record there, and later runs stop until you have checked that template in the
UI and deleted the record. It never changes Semaphore itself, the database,
Ansible, the inventory, keys, a template's variable groups, or a tab you chose,
and it deletes nothing unless you ask, as
[the STIG tab section](#from-one-stig-tab-to-one-per-system) describes.

Last, it checks that the lab folder is exactly as planned; if you edited a
guide file meanwhile, it stops without touching the folder, and a second run
picks up from there. If writing the files fails part way, for example on a
full disk or Ctrl-C, it puts back the files it had written, says that nothing
in the folder changed while Semaphore is already updated, and stops; run it
again once the cause is fixed. If you save a file in the very moment it is
replaced, the swap is undone, your version stays, and the update stops. It
writes the files as the lab folder's owner, so the `semaphore` group can still
read them, restores SELinux labels on Enterprise Linux, and commits them in the
folder's Git history with `.guide-files.json`, the record of the guide's own
versions that the next update compares with. A second run reports nothing to
do.

`git revert HEAD` in the folder undoes that commit's files, not the Semaphore
changes: the tabs and templates the update added stay and need those files,
and templates removed with `--remove-replaced` stay removed. If that update
was the folder's first, which created `.guide-files.json`, the next update
stops and names the revert commit; to apply the update again, revert that
commit with `git revert COMMIT` as the folder's owner and run the update. After
a later update, the revert restores the previous record, so the next update
plans the same changes again; check its plan before `--apply`.

## Options and logins

With a different lab folder, add the same `--lab-dir DIR` the installer used;
without it, the update stops with `No lab folder at /opt/ansible-lab; pass the
--lab-dir the installer used.` If several projects share the seeded project's
name, pass `--project-id` with its ID.

If you changed the administrator's password in the UI, as Stage 1 asks, the
stored installer password no longer works, and the update asks for a Semaphore
administrator's login and password at the terminal. A password login cannot
pass a second factor, so when the administrator uses one, as
[chapter 15](15-identity.md) sets up, use a token. For a token, or an
unattended run, create an API token for a Semaphore administrator, or for the
project's owner or a manager, as
[chapter 17](17-api-and-integrations.md#do-inspect-swagger-and-token-access)
shows, pass it as `SEMAPHORE_API_TOKEN` with
`sudo --preserve-env=SEMAPHORE_API_TOKEN`, and delete the token afterwards.

## The Operations tab

A controller installed before the **Operations** tab existed gets it from the
update: `--apply` adds the tab after your existing tabs, with its two
templates, **Health report** and **Reboot one target**, and copies their
playbooks, `playbooks/report.yml` and `playbooks/reboot.yml`, into the lab
folder. It changes nothing else: your other tabs keep their order, and no
other template changes. The plan lists them under `Template tabs to add` and
`Templates to add`. The new controller tools of the same release,
`controller/onboard-target.sh`, `controller/lab-sudo.py` and
`controller/remove-target.sh`, run from the guide's folder and need nothing
from the update; on a controller installed earlier, make the copy of the
service key that Stage 3 uses yourself, as
[Stage 1](stage-1-controller.md#do-save-the-service-key) shows.

## From one STIG tab to one per system

Release `v1.7.0` replaced the single **STIG** tab with one tab per system and
version. An update adds the new tabs and templates and keeps the old STIG
objects, so nothing you ran disappears; the old templates still work and audit
every supported system at once. Which old objects a controller has depends on
the release it was installed from or last updated to: from `v1.6.x`, four STIG
templates, the **STIG** tab and the **Local SCAP content** variable group; from
`v1.5.0`, the four templates and the variable group, without a tab; from
earlier releases, three templates. The plan lists them as replaced. If you
scanned with a SCAP file of your own, move it into its system's folder, for
example with
`mv /opt/ansible-lab/content/U_RHEL_9_V2R9_STIG_SCAP_1-3_Benchmark.xml /opt/ansible-lab/content/rhel/9/`
as the folder's owner, where the variable group **DISA SCAP file · RHEL 9**
expects DISA's RHEL 9 benchmark, or edit that group's path. A group seeded
before this release names the V2R9 file; one seeded now names the folder
`content/rhel/9`, and the playbook scans with the one benchmark there. Once you have
checked the new tabs, delete the old objects with:

```bash
sudo bash controller/update-controller.sh --apply --remove-replaced
```

It deletes them only after the lab folder holds the new playbooks, and saves
the templates, the tab, the variable group and their schedules and
integrations to a root-only file under `/root/ansible-lab-update/` first.
Deleting a template in Semaphore also deletes its task history, so keep any
task output you need first; the backup holds settings, not runs. Deleting a
template would also delete its schedules and integrations, so the update keeps
any old template that one of them still runs: the plan lists it with each
schedule's and integration's name, for example `schedule 'nightly audit' (ID 1)
runs it`. Recreate those on the per-system templates, such as **RHEL 9 · STIG
audit**, delete them from the old template, and run `--apply --remove-replaced`
again. The tab and the variable group are deleted only when no other template
uses them, and a **Local SCAP content** group that you filled in is kept with
your values; delete it in the UI once you have copied them.

STIG reports from `v1.8.0` on go to one folder per run, named after the
controller's UTC start time with a trailing `Z`, such as `20261019T061020Z`;
folders from earlier runs keep their old names.

## Readiness before and after

It runs the readiness check before and after the update. A check that already
failed before is listed with its fix, and the update still completes; only a
check that newly fails ends it with an error. On a controller whose UI was
exposed over HTTPS before 24 September 2026, expect
`nginx_listens_only_where_expected`: the exposure script then left nginx's
default site on port 80. Run it again from the new copy, which removes that site
and keeps your certificate, so the browser's fingerprint does not change:

```bash
sudo bash controller/expose-semaphore.sh --mode https
```

On a controller already exposed over HTTPS, or on loopback, this does not
restart Semaphore, so running tasks continue.

## Do: update the Ansible runtime and Semaphore's SSH settings

Two things live outside the lab folder and the Semaphore project, so the
update tool leaves them alone. It ends its plan and its update by naming them
when they are older than this copy:

```text
Also older than this copy of the guide, and left alone by update-controller.sh:
  Ansible runtime /opt/ansible-venv: 2.20.8 installed, 2.21.4 pinned
  SSH connection reuse for Semaphore jobs: not set
To see and apply those: sudo bash controller/update-runtime.sh
```

- **The Ansible runtime.** Releases `v1.1.0` and `v1.2.0` installed ansible-core
  2.20.8, and every later release 2.21.4. The 2.20 line has had security fixes
  only since 2 November 2026.
- **SSH connection reuse.** A controller installed before `v1.8.0` keeps its
  `/etc/semaphore/config.json`, whose `ANSIBLE_SSH_ARGS` lacks the connection
  reuse that the lab's `ansible.cfg` gives terminal runs, so every task of a
  Semaphore job opens a new SSH login. In the test, **Baseline preview** against
  four targets went from 19 to 14.5 seconds with it.

[`controller/update-runtime.sh`](../controller/update-runtime.sh) updates both.
Without options it shows its plan and changes nothing:

```bash
sudo bash controller/update-runtime.sh
sudo bash controller/update-runtime.sh --apply
```

`--apply` stops Semaphore, installs the versions that
[`requirements-controller.txt`](../requirements-controller.txt) pins into
`/opt/ansible-venv` in place, adds the reuse to `ANSIBLE_SSH_ARGS`, starts
Semaphore again and runs the readiness check. It ends with `Updated. The
readiness check passed.`, and Semaphore was down for a few seconds in the test.
It changes only what its plan lists and keeps packages you added to the virtual
environment. A second run reports `Nothing to do: both match this copy of the
guide.` While a Semaphore task runs it stops and changes nothing, because
stopping Semaphore stops that task: run it when no task is running, or add
`--force`.

It does not change Semaphore itself or PostgreSQL. Every release so far
installs Semaphore 2.19.12 and PostgreSQL 16, so those are already the versions
this copy names.

Before it changes anything, it saves two root-only files under
`/root/ansible-lab-update/`: the list of installed packages,
`ansible-venv-before-TIME.txt`, and the configuration as it was,
`semaphore-config-before-TIME.json`, which holds Semaphore's secrets. If the
installation fails, it installs the saved versions again by itself. To go back
later, while no task runs:

```bash
sudo systemctl stop semaphore
sudo /opt/ansible-venv/bin/pip install --requirement /root/ansible-lab-update/ansible-venv-before-TIME.txt
sudo install -m 0640 -o root -g semaphore /root/ansible-lab-update/semaphore-config-before-TIME.json /etc/semaphore/config.json
sudo systemctl start semaphore
```

## Do: bring earlier machines to the current standard

Machines you added with an earlier release keep working. The update changes
nothing on them, and their inventory lines and trusted host keys stay. A
machine that was prepared by hand, or by an earlier copy of the onboarding
files, can still differ from what the onboarding script sets up today: the
sudo rule in `/etc/sudoers.d/90-ansible-lab`, the SSH drop-in that keeps
`svc_ansible` key-only, and authorized keys that are exactly the service key.
To bring such machines in line, run the one command of
[Stage 2](stage-2-existing-machines.md) for them. `--keep-password` leaves each
account's sudo password as it is:

```bash
bash controller/onboard-target.sh ADMIN@VM_ADDRESS ADMIN@OTHER_ADDRESS --keep-password
```

For a machine that the inventory lists under the name you gave it at the time,
it says `Already present as NAME: ...; nothing changed.` and keeps that name,
and the run ends with `Prepared and in the inventory: ...`. The account's
authorized keys become exactly the service key, so pass `--extra-key FILE` for
a key of your own that must stay. Afterwards
`sudo python3.12 controller/lab-sudo.py` reports that the lab inventory already
uses your **Lab sudo** key, and **Ping** and **Baseline preview** pass as
before.

## Check

The update ends with `Updated to RELEASE_TAG. The readiness check passed.`, or
with the readiness checks that already failed before it. The **Task Templates**
page shows the tabs **Lessons**, **Patching**, one **STIG ·** tab per system and
**Operations** beside **All**, and **Ping** still succeeds. After
`update-runtime.sh --apply`, `/opt/ansible-venv/bin/ansible --version` names
the pinned ansible-core, and its plan reports nothing to do. On a controller updated from
`v1.6.x`, the old **STIG** tab stays until you remove it; older controllers
keep their old STIG templates under **All**.

## When it fails

Every stop names its fix; [controller update
stopped](11-troubleshooting.md#controller-update-stopped) lists the messages
and next steps.
